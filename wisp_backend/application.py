"""Compose the v1 API and lifecycle-owned provider clients."""
import asyncio

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from wisp_backend.api import chat, health, memory, events
from wisp_backend.api.boundary import ChatBoundary, error_response
from wisp_backend.config import Settings
from wisp_backend.errors import ServiceError
from wisp_backend.ledger import SQLiteLedger
from wisp_backend.providers.groq import GroqProvider
from wisp_backend.service import ChatService
from wisp_backend.upstream import create_client


def create_app(transport: httpx.AsyncBaseTransport | None = None, *, settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        config = settings if settings is not None else Settings.from_env()
        ledger = await SQLiteLedger.open(config.ledger_path, config.ledger)
        async def cleanup():
            while True:
                await asyncio.sleep(60)
                try:
                    await ledger.maintain()
                except ServiceError:
                    # Adapter remains fail-closed; do not emit sensitive exceptions.
                    pass
        maintenance = asyncio.create_task(cleanup())
        try:
            async with create_client(config, transport) as client:
                service = ChatService({"groq": GroqProvider(client)}, config.assistants, ledger, config.request_timeout)
                app.state.chat_service = service
                try:
                    yield
                finally:
                    await service.close()
        finally:
            maintenance.cancel()
            await asyncio.gather(maintenance, return_exceptions=True)
            await ledger.close()

    app = FastAPI(title="Wisp API", version="1.0.0", lifespan=lifespan)
    app.add_middleware(ChatBoundary)

    @app.exception_handler(ServiceError)
    async def service_error(request, error: ServiceError):
        return error_response(error.code, getattr(request.state, "request_id", None), error.retry_after_ms, getattr(request.state, "wire_version", 1))

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        return error_response("invalid_request", getattr(request.state, "request_id", None), version=getattr(request.state, "wire_version", 1))

    app.include_router(health.router)
    app.include_router(chat.router)
    app.include_router(memory.router)
    app.include_router(events.router)
    # FastAPI's default 422 envelope is not part of this wire contract.
    default_openapi = app.openapi

    def openapi():
        spec = default_openapi()
        for route in ("/v1/chat", "/v2/chat", "/v3/events", "/v3/chat"):
            spec["paths"][route]["post"]["responses"].pop("422", None)
        return spec
    app.openapi = openapi
    return app
