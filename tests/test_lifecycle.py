import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from pydantic import SecretStr
from starlette.responses import Response

from wisp_backend.application import create_app
from wisp_backend.api.dependencies import get_chat_proxy
from wisp_backend.config import Settings

BODY = {"model": "test", "messages": [{"role": "user", "content": "hi"}]}


class TrackedStream(httpx.AsyncByteStream):
    def __init__(self, error=None):
        self.closed = False
        self.error = error

    async def __aiter__(self):
        yield b'data: {}\n\n'
        if self.error:
            raise self.error
        yield b'data: [DONE]\n\n'

    async def aclose(self):
        self.closed = True


class LifecycleTests(unittest.TestCase):
    def app(self, handler):
        return create_app(
            httpx.MockTransport(handler),
            settings=Settings(api_key=SecretStr("explicit-key")),
        )

    def test_explicit_settings_and_client_shutdown(self):
        def upstream(request):
            self.assertEqual(request.headers["authorization"], "Bearer explicit-key")
            return httpx.Response(200, json={})

        app = self.app(upstream)
        with patch("wisp_backend.application.Settings.from_env", side_effect=AssertionError):
            with TestClient(app) as client:
                self.assertEqual(client.post("/v1/chat/completions", json=BODY).status_code, 200)
                http_client = app.state.chat_proxy.client
                self.assertFalse(http_client.is_closed)
            self.assertTrue(http_client.is_closed)

    def test_response_streams_close(self):
        for streaming in [False, True]:
            for status in [200, 429]:
                stream = TrackedStream()
                app = self.app(lambda _: httpx.Response(
                    status, stream=stream,
                    headers={"content-type": "text/event-stream", "x-request-id": "req-1"},
                ))
                with self.subTest(streaming=streaming, status=status), TestClient(app) as client:
                    response = client.post("/v1/chat/completions", json={**BODY, "stream": streaming})
                    self.assertEqual(response.status_code, status)
                    self.assertEqual(response.headers["x-request-id"], "req-1")
                    self.assertIn(b"[DONE]", response.content)
                    self.assertTrue(stream.closed)

    def test_read_error_closes_response(self):
        stream = TrackedStream(httpx.ReadTimeout("private diagnostic"))
        with TestClient(self.app(lambda _: httpx.Response(200, stream=stream))) as client:
            response = client.post("/v1/chat/completions", json=BODY)
            self.assertEqual(response.status_code, 504)
            self.assertTrue(stream.closed)

    def test_interrupted_sse_closes_response(self):
        stream = TrackedStream(httpx.ReadError("broken stream"))
        with TestClient(self.app(lambda _: httpx.Response(200, stream=stream))) as client:
            with self.assertRaises(httpx.ReadError):
                client.post("/v1/chat/completions", json={**BODY, "stream": True})
            self.assertTrue(stream.closed)

    def test_proxy_dependency_can_be_replaced(self):
        class StubProxy:
            async def complete(self, body):
                return Response(body.model, media_type="text/plain")

        def upstream(_):
            self.fail("Dependency override must bypass upstream")

        app = self.app(upstream)
        app.dependency_overrides[get_chat_proxy] = lambda: StubProxy()
        with TestClient(app) as client:
            self.assertEqual(client.post("/v1/chat/completions", json=BODY).text, "test")
