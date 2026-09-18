import json
from pathlib import Path
import sqlite3

import httpx
import pytest
from pydantic import ValidationError

from wisp_backend.events_schemas import EventRequest, EventAwareChatRequest

FIXTURES = Path(__file__).parent/'fixtures/desktop-backend-v3'


def fixture(name):
    return json.loads((FIXTURES/name).read_bytes())


@pytest.mark.parametrize('outcome', ['caught', 'missed', 'lost_target'])
def test_event_game_bounds(outcome):
    body = fixture('request.game.json')
    body['event']['outcome'] = outcome
    for duration in [0, 60000, .5]:
        body['event']['executedMs'] = duration
        EventRequest.model_validate(body)
    for duration in [-.1, 60000.1, True, '100', None, float('inf'), float('nan')]:
        body['event']['executedMs'] = duration
        with pytest.raises(ValidationError):
            EventRequest.model_validate(body)


def test_event_allowed_shapes_and_no_messages():
    base = fixture('request.game.json')
    variants = [
        {**base, 'messages': [{'role': 'user', 'content': 'fake'}]},
        {**base, 'previousInitiative': fixture('request.chat.json')['previousInitiative']},
        {**base, 'event': {**base['event'], 'outcome': 'cancelled'}},
        {**base, 'event': {**base['event'], 'activityRunId': 'local-only'}},
        {**base, 'event': {**base['event'], 'x': 5}},
        {**base, 'event': {**base['event'], 'type': 'sleep_started'}},
        {**base, 'event': {'type': 'social_bid_started', 'occurredAt': base['event']['occurredAt'], 'executedMs': 5}},
        {**base, 'event': {'type': 'social_bid_started', 'occurredAt': '2025-02-29T00:00:00.000Z'}},
        {**base, 'memory': {}},
    ]
    for body in variants:
        with pytest.raises(ValidationError):
            EventRequest.model_validate(body)
    EventRequest.model_validate(fixture('request.social.json'))


@pytest.mark.parametrize('field,value', [
    ('kind', 'user_message'), ('text', ''), ('text', ' '), ('text', '😀'*121),
    ('text', ' '+'a'*240), ('text', 'bad\r'), ('text', 12),
    ('createdAt', '2026-09-18T09:00:00Z'), ('createdAt', '2026-13-01T00:00:00.000Z'),
    ('createdAt', True), ('sourceId', 'local-only'),
])
def test_previous_initiative_strict_fields(field, value):
    body = fixture('request.chat.json')
    body['previousInitiative'][field] = value
    with pytest.raises(ValidationError):
        EventAwareChatRequest.model_validate(body)


def test_previous_initiative_optional_but_not_null_and_exact_limits():
    body = fixture('request.chat.json')
    for kind in ['social_bid', 'cursor_game']:
        body['previousInitiative']['kind'] = kind
        body['previousInitiative']['text'] = '😀'*120
        body['previousInitiative']['createdAt'] = '0000-02-29T00:00:00.000Z'
        EventAwareChatRequest.model_validate(body)
    with pytest.raises(ValidationError):
        EventAwareChatRequest.model_validate({**body, 'previousInitiative': None})
    body.pop('previousInitiative')
    EventAwareChatRequest.model_validate(body)


@pytest.mark.parametrize('reply', [
    {'text': 'ok', 'decision': None}, {'text': 'ok', 'decision': {'behavior': 'respond', 'confidence': 1}},
    {'text': 'ok', 'memoryCandidates': []}, {'text': 'ok', 'requestId': 'model-owned'},
    {'text': 'ok', 'version': 3}, {'text': 'ok', 'state': {'friendship': 1000}},
    {'text': '😀'*121}, {'text': ' '+'a'*240}, {'text': ''}, {'text': 'bad\r'},
])
def test_event_model_extra_fields_fail_with_usage_preserved(app_factory, completion, reply):
    from fastapi.testclient import TestClient
    calls = []
    def upstream(request):
        calls.append(request)
        return httpx.Response(200, json=completion(reply, usage={'prompt_tokens': 2, 'completion_tokens': 3, 'total_tokens': 5}))
    app = app_factory(upstream)
    with TestClient(app) as client:
        body = fixture('request.game.json')
        response = client.post('/v3/events', json=body)
        assert response.status_code == 502
        assert response.json() == {'version': 3, 'requestId': body['requestId'], 'error': {'code': 'invalid_model_response'}}
        replay = client.post('/v3/events', json=body)
        assert replay.content == response.content
        with sqlite3.connect(app.state.chat_service.ledger.path) as db:
            assert db.execute('SELECT requests,reserved,confirmed,uncertain FROM days').fetchone() == (1,0,5,0)
    assert len(calls) == 1


def test_event_reply_utf16_boundary(client_factory, completion):
    with client_factory(lambda _: httpx.Response(200, json=completion({'text': '😀'*120}))) as client:
        response = client.post('/v3/events', json=fixture('request.game.json'))
        assert response.status_code == 200
        assert response.json()['text'] == '😀'*120


def test_old_routes_reject_new_fields(client_factory, body):
    previous = fixture('request.chat.json')['previousInitiative']
    memory = fixture('request.game.json')['memory']
    with client_factory(lambda _: pytest.fail('old version accepted v3 fields')) as client:
        assert client.post('/v1/chat', json={**body, 'previousInitiative': previous}).status_code == 400
        response = client.post('/v2/chat', json={**body, 'version': 2, 'memory': memory, 'previousInitiative': previous})
        assert response.status_code == 400 and response.json()['version'] == 2
