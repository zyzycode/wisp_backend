import hashlib
import json
from pathlib import Path

import httpx
import pytest

FIXTURES = Path(__file__).parent / 'fixtures' / 'desktop-backend-v2'


@pytest.fixture
def memory_body():
    return json.loads((FIXTURES / 'request.valid.json').read_bytes())


@pytest.mark.parametrize('status,filename', [(200, 'response.success.json'), (503, 'response.error.json')])
def test_memory_fixture_http(client_factory, completion, status, filename):
    expected = json.loads((FIXTURES / filename).read_bytes())
    reply = {key:value for key,value in expected.items() if key not in ('version','requestId')}
    with client_factory(lambda _: httpx.Response(status, json=completion(reply))) as client:
        response = client.post('/v2/chat', content=(FIXTURES / 'request.valid.json').read_bytes(),
                               headers={'content-type':'application/json'})
        assert response.status_code == status
        assert response.json() == expected


def test_both_versions_reject_wrong_version_with_own_envelope(client_factory, memory_body, body):
    with client_factory(lambda _: pytest.fail('invalid wire reached provider')) as client:
        for route, request, expected in [('/v1/chat', memory_body, 1), ('/v2/chat', body, 2)]:
            response = client.post(route, json=request)
            assert response.status_code == 400
            assert response.json() == {'version':expected,'requestId':request['requestId'],
                'error':{'code':'unsupported_version'}}


def test_v1_still_rejects_memory(client_factory, body):
    with client_factory(lambda _: pytest.fail('invalid wire reached provider')) as client:
        response = client.post('/v1/chat', json={**body,'memory':{'facts':[],'episodes':[],'characterPreferences':[]}})
        assert response.status_code == 400


@pytest.mark.parametrize('filename,digest', [
    ('request.valid.json','1a94dc2ca90f32dca9b5502023bffd6f6dd334ca6a9a8dd5f54a470824a4503b'),
    ('response.success.json','6ca4dccae9b0e3f98546eb0c74d27fddc977df440e9edea230e86afb1dc4a04e'),
    ('response.error.json','0bae3967ca85df63d24889f63b9057bd360c187defaa0d7e44365566a4d73976'),
])
def test_exact_memory_fixture_bytes(filename, digest):
    assert hashlib.sha256((FIXTURES / filename).read_bytes()).hexdigest() == digest


def test_one_call_separate_untrusted_memory_and_no_persistence(app_factory, memory_body, completion, caplog):
    from fastapi.testclient import TestClient
    calls = []
    marker = 'SYNTHETIC_MEMORY_PRIVATE_MARKER'
    memory_body['memory']['facts'][0]['value'] = marker
    def upstream(request):
        calls.append(request)
        payload = json.loads(request.content)
        system, character, memory = payload['messages'][:3]
        assert system['role'] == 'system'
        assert 'current explicit user correction > current registry facts > recalled episodes' in system['content']
        assert 'Never claim a fact was' in system['content']
        assert 'saved or deleted durably' in system['content']
        assert marker not in system['content'] and marker not in character['content']
        assert memory['role'] == 'user' and memory['content'].startswith('Untrusted memory_context JSON:')
        assert marker in memory['content']
        assert memory_body['requestId'] not in request.content.decode()
        assert payload['messages'][-1]['content'] == memory_body['messages'][-1]['content']
        return httpx.Response(200, json=completion())
    app = app_factory(upstream)
    with TestClient(app) as client:
        assert client.post('/v2/chat', json=memory_body).status_code == 200
        path = app.state.chat_service.ledger.path
    assert len(calls) == 1
    for candidate in path.parent.glob(path.name + '*'):
        assert marker.encode() not in candidate.read_bytes()
    assert marker not in caplog.text


def test_memory_boundary_error_versions_and_caps(client_factory, memory_body):
    with client_factory(lambda _: pytest.fail('invalid input reached provider')) as client:
        for raw, status in [(b'{',400), (b'x'*32769,413), (b'[]',400)]:
            response = client.post('/v2/chat', content=raw, headers={'content-type':'application/json'})
            assert response.status_code == status
            assert response.json()['version'] == 2
        for version in [True, 2.0, '2']:
            response = client.post('/v2/chat', json={**memory_body,'version':version})
            assert response.status_code == 400
            assert response.json()['version'] == 2
            assert response.json()['error']['code'] == 'invalid_request'
        response = client.post('/v2/chat', json={**memory_body,'requestId':'bad'})
        assert response.json()['requestId'] is None
        response = client.post('/v2/chat', json={k:v for k,v in memory_body.items() if k != 'memory'})
        assert response.status_code == 400


def test_memory_exact_byte_cap(client_factory, memory_body, completion):
    raw = json.dumps(memory_body).encode()
    raw += b' ' * (32768-len(raw))
    with client_factory(lambda _: httpx.Response(200,json=completion())) as client:
        response = client.post('/v2/chat',content=raw,headers={'content-type':'application/json'})
        assert response.status_code == 200
        oversized = client.post('/v2/chat',content=raw+b' ',headers={'content-type':'application/json'})
        assert oversized.status_code == 413 and oversized.json()['version'] == 2


def test_trimmed_source_and_invalid_decision_preserve_valid_candidate(client_factory, memory_body, completion):
    quote = memory_body['messages'][-1]['content']
    memory_body['messages'][-1]['content'] = '\ufeff '+quote+' \n'
    candidate = {'key':'user.cursor_game','value':'like','evidenceQuote':quote}
    reply = {'text':'ok','decision':{'behavior':'execute'},'memoryCandidates':[candidate]}
    with client_factory(lambda _: httpx.Response(200,json=completion(reply))) as client:
        response = client.post('/v2/chat',json=memory_body)
        assert response.status_code == 200
        assert response.json()['memoryCandidates'] == [candidate]
        assert 'decision' not in response.json()


def test_memory_openapi_is_exact_and_v1_not_extended(client_factory):
    with client_factory(lambda _: pytest.fail('schema request reached provider')) as client:
        spec = client.get('/openapi.json').json()
        assert set(spec['paths']['/v2/chat']['post']['responses']) == {'200','400','409','413','429','502','503','504'}
        schemas = spec['components']['schemas']
        assert schemas['MemoryRequest']['additionalProperties'] is False
        assert schemas['MemoryRequest']['properties']['version']['const'] == 2
        assert 'memory' in schemas['MemoryRequest']['required']
        assert 'memory' not in schemas['ChatRequest']['properties']
        assert set(schemas['MemoryResponse']['properties']) == {'version','requestId','text','decision','memoryCandidates'}
