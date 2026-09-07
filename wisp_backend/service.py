"""Choose a server-owned profile and delegate through the provider interface."""
from collections.abc import Mapping

from wisp_backend.config import AssistantSettings
from wisp_backend.errors import ServiceError
from wisp_backend.providers.base import Provider
from wisp_backend.schemas import AssistantInfo, ChatRequest


class ChatService:
    def __init__(self, providers: Mapping[str, Provider], assistants: Mapping[str, AssistantSettings]):
        self.providers = dict(providers)
        self.assistants = dict(assistants)
        for settings in self.assistants.values():
            if settings.provider not in self.providers:
                raise ValueError("Assistant references an unregistered provider")

    def list_assistants(self):
        return [AssistantInfo(id=key, name=value.name) for key, value in self.assistants.items()]

    def resolve(self, body: ChatRequest):
        settings = self.assistants.get(body.assistant)
        if settings is None:
            raise ServiceError("unknown_assistant", "Unknown assistant profile.", 422)
        return self.providers[settings.provider], settings

    async def complete(self, body: ChatRequest):
        provider, settings = self.resolve(body)
        return await provider.complete(body.messages, settings)

    def stream(self, body: ChatRequest):
        provider, settings = self.resolve(body)
        return provider.stream(body.messages, settings)
