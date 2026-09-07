"""Local, OpenAI-compatible chat proxy for xAI."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, JsonValue, StrictBool
from starlette.background import BackgroundTask


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str = Field(min_length=1)
    messages: list[dict[str, JsonValue]] = Field(min_length=1)
    stream: StrictBool = False


def create_app(transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        load_dotenv(Path(__file__).with_name(".env"), override=False)
        key = os.getenv("XAI_API_KEY") or os.getenv("token_api")
        if not key or not key.strip():
            raise RuntimeError("Set XAI_API_KEY or token_api in backend_proxy/.env")
        async with httpx.AsyncClient(
            base_url="https://api.x.ai/v1/",
            headers={"Authorization": f"Bearer {key.strip()}"},
            timeout=httpx.Timeout(3600, connect=15, pool=15),
            transport=transport,
            follow_redirects=False,
        ) as client:
            app.state.client = client
            yield

    app = FastAPI(title="Local Grok proxy", lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/chat/completions")
    async def chat(body: ChatRequest, request: Request) -> Response:
        client: httpx.AsyncClient = request.app.state.client
        upstream = None
        try:
            upstream = await client.send(
                client.build_request(
                    "POST", "chat/completions",
                    json=body.model_dump(exclude_unset=True),
                ),
                stream=True,
            )
            headers = {
                name: upstream.headers[name]
                for name in ("content-type", "retry-after", "x-request-id")
                if name in upstream.headers
            }
            if body.stream and upstream.is_success:
                async def chunks() -> AsyncIterator[bytes]:
                    try:
                        async for chunk in upstream.aiter_bytes():
                            yield chunk
                    finally:
                        await upstream.aclose()

                return StreamingResponse(
                    chunks(), status_code=upstream.status_code, headers=headers,
                    background=BackgroundTask(upstream.aclose),
                )
            content = await upstream.aread()
            await upstream.aclose()
            return Response(content, status_code=upstream.status_code, headers=headers)
        except httpx.TimeoutException:
            if upstream is not None:
                await upstream.aclose()
            raise HTTPException(504, "xAI request timed out") from None
        except httpx.RequestError:
            if upstream is not None:
                await upstream.aclose()
            raise HTTPException(502, "Could not reach xAI") from None

    return app


app = create_app()

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
