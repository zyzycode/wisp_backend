"""Composition root: configuration, resource lifetime and router registration."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from wisp_backend.api import chat, health
from wisp_backend.config import Settings
from wisp_backend.proxy import ChatProxy
from wisp_backend.upstream import create_client


def create_app(
    transport: httpx.AsyncBaseTransport | None = None,
    *, settings: Settings | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        config = settings if settings is not None else Settings.from_env()
        async with create_client(config, transport) as client:
            app.state.chat_proxy = ChatProxy(client)
            yield

    app = FastAPI(title="Local Grok proxy", lifespan=lifespan)
    app.include_router(health.router)
    app.include_router(chat.router)
    return app
