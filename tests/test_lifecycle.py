import json

import httpx
import pytest
from fastapi.testclient import TestClient

from wisp_backend.api.dependencies import get_chat_service
from wisp_backend.config import AssistantSettings
from wisp_backend.schemas import ChatResponse, DeltaEvent, DoneEvent
from wisp_backend.service import ChatService


class TrackedStream(httpx.AsyncByteStream):
    def __init__(self, data, error=None):
        self.data = data
        self.closed = False
        self.error = error

    async def __aiter__(self):
        for offset in range(0, len(self.data), 3):
            yield self.data[offset:offset + 3]
        if self.error:
            raise self.error

    async def aclose(self):
        self.closed = True


def wire(text="Hello"):
    return (': keepalive\n\ndata: ' + json.dumps({"choices": [{"delta": {"content": text}, "finish_reason": None}]}) +
            '\n\ndata: ' + json.dumps({"choices": [{"delta": {}, "finish_reason": "stop"}],
                "x_groq": {"usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}}}) +
            '\n\ndata: [DONE]\n\n').encode()


def test_client_shutdown(app_factory, monkeypatch):
    def load_env():
        pytest.fail("Explicit settings must bypass environment")
    monkeypatch.setattr("wisp_backend.application.Settings.from_env", load_env)
    app = app_factory(lambda _: httpx.Response(200))
    with TestClient(app):
        client = app.state.chat_service.providers["groq"].client
        assert not client.is_closed
    assert client.is_closed


def test_sse_normalization_and_close(client_factory, body):
    stream = TrackedStream(wire("Привет"))
    with client_factory(lambda _: httpx.Response(200, stream=stream)) as client:
        response = client.post("/v1/chat/completions", json={**body, "stream": True})
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        assert events == [{"type": "delta", "text": "Привет"}, {"type": "done", "finish_reason": "stop",
                         "usage": {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3}}]
        assert stream.closed
        assert "text/event-stream" in response.headers["content-type"]


@pytest.mark.parametrize("data,error,code", [
    (b'data: not-json\n\n', None, "invalid_response"),
    (b'data: [DONE]\n\n', None, "invalid_response"),
    (b'', httpx.ReadTimeout("private"), "timeout"),
    (b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n', None, "invalid_response"),
])
def test_stream_failure_has_error_not_done(client_factory, body, data, error, code):
    stream = TrackedStream(data, error)
    with client_factory(lambda _: httpx.Response(200, stream=stream)) as client:
        response = client.post("/v1/chat/completions", json={**body, "stream": True})
        assert 'event: error' in response.text
        assert code in response.text
        assert 'event: done' not in response.text
        assert 'private' not in response.text
        assert stream.closed


def test_stream_http_failure(client_factory, body):
    with client_factory(lambda _: httpx.Response(401, text="private")) as client:
        response = client.post("/v1/chat/completions", json={**body, "stream": True})
        assert "event: error" in response.text
        assert "unavailable" in response.text
        assert "private" not in response.text


def test_non_stream_read_error_closes_response(client_factory, body):
    stream = TrackedStream(b'', httpx.ReadTimeout("private"))
    with client_factory(lambda _: httpx.Response(200, stream=stream)) as client:
        assert client.post("/v1/chat/completions", json=body).status_code == 504
        assert stream.closed


def test_provider_swap_keeps_public_contract(app_factory, body):
    class OtherProvider:
        async def complete(self, messages, settings):
            assert settings.model == "internal-other-model"
            return ChatResponse(text="Other", finish_reason="stop")

        async def stream(self, messages, settings):
            yield DeltaEvent(text="Other")
            yield DoneEvent(finish_reason="stop")

    def upstream(_):
        pytest.fail("Wrong provider used")
    app = app_factory(upstream)
    service = ChatService({"other": OtherProvider()}, {"default": AssistantSettings(
        provider="other", model="internal-other-model")})
    app.dependency_overrides[get_chat_service] = lambda: service
    with TestClient(app) as client:
        assert client.post("/v1/chat/completions", json=body).json()["text"] == "Other"
        assert "Other" in client.post("/v1/chat/completions", json={**body, "stream": True}).text


def test_closing_stream_early_releases_upstream():
    import asyncio
    from contextlib import aclosing
    from wisp_backend.providers.groq import GroqProvider
    from wisp_backend.schemas import Message

    stream = TrackedStream(wire())

    async def run():
        async with httpx.AsyncClient(base_url="https://example.test/", transport=httpx.MockTransport(
            lambda _: httpx.Response(200, stream=stream),
        )) as client:
            provider = GroqProvider(client)
            async with aclosing(provider.stream([Message(role="user", content="hi")], AssistantSettings())) as events:
                assert (await anext(events)).text == "Hello"
            assert stream.closed
    asyncio.run(run())


def test_unknown_provider_fails_at_startup():
    with pytest.raises(ValueError, match="unregistered"):
        ChatService({}, {"default": AssistantSettings(provider="missing")})


def test_profile_routes_to_selected_provider(app_factory, body):
    calls = []

    class Provider:
        def __init__(self, name):
            self.name = name

        async def complete(self, messages, settings):
            calls.append((self.name, settings.model, settings.max_output_tokens))
            return ChatResponse(text=self.name, finish_reason="stop")

    service = ChatService({"first": Provider("first"), "second": Provider("second")}, {
        "default": AssistantSettings(provider="first", model="model-a"),
        "writer": AssistantSettings(provider="second", model="model-b", max_output_tokens=256),
    })
    app = app_factory(lambda _: pytest.fail("Unexpected upstream request"))
    app.dependency_overrides[get_chat_service] = lambda: service
    with TestClient(app) as client:
        assert client.post("/v1/chat/completions", json=body).json()["text"] == "first"
        assert client.post("/v1/chat/completions", json={**body, "assistant": "writer"}).json()["text"] == "second"
    assert calls == [("first", "model-a", 4096), ("second", "model-b", 256)]
