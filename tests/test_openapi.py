import json

import httpx
import pytest


def test_public_schema_hides_provider_details(client_factory):
    with client_factory(lambda _: httpx.Response(200)) as client:
        spec = client.get("/openapi.json").json()
        serialized = json.dumps(spec).lower()
        for private in ["groq", "grok", "gpt-oss", "chatmodel", "api_key", "max_completion_tokens"]:
            assert private not in serialized
        schemas = spec["components"]["schemas"]
        assert set(schemas["ChatRequest"]["properties"]) == {"assistant", "messages", "stream"}
        assert schemas["ChatRequest"]["additionalProperties"] is False
        for name in ["ChatResponse", "ErrorResponse", "DeltaEvent", "DoneEvent", "ErrorEvent"]:
            assert name in schemas
        assert client.get("/v1/assistants").json() == {"assistants": [{"id": "default", "name": "Assistant"}]}


@pytest.mark.parametrize("streaming", [False, True])
def test_unknown_assistant(client_factory, body, streaming):
    def upstream(_):
        pytest.fail("Unknown assistant reached upstream")
    with client_factory(upstream) as client:
        response = client.post("/v1/chat/completions", json={**body, "assistant": "missing", "stream": streaming})
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "unknown_assistant"
