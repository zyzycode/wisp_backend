"""Server-owned routing and response correlation."""
import asyncio
from collections.abc import Mapping

from wisp_backend.config import AssistantSettings
from wisp_backend.errors import ServiceError
from wisp_backend.prompts import build_messages
from wisp_backend.providers.base import Provider
from wisp_backend.schemas import ChatRequest, ChatResponse, ModelReply


class ChatService:
    def __init__(self, providers: Mapping[str, Provider], assistants: Mapping[str, AssistantSettings], deadline: float = 10):
        self.providers = dict(providers)
        self.assistants = dict(assistants)
        self.deadline = deadline
        if "default" not in self.assistants:
            raise ValueError("A default assistant is required")
        for settings in self.assistants.values():
            if settings.provider not in self.providers:
                raise ValueError("Assistant references an unregistered provider")

    async def complete(self, body: ChatRequest) -> ChatResponse:
        settings = self.assistants["default"]
        try:
            result = await asyncio.wait_for(
                self.providers[settings.provider].complete(build_messages(body), settings), self.deadline,
            )
        except asyncio.TimeoutError:
            raise ServiceError("upstream_timeout") from None
        # Revalidate at the service boundary for all provider implementations.
        from pydantic import ValidationError
        try:
            reply = ModelReply.model_validate(result.model_dump(exclude_none=True))
            return ChatResponse(version=1, requestId=body.requestId, **reply.model_dump(exclude_none=True))
        except (ValidationError, AttributeError, TypeError):
            raise ServiceError("invalid_model_response") from None
