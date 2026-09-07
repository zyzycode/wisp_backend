import json

import httpx
import pytest


@pytest.fixture
def upstream_body():
    return {"id": "private-id", "model": "private-model", "choices": [{
        "message": {"role": "assistant", "content": "Hello", "reasoning": "private"},
        "finish_reason": "stop"}], "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5}}


def test_server_owns_payload_and_normalizes_response(client_factory, body, upstream_body):
    def upstream(request):
        assert str(request.url) == "https://api.groq.com/openai/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer test-key"
        assert json.loads(request.content) == {"messages": body["messages"], "model": "openai/gpt-oss-20b",
                                               "stream": False, "max_completion_tokens": 4096}
        return httpx.Response(200, json=upstream_body, headers={"x-request-id": "private-id"})
    with client_factory(upstream) as client:
        response = client.post("/v1/chat/completions", json=body, headers={"Authorization": "Bearer caller"})
        assert response.status_code == 200
        assert response.json() == {"text": "Hello", "finish_reason": "stop",
                                   "usage": {"input_tokens": 2, "output_tokens": 3, "total_tokens": 5}}
        assert "private" not in response.text
        assert "x-request-id" not in response.headers
        assert client.get("/health").json() == {"status": "ok"}


@pytest.mark.parametrize("status,expected,code", [(401, 502, "unavailable"), (400, 502, "unavailable"),
    (429, 429, "rate_limited"), (503, 502, "unavailable")])
def test_upstream_errors_are_private(client_factory, body, status, expected, code):
    with client_factory(lambda _: httpx.Response(status, text="private provider diagnostic")) as client:
        response = client.post("/v1/chat/completions", json=body)
        assert response.status_code == expected
        assert response.json()["error"]["code"] == code
        assert "private" not in response.text


@pytest.mark.parametrize("error,status,code", [(httpx.ConnectError, 502, "unavailable"),
                                               (httpx.ReadTimeout, 504, "timeout")])
def test_network_errors(client_factory, body, error, status, code):
    def upstream(request):
        raise error("private diagnostic", request=request)
    with client_factory(upstream) as client:
        response = client.post("/v1/chat/completions", json=body)
        assert response.status_code == status
        assert response.json()["error"]["code"] == code
        assert "private" not in response.text


@pytest.mark.parametrize("extra", [{"model": "grok-4.6"}, {"provider": "groq"}, {"tools": []},
    {"temperature": 1}, {"messages": []}, {"messages": [{"role": "tool", "content": "x"}]},
    {"messages": [{"role": "user", "content": "x", "secret": "private"}]}, {"stream": "yes"}])
def test_invalid_input_does_not_call_upstream(client_factory, body, extra):
    def upstream(_):
        pytest.fail("Invalid input reached provider")
    with client_factory(upstream) as client:
        response = client.post("/v1/chat/completions", json={**body, **extra})
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_request"
        assert "private" not in response.text


@pytest.mark.parametrize("payload", [{}, {"choices": []}, {"choices": [{"message": {"content": None}}]},
                                      {"choices": "bad"}])
def test_malformed_response(client_factory, body, payload):
    with client_factory(lambda _: httpx.Response(200, json=payload)) as client:
        response = client.post("/v1/chat/completions", json=body)
        assert response.status_code == 502
        assert response.json()["error"]["code"] == "invalid_response"
