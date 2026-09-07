from collections.abc import AsyncIterator
from typing import Protocol

from wisp_backend.schemas import ChatResponse, DeltaEvent, DoneEvent, Message
from wisp_backend.config import AssistantSettings


class Provider(Protocol):
    async def complete(self, messages: list[Message], settings: AssistantSettings) -> ChatResponse: ...

    def stream(self, messages: list[Message], settings: AssistantSettings) -> AsyncIterator[DeltaEvent | DoneEvent]: ...
