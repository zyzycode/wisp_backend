"""Internal provider port, separate from the desktop wire."""
from typing import Protocol

from wisp_backend.config import AssistantSettings
from wisp_backend.contracts import ProviderResult, ReplyContext


class Provider(Protocol):
    async def complete(self, messages: list[dict[str, str]], settings: AssistantSettings,
                       timeout: float, reply_context: ReplyContext = ReplyContext()) -> ProviderResult: ...
