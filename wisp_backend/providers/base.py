"""Internal provider port; does not expose provider envelopes to HTTP callers."""
from typing import Protocol

from wisp_backend.config import AssistantSettings
from wisp_backend.schemas import ModelReply


class Provider(Protocol):
    async def complete(self, messages: list[dict[str, str]], settings: AssistantSettings) -> ModelReply: ...
