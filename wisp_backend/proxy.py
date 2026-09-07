"""Forward responses and manage upstream response lifetime."""

from collections.abc import AsyncIterator

import httpx
from fastapi import HTTPException
from starlette.responses import Response, StreamingResponse
from starlette.background import BackgroundTask

from wisp_backend.schemas import ChatRequest


class ChatProxy:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    async def complete(self, body: ChatRequest) -> Response:
        client = self.client
        upstream = None
        streaming = False
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

                response = StreamingResponse(
                    chunks(), status_code=upstream.status_code, headers=headers,
                    background=BackgroundTask(upstream.aclose),
                )
                streaming = True
                return response
            content = await upstream.aread()
            return Response(content, status_code=upstream.status_code, headers=headers)
        except httpx.TimeoutException:
            raise HTTPException(504, "xAI request timed out") from None
        except httpx.RequestError:
            raise HTTPException(502, "Could not reach xAI") from None
        finally:
            # StreamingResponse owns the resource after a successful handoff.
            if upstream is not None and not streaming:
                await upstream.aclose()

