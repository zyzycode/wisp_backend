"""Compose the v1 API and lifecycle-owned provider clients."""
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from wisp_backend.api import chat, health
from wisp_backend.api.boundary import ChatBoundary, error_response
from wisp_backend.config import Settings
from wisp_backend.errors import ServiceError
from wisp_backend.providers.groq import GroqProvider
from wisp_backend.service import ChatService
from wisp_backend.upstream import create_client


def create_app(transport: httpx.AsyncBaseTransport | None = None, *, settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        config = settings if settings is not None else Settings.from_env()
        async with create_client(config, transport) as client:
            app.state.chat_service = ChatService(
                {"groq": GroqProvider(client)}, config.assistants, config.request_timeout,
            )
            yield

    app = FastAPI(title="Wisp API", version="1.0.0", lifespan=lifespan)
    app.add_middleware(ChatBoundary)

    @app.exception_handler(ServiceError)
    async def service_error(request, error: ServiceError):
        return error_response(error.code, getattr(request.state, "request_id", None))

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        return error_response("invalid_request", getattr(request.state, "request_id", None))

    app.include_router(health.router)
    app.include_router(chat.router)
    # FastAPI's default 422 envelope is not part of this wire contract.
    default_openapi = app.openapi

    def openapi():
        spec = default_openapi()
        spec["paths"]["/v1/chat"]["post"]["responses"].pop("422", None)
        return spec
    app.openapi = openapi
    return app
