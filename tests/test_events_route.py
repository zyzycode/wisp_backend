import json
from pathlib import Path

import httpx
import pytest

FIXTURES = Path(__file__).parent / 'fixtures/desktop-backend-v3'


def fixture(name):
    return json.loads((FIXTURES / name).read_bytes())


@pytest.mark.parametrize('route,request_file,response_file,status', [
    ('/v3/events', 'request.game.json', 'response.event.success.json', 200),
    ('/v3/events', 'request.game.json', 'response.error.json', 503),
    ('/v3/chat', 'request.chat.json', 'response.chat.success.json', 200),
])
def test_v3_shared_fixtures_http(client_factory, completion, route, request_file, response_file, status):
    expected = fixture(response_file)
    reply = {key: value for key, value in expected.items() if key not in ('version', 'requestId')}
    with client_factory(lambda _: httpx.Response(status, json=completion(reply))) as client:
        response = client.post(route, content=(FIXTURES / request_file).read_bytes(), headers={'content-type': 'application/json'})
        assert response.status_code == status
        assert response.json() == expected


def test_social_fixture_text_only(client_factory, completion):
    request = fixture('request.social.json')
    with client_factory(lambda _: httpx.Response(200, json=completion({'text': 'Привет!'}))) as client:
        response = client.post('/v3/events', json=request)
        assert response.status_code == 200
        assert response.json() == {'version': 3, 'requestId': request['requestId'], 'text': 'Привет!'}


@pytest.mark.parametrize('name,expected', [
    ('request.chat.json', '7c92911cdd2c4222a3cae0da584339d769ddf7a24fee3ed6d2fff996b5f3f436'),
    ('request.game.json', '89eb918ca1e74531f657d7ce3b3c48b4cfd15c0c9a9ad74cf3fd00e732f54edb'),
    ('request.social.json', 'cdb0cdecfca87aa41476f33249c75e5af80946bbada773204d6388362ccf1248'),
    ('response.chat.success.json', '45202cd07690a0693cbf0ee95e85236de2a3f2cd9c4bf971de3c1c984345aafb'),
    ('response.error.json', '769c71b89bcaedfc067296dbb6f8bcf92075405dfd2240b115f5ec905550a020'),
    ('response.event.success.json', '84b2ac018d31fa9c7d84c86f8ca1b0456a6f0a92d49bd839565ff1b59c66f8d8'),
])
def test_exact_v3_fixture_bytes(name, expected):
    import hashlib
    assert hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest() == expected


@pytest.mark.parametrize('request_name,route', [('request.game.json', '/v3/events'), ('request.chat.json', '/v3/chat')])
def test_v3_boundary_errors_and_exact_byte_cap(client_factory, completion, request_name, route):
    body = fixture(request_name)
    with client_factory(lambda _: pytest.fail('invalid input reached provider')) as client:
        for version in [1, 2, 4]:
            response = client.post(route, json={**body, 'version': version})
            assert response.status_code == 400
            assert response.json() == {'version': 3, 'requestId': body['requestId'], 'error': {'code': 'unsupported_version'}}
        for version in [True, 3.0, '3', None]:
            response = client.post(route, json={**body, 'version': version})
            assert response.status_code == 400
            assert response.json()['version'] == 3
            assert response.json()['error']['code'] == 'invalid_request'
        for content, status in [(b'{', 400), (b'x'*32769, 413)]:
            response = client.post(route, content=content, headers={'content-type': 'application/json'})
            assert response.status_code == status
            assert response.json()['version'] == 3
            assert response.json()['requestId'] is None
    raw = json.dumps(body).encode()
    raw += b' ' * (32768-len(raw))
    with client_factory(lambda _: httpx.Response(200, json=completion())) as client:
        assert client.post(route, content=raw, headers={'content-type': 'application/json'}).status_code == 200
        assert client.post(route, content=raw+b' ', headers={'content-type': 'application/json'}).status_code == 413


def test_event_prompt_output_cap_and_authoritative_outcome(client_factory, completion):
    body = fixture('request.game.json')
    body['event']['outcome'] = 'missed'
    calls = []
    def upstream(request):
        calls.append(request)
        data = json.loads(request.content)
        assert data['max_completion_tokens'] == 1024
        assert 0 < request.extensions['timeout']['read'] <= 2.5
        messages = data['messages']
        assert len(messages) == 4  # instructions and three data blocks, no fabricated dialogue
        assert 'not spoken by the user' in messages[0]['content']
        assert 'outcome is authoritative factual context' in messages[0]['content']
        assert 'Never guilt the user' in messages[0]['content']
        assert 'screen observations' in messages[0]['content']
        assert '"outcome": "caught"' in messages[2]['content']  # older recalled episode
        assert '"outcome": "missed"' in messages[3]['content']  # current authoritative event
        assert body['requestId'] not in request.content.decode()
        return httpx.Response(200, json=completion({'text': 'На этот раз промахнулась.'}))
    with client_factory(upstream) as client:
        assert client.post('/v3/events', json=body).status_code == 200
    assert len(calls) == 1


def test_chat_bridge_preserves_ai_provenance_and_only_current_user_evidence(client_factory, completion):
    body = fixture('request.chat.json')
    calls = []
    def upstream(request):
        calls.append(request)
        data = json.loads(request.content)
        assert data['max_completion_tokens'] == 4096
        assert 2.5 < request.extensions['timeout']['read'] <= 10
        messages = data['messages']
        assert messages[-1] == body['messages'][-1]
        previous = messages[-2]
        assert previous['content'].startswith('Previous published AI initiative (not user speech or proof of attention):')
        assert body['previousInitiative']['text'] in previous['content']
        assert 'never evidence for a memory candidate' in messages[0]['content']
        return httpx.Response(200, json=completion({'text': 'Хорошо.', 'memoryCandidates': [
            {'key': 'user.favorite_topic', 'value': 'музыка', 'evidenceQuote': body['previousInitiative']['text']},
            {'key': 'user.reply_style', 'value': 'brief', 'evidenceQuote': body['messages'][-1]['content']},
        ]}))
    with client_factory(upstream) as client:
        response = client.post('/v3/chat', json=body)
        assert response.status_code == 200
        # Structural/source validation only; desktop recognizer still owns acceptance.
        assert [candidate['key'] for candidate in response.json()['memoryCandidates']] == ['user.reply_style']
    assert len(calls) == 1


def test_event_and_initiative_content_never_persist_or_log(app_factory, completion, caplog):
    from fastapi.testclient import TestClient
    marker = 'SYNTHETIC_V3_PRIVATE_TEXT_MARKER'
    body = fixture('request.chat.json')
    body['previousInitiative']['text'] = marker
    app = app_factory(lambda _: httpx.Response(200, json=completion({'text': marker})))
    with TestClient(app) as client:
        assert client.post('/v3/chat', json=body).status_code == 200
        path = app.state.chat_service.ledger.path
    for candidate in path.parent.glob(path.name+'*'):
        content = candidate.read_bytes()
        assert marker.encode() not in content
        assert b'social_bid_started' not in content
    assert marker not in caplog.text


def test_v3_openapi_keeps_old_shapes(client_factory):
    with client_factory(lambda _: pytest.fail('schema lookup reached provider')) as client:
        spec = client.get('/openapi.json').json()
        for route in ['/v3/events', '/v3/chat']:
            assert set(spec['paths'][route]['post']['responses']) == {'200', '400', '409', '413', '429', '502', '503', '504'}
        schemas = spec['components']['schemas']
        assert set(schemas['EventResponse']['properties']) == {'version', 'requestId', 'text'}
        assert 'messages' not in schemas['EventRequest']['properties']
        assert 'previousInitiative' in schemas['EventAwareChatRequest']['properties']
        assert 'previousInitiative' not in schemas['MemoryRequest']['properties']
        assert 'memory' not in schemas['ChatRequest']['properties']
