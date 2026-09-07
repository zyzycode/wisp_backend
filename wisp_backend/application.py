"""Composition root: configuration, resource lifetime and router registration."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from wisp_backend.api import chat, health
from wisp_backend.config import Settings
from wisp_backend.errors import ServiceError
from wisp_backend.providers.groq import GroqProvider
from wisp_backend.service import ChatService
from wisp_backend.schemas import ErrorResponse, ErrorDetail, DeltaEvent, DoneEvent, ErrorEvent
from wisp_backend.upstream import create_client


def create_app(
    transport: httpx.AsyncBaseTransport | None = None,
    *, settings: Settings | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        config = settings if settings is not None else Settings.from_env()
        async with create_client(config, transport) as client:
            app.state.chat_service = ChatService({"groq": GroqProvider(client)}, config.assistants)
            yield

    app = FastAPI(title="Wisp API", version="1.0.0", lifespan=lifespan)

    @app.exception_handler(ServiceError)
    async def service_error(request, error: ServiceError):
        body = ErrorResponse(error=ErrorDetail(code=error.code, message=error.message))
        return JSONResponse(body.model_dump(), status_code=error.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        body = ErrorResponse(error=ErrorDetail(
            code="invalid_request", message="Invalid request. See the API schema.",
        ))
        return JSONResponse(body.model_dump(), status_code=422)

    app.include_router(health.router)
    app.include_router(chat.router)
    # SSE payloads are JSON inside an event stream, rather than HTTP JSON bodies.
    original_openapi = app.openapi

    def openapi():
        spec = original_openapi()
        from pydantic.json_schema import models_json_schema
        _, definitions = models_json_schema(
            [(model, "serialization") for model in (DeltaEvent, DoneEvent, ErrorEvent)],
            ref_template="#/components/schemas/{model}",
        )
        spec["components"]["schemas"].update(definitions["$defs"])
        return spec

    app.openapi = openapi
    return app
