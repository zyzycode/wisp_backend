import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from wisp_backend.api.dependencies import get_chat_service
from wisp_backend.config import AssistantSettings
from wisp_backend.schemas import ModelReply
from wisp_backend.service import ChatService


class TrackedStream(httpx.AsyncByteStream):
    def __init__(self, chunks, error=None):
        self.chunks = chunks
        self.closed = False
        self.error = error
        self.read_count = 0

    async def __aiter__(self):
        for chunk in self.chunks:
            self.read_count += 1
            yield chunk
        if self.error:
            raise self.error

    async def aclose(self):
        self.closed = True


def test_client_shutdown(app_factory, monkeypatch):
    def load_env():
        pytest.fail("Explicit settings must bypass environment")
    monkeypatch.setattr("wisp_backend.application.Settings.from_env", load_env)
    app = app_factory(lambda _: httpx.Response(200))
    with TestClient(app):
        client = app.state.chat_service.providers["groq"].client
        assert not client.is_closed
    assert client.is_closed


@pytest.mark.parametrize("chunks,error,status", [
    ([b'{'], None, 502), ([b''], httpx.ReadTimeout("private"), 504),
    ([b'a' * (256 * 1024 + 1), b'not-read'], None, 502),
])
def test_response_closed_and_read_bounded(client_factory, body, chunks, error, status):
    stream = TrackedStream(chunks, error)
    with client_factory(lambda _: httpx.Response(200, stream=stream)) as client:
        assert client.post("/v1/chat", json=body).status_code == status
        assert stream.closed
        assert stream.read_count == 1


def test_provider_swap_and_total_deadline(app_factory, body):
    class OtherProvider:
        async def complete(self, messages, settings):
            assert settings.model == "internal-other-model"
            return ModelReply(text="Other")

    app = app_factory(lambda _: pytest.fail("Wrong provider"))
    service = ChatService({"other": OtherProvider()}, {"default": AssistantSettings(provider="other", model="internal-other-model")})
    app.dependency_overrides[get_chat_service] = lambda: service
    with TestClient(app) as client:
        assert client.post("/v1/chat", json=body).json()["text"] == "Other"

        class SlowProvider:
            cancelled = False
            async def complete(self, messages, settings):
                try:
                    await asyncio.sleep(10)
                finally:
                    self.cancelled = True
        slow = SlowProvider()
        service.providers["other"] = slow
        service.deadline = .01
        response = client.post("/v1/chat", json=body)
        assert response.status_code == 504
        assert slow.cancelled


def test_unknown_provider_fails_at_startup():
    with pytest.raises(ValueError, match="unregistered"):
        ChatService({}, {"default": AssistantSettings(provider="missing")})
