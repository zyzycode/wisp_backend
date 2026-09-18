import asyncio
import json
import sqlite3
from uuid import uuid4

import httpx
import pytest

from wisp_backend.contracts import RESERVATION


@pytest.mark.parametrize('usage,confirmed', [
    ({'prompt_tokens': 5, 'completion_tokens': 2, 'total_tokens': 7}, True),
    (None, False), ({'prompt_tokens': True, 'completion_tokens': 2, 'total_tokens': 3}, False),
    ({'prompt_tokens': 5, 'completion_tokens': 2, 'total_tokens': 8}, False),
    ({'prompt_tokens': -1, 'completion_tokens': 2, 'total_tokens': 1}, False),
    ({'prompt_tokens': 5.0, 'completion_tokens': 2, 'total_tokens': 7}, False),
])
def test_usage_accounted_even_for_invalid_model_output(app_factory, body, completion, usage, confirmed):
    from fastapi.testclient import TestClient
    app = app_factory(lambda _: httpx.Response(200, json=completion({'text': ''}, usage=usage)))
    with TestClient(app) as client:
        first = client.post('/v1/chat', json=body)
        assert first.status_code == 502
        repeat = client.post('/v1/chat', json=body)
        assert repeat.status_code == (502 if confirmed else 409)
        with sqlite3.connect(app.state.chat_service.ledger.path) as db:
            assert db.execute('SELECT requests,confirmed,uncertain FROM days').fetchone() == (1, 7 if confirmed else 0, 0 if confirmed else RESERVATION)


def test_duplicates_and_concurrent_limit_on_real_http_route(app_factory, body, completion):
    async def run():
        calls = 0
        entered = asyncio.Event()
        release = asyncio.Event()
        async def upstream(request):
            nonlocal calls
            calls += 1
            entered.set()
            await release.wait()
            return httpx.Response(200, json=completion(usage={'prompt_tokens': 5, 'completion_tokens': 2, 'total_tokens': 7}))
        app = app_factory(upstream)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
                first = asyncio.create_task(client.post('/v1/chat', json=body))
                await entered.wait()
                duplicate = await client.post('/v1/chat', json=body)
                assert duplicate.status_code == 409
                assert duplicate.json()['error']['code'] == 'request_in_progress'
                changed = await client.post('/v1/chat', content=json.dumps(body, indent=2), headers={'content-type':'application/json'})
                assert changed.json()['error']['code'] == 'request_conflict'
                second = asyncio.create_task(client.post('/v1/chat', json={**body, 'requestId':str(uuid4())}))
                while calls < 2:
                    await asyncio.sleep(0)
                denied = await client.post('/v1/chat', json={**body, 'requestId':str(uuid4())})
                assert denied.status_code == 429
                assert denied.json()['error'] == {'code':'rate_limited', 'retryAfterMs':1000}
                release.set()
                assert (await first).status_code == (await second).status_code == 200
                replay = await client.post('/v1/chat', json=body)
                assert replay.status_code == 200
                assert calls == 2
    asyncio.run(run())


def test_payloads_never_persist_or_log(app_factory, body, completion, caplog):
    from fastapi.testclient import TestClient
    marker = 'SYNTHETIC_CONTENT_NOT_FOR_STORAGE'
    body['messages'][0]['content'] = marker
    app = app_factory(lambda _: httpx.Response(200, json=completion({'text': marker}, usage={'prompt_tokens':1,'completion_tokens':1,'total_tokens':2})))
    with TestClient(app) as client:
        assert client.post('/v1/chat', json=body).status_code == 200
        path = app.state.chat_service.ledger.path
    for candidate in path.parent.glob(path.name + '*'):
        assert marker.encode() not in candidate.read_bytes()
    assert marker not in caplog.text
