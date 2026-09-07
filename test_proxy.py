import json
import os
import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from main import create_app


class ProxyTests(unittest.TestCase):
    def client(self, handler):
        return TestClient(create_app(httpx.MockTransport(handler)))

    def setUp(self):
        self.env = patch.dict(os.environ, {"XAI_API_KEY": "test-key"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_forwards_body_and_server_token(self):
        body = {"model": "test", "messages": [{"role": "user", "content": "hi"}],
                "temperature": 0.5, "tools": []}

        def upstream(request):
            self.assertEqual(str(request.url), "https://api.x.ai/v1/chat/completions")
            self.assertEqual(request.headers["authorization"], "Bearer test-key")
            self.assertEqual(json.loads(request.content), body)
            return httpx.Response(200, json={"choices": []})

        with self.client(upstream) as client:
            response = client.post("/v1/chat/completions", json=body,
                                   headers={"Authorization": "Bearer caller-key"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"choices": []})
            self.assertEqual(client.get("/health").json(), {"status": "ok"})

    def test_sse(self):
        data = b'data: {"choices": []}\n\ndata: [DONE]\n\n'
        with self.client(lambda _: httpx.Response(
            200, content=data, headers={"content-type": "text/event-stream"}
        )) as client:
            response = client.post("/v1/chat/completions", json={
                "model": "test", "messages": [{"role": "user", "content": "hi"}],
                "stream": True,
            })
            self.assertEqual(response.content, data)
            self.assertIn("text/event-stream", response.headers["content-type"])

    def test_upstream_error(self):
        with self.client(lambda _: httpx.Response(
            429, json={"error": "rate limit"}, headers={"retry-after": "10"}
        )) as client:
            response = client.post("/v1/chat/completions", json={
                "model": "test", "messages": [{"role": "user", "content": "hi"}],
                "stream": True,
            })
            self.assertEqual(response.status_code, 429)
            self.assertEqual(response.json(), {"error": "rate limit"})
            self.assertEqual(response.headers["retry-after"], "10")

    def test_network_errors(self):
        for error, status in [(httpx.ConnectError, 502), (httpx.ReadTimeout, 504)]:
            def upstream(request):
                raise error("private diagnostic", request=request)

            with self.subTest(status=status), self.client(upstream) as client:
                response = client.post("/v1/chat/completions", json={
                    "model": "test", "messages": [{"role": "user", "content": "hi"}],
                })
                self.assertEqual(response.status_code, status)
                self.assertNotIn("private diagnostic", response.text)

    def test_invalid_input_does_not_call_upstream(self):
        def upstream(_):
            self.fail("Invalid input reached xAI")

        with self.client(upstream) as client:
            for body in [{}, {"model": "test", "messages": []},
                         {"model": "test", "messages": [{}], "stream": "yes"}]:
                self.assertEqual(client.post("/v1/chat/completions", json=body).status_code, 422)


if __name__ == "__main__":
    unittest.main()
