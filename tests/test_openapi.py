import json

import httpx


def test_public_schema(client_factory, body):
    with client_factory(lambda _: httpx.Response(200)) as client:
        spec = client.get("/openapi.json").json()
        assert "/v1/chat/completions" not in spec["paths"]
        assert "/v1/assistants" not in spec["paths"]
        operation = spec["paths"]["/v1/chat"]["post"]
        assert set(operation["responses"]) == {"200", "400", "409", "413", "429", "502", "503", "504"}
        schemas = spec["components"]["schemas"]
        assert set(schemas["ChatRequest"]["required"]) == {"version", "requestId", "event", "messages", "stream", "locale", "character"}
        assert schemas["ChatRequest"]["additionalProperties"] is False
        assert schemas["ChatRequest"]["examples"][0] == body
        assert "default" not in schemas["Needs"]["properties"]["boredom"]
        assert set(schemas["ChatResponse"]["properties"]) == {"version", "requestId", "text", "decision"}
        assert "playful" in schemas["Decision"]["properties"]["mood"]["enum"]
        for private in ["groq", "gpt-oss", "quota", "text/event-stream"]:
            assert private not in json.dumps(spec).lower()
        assert client.get("/health").json() == {"status": "ok"}
