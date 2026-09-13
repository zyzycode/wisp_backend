import asyncio
import json
from copy import deepcopy

import pytest
from pydantic import ValidationError

from wisp_backend.api.boundary import ChatBoundary
from wisp_backend.schemas import ChatRequest, ErrorDetail, ModelReply


NUMBERS = [
    ("needs.energy", 100), ("needs.attention", 100), ("needs.play", 100),
    ("needs.comfort", 100), ("needs.boredom", 100),
    ("relationship.friendship", 1000), ("relationship.love", 1000),
    ("personality.traits.shyness", 1), ("personality.traits.playfulness", 1),
    ("personality.traits.sensitivity", 1), ("personality.traits.boldness", 1),
    ("intimacy.flirtiness", 100), ("intimacy.romanticCharge", 100),
]


def put(body, path, value):
    target = body["character"]
    parts = path.split(".")
    for part in parts[:-1]:
        target = target[part]
    target[parts[-1]] = value


@pytest.mark.parametrize("path,maximum", NUMBERS)
def test_numeric_inclusive_ranges_and_types(body, path, maximum):
    for value in [0, maximum, maximum / 2]:
        put(body, path, value)
        ChatRequest.model_validate(body)
    for value in [-.01, maximum + .01, "0", None, True, float("nan"), float("inf")]:
        put(body, path, value)
        with pytest.raises(ValidationError):
            ChatRequest.model_validate(body)


@pytest.mark.parametrize("path", ["relationship.loveUnlocked", "intimacy.userConsentEnabled"])
def test_booleans(body, path):
    for value in [0, 1, "true", None]:
        put(body, path, value)
        with pytest.raises(ValidationError):
            ChatRequest.model_validate(body)


@pytest.mark.parametrize("path,limit", [("personality.presetId", 128), ("personality.aiSelfConcept", 500)])
def test_character_text_limits(body, path, limit):
    put(body, path, "a" * limit)
    ChatRequest.model_validate(body)
    for value in ["a" * (limit + 1), "", " ", "bad\x00", "bad\r", "\ud800", "😀" * (limit // 2 + 1)]:
        put(body, path, value)
        with pytest.raises(ValidationError):
            ChatRequest.model_validate(body)


def test_history_order_and_utf16(body):
    for count in [1, 3, 5, 7]:
        body["messages"] = [{"role": "user" if index % 2 == 0 else "assistant",
                            "content": "😀" * (120 if index % 2 == 0 else 1000)} for index in range(count)]
        ChatRequest.model_validate(body)
    variants = [[], [{"role": "assistant", "content": "hi"}],
        [{"role": "user", "content": "hi"}] * 3,
        [{"role": "system", "content": "hi"}],
        [{"role": "user", "content": "😀" * 121}],
        [{"role": "user", "content": " " + "x" * 240}],
        [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "x" * 2001}, {"role": "user", "content": "hi"}]]
    for messages in variants:
        body["messages"] = messages
        with pytest.raises(ValidationError):
            ChatRequest.model_validate(body)


def test_missing_and_unknown_keys_recursively(body):
    def visit(value, path=()):
        if isinstance(value, dict):
            yield path, value
            for key, child in value.items():
                yield from visit(child, (*path, key))
        elif isinstance(value, list):
            for key, child in enumerate(value):
                yield from visit(child, (*path, key))

    for path, original in visit(body):
        for key in [*original, "unknown"]:
            changed = deepcopy(body)
            target = changed
            for segment in path:
                target = target[segment]
            if key == "unknown":
                target[key] = 1
            else:
                del target[key]
            with pytest.raises(ValidationError):
                ChatRequest.model_validate(changed)


def test_optional_boredom_preserves_absence(body):
    request = ChatRequest.model_validate(body)
    assert "boredom" not in request.character.needs.model_dump(exclude_unset=True)
    body["character"]["needs"]["boredom"] = 0
    assert ChatRequest.model_validate(body).character.needs.boredom == 0


@pytest.mark.parametrize("extra,code", [({"version": 2}, "unsupported_version"),
    ({"version": True}, "invalid_request"), ({"version": 1.0}, "invalid_request"),
    ({"stream": True}, "invalid_request"), ({"stream": 0}, "invalid_request"),
    ({"locale": "de"}, "invalid_request"), ({"quota": {}}, "invalid_request")])
def test_wire_errors_preserve_id(client_factory, body, extra, code):
    with client_factory(lambda _: pytest.fail("Invalid request reached provider")) as client:
        response = client.post("/v1/chat", json={**body, **extra})
        assert response.status_code == 400
        assert response.json() == {"version": 1, "requestId": body["requestId"], "error": {"code": code}}


@pytest.mark.parametrize("request_id", [None, "bad", "02d80270-1a72-17c9-a713-335b872ad24b", 1])
def test_invalid_id_is_null(client_factory, body, request_id):
    with client_factory(lambda _: pytest.fail("Invalid request reached provider")) as client:
        response = client.post("/v1/chat", json={**body, "requestId": request_id})
        assert response.status_code == 400
        assert response.json()["requestId"] is None


@pytest.mark.parametrize("content", [b'{', b'{"version":1,"version":2}', b'{"version":NaN}', b'\xff', b'[]'])
def test_invalid_json(client_factory, content):
    with client_factory(lambda _: pytest.fail("Invalid request reached provider")) as client:
        response = client.post("/v1/chat", content=content, headers={"content-type": "application/json"})
        assert response.status_code == 400
        assert response.json()["requestId"] is None


def test_chunked_limit_stops_reading():
    async def run():
        count = 0
        sent = []
        async def receive():
            nonlocal count
            count += 1
            return {"type": "http.request", "body": b"x" * 16385, "more_body": True}
        async def send(message):
            sent.append(message)
        async def downstream(scope, receive, send):
            pytest.fail("Oversized body reached downstream")
        await ChatBoundary(downstream)({"type": "http", "method": "POST", "path": "/v1/chat",
            "headers": [(b"content-type", b"application/json")]}, receive, send)
        assert count == 2
        assert sent[0]["status"] == 413
        assert json.loads(sent[1]["body"])["error"]["code"] == "payload_too_large"
    asyncio.run(run())


def test_exact_byte_limit(client_factory, body, completion):
    import httpx
    raw = json.dumps(body).encode()
    with client_factory(lambda _: httpx.Response(200, json=completion())) as client:
        raw += b" " * (32768 - len(raw))
        assert client.post("/v1/chat", content=raw, headers={"content-type": "application/json"}).status_code == 200
        assert client.post("/v1/chat", content=raw + b" ", headers={"content-type": "application/json"}).status_code == 413


def test_retry_hint_bounds():
    for value in [1, 86400000]:
        ErrorDetail(code="rate_limited", retryAfterMs=value)
    for value in [0, 86400001, 1.5, True, "1", None]:
        with pytest.raises(ValidationError):
            ErrorDetail(code="rate_limited", retryAfterMs=value)


def test_text_only_response_and_controls():
    assert ModelReply(text=" hi\nthere\t ").text == "hi\nthere"
    assert ModelReply(text="😀" * 1000).text == "😀" * 1000


def test_unicode_trim_and_invalid_surrogate(body):
    body["messages"][0]["content"] = "\ufeff"
    with pytest.raises(ValidationError):
        ChatRequest.model_validate(body)
    assert ModelReply(text="\ufeffHi\ufeff").text == "Hi"
    body["messages"][0]["content"] = "\ud800"
    with pytest.raises(ValidationError):
        ChatRequest.model_validate(body)
