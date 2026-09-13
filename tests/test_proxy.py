import json

import httpx
import pytest


def test_server_owns_prompt_model_and_envelope(client_factory, body, completion):
    def upstream(request):
        assert str(request.url) == "https://api.groq.com/openai/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer test-key"
        payload = json.loads(request.content)
        assert payload["model"] == "openai/gpt-oss-20b"
        assert payload["stream"] is False
        assert payload["response_format"] == {"type": "json_object"}
        assert payload["messages"][0]["role"] == "system"
        assert "Russian" in payload["messages"][0]["content"]
        assert "boredom" not in payload["messages"][1]["content"]
        assert payload["messages"][-1] == body["messages"][-1]
        assert body["requestId"] not in request.content.decode()
        return httpx.Response(200, json=completion(id="private", model="private"), headers={"x-request-id": "private"})
    with client_factory(upstream) as client:
        response = client.post("/v1/chat", json=body)
        assert response.status_code == 200
        assert response.json() == {"version": 1, "requestId": body["requestId"], "text": "Привет!"}
        assert "private" not in response.text
        assert "x-request-id" not in response.headers


@pytest.mark.parametrize("status", [301, 400, 401, 429, 500, 503])
def test_provider_errors_are_not_server_admission_errors(client_factory, body, status):
    calls = []
    def upstream(request):
        calls.append(request)
        return httpx.Response(status, text="private diagnostic", headers={"location": "https://other.test"})
    with client_factory(upstream) as client:
        response = client.post("/v1/chat", json=body)
        assert response.status_code == 503
        assert response.json() == {"version": 1, "requestId": body["requestId"],
                                   "error": {"code": "upstream_unavailable"}}
        assert len(calls) == 1


@pytest.mark.parametrize("error,status,code", [(httpx.ConnectError, 503, "upstream_unavailable"),
                                               (httpx.ReadTimeout, 504, "upstream_timeout")])
def test_network_errors(client_factory, body, error, status, code):
    def upstream(request):
        raise error("private", request=request)
    with client_factory(upstream) as client:
        response = client.post("/v1/chat", json=body)
        assert response.status_code == status
        assert response.json()["error"] == {"code": code}


@pytest.mark.parametrize("decision", [None, {}, {"behavior": "execute", "confidence": 1},
    {"behavior": "respond", "confidence": True}, {"behavior": "respond", "confidence": 1.1},
    {"behavior": "respond", "confidence": .5, "coordinates": [1, 2]},
    {"behavior": "respond", "confidence": .5, "mood": "curious"},
    {"behavior": "respond", "confidence": .5, "tone": None}])
def test_bad_hint_is_dropped(client_factory, body, completion, decision):
    with client_factory(lambda _: httpx.Response(200, json=completion({"text": "Good", "decision": decision}))) as client:
        response = client.post("/v1/chat", json=body)
        assert response.status_code == 200
        assert response.json() == {"version": 1, "requestId": body["requestId"], "text": "Good"}


def test_valid_hint(client_factory, body, completion):
    reply = {"text": "Good", "decision": {"behavior": "respond", "confidence": .9, "mood": "playful"}}
    with client_factory(lambda _: httpx.Response(200, json=completion(reply))) as client:
        assert client.post("/v1/chat", json=body).json() == {"version": 1, "requestId": body["requestId"], **reply}


@pytest.mark.parametrize("reply", [{}, {"text": ""}, {"text": " "}, {"text": "a" * 2001},
    {"text": "😀" * 1001}, {"text": "bad\rtext"}, {"text": "hi", "requestId": "model-owned"},
    {"text": "hi", "quota": {}}, {"text": 123}, {"text": " "+"a"*2000}])
def test_invalid_model_output(client_factory, body, completion, reply):
    with client_factory(lambda _: httpx.Response(200, json=completion(reply))) as client:
        response = client.post("/v1/chat", json=body)
        assert response.status_code == 502
        assert response.json()["error"]["code"] == "invalid_model_response"


@pytest.mark.parametrize("payload", [b'not-json', b'{"choices":[]}', b'{"choices":"bad"}'])
def test_malformed_provider_envelope(client_factory, body, payload):
    with client_factory(lambda _: httpx.Response(200, content=payload)) as client:
        assert client.post("/v1/chat", json=body).status_code == 502
