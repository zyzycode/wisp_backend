import asyncio
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

import httpx
import pytest

from wisp_backend.config import LedgerSettings
from wisp_backend.contracts import RESERVATION, ProviderResult, Usage
from wisp_backend.events_schemas import EventRequest, EventModelReply

FIXTURES = Path(__file__).parent/'fixtures/desktop-backend-v3'


def fixture(name):
    return json.loads((FIXTURES/name).read_bytes())


def test_all_endpoints_share_budget_and_id_namespace(app_factory, body, completion):
    async def run():
        calls = []
        def upstream(request):
            calls.append(request)
            return httpx.Response(200, json=completion({'text': 'ok'}, usage={'prompt_tokens': 1, 'completion_tokens': 2, 'total_tokens': 3}))
        app = app_factory(upstream)
        game = fixture('request.game.json')
        request_id = game['requestId']
        candidates = [('/v1/chat', {**body, 'requestId': request_id}),
            ('/v2/chat', {**body, 'version': 2, 'requestId': request_id, 'memory': game['memory']}),
            ('/v3/chat', {**fixture('request.chat.json'), 'requestId': request_id})]
        async with app.router.lifespan_context(app):
            ledger = app.state.chat_service.ledger
            ledger.policy = LedgerSettings(daily_requests=1)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
                first = await client.post('/v3/events', json=game)
                assert first.status_code == 200
                for route, candidate in candidates:
                    conflict = await client.post(route, json=candidate)
                    assert conflict.status_code == 409
                    assert conflict.json()['error']['code'] == 'request_conflict'
                    assert conflict.json()['version'] == candidate['version']
                    denied = await client.post(route, json={**candidate, 'requestId': str(uuid4())})
                    assert denied.status_code == 429
                    assert denied.json()['error']['code'] == 'budget_exhausted'
                replay = await client.post('/v3/events', json=game)
                assert replay.content == first.content
                changed = await client.post('/v3/events', json={**fixture('request.social.json'), 'requestId': request_id})
                assert changed.status_code == 409
            with sqlite3.connect(ledger.path) as db:
                assert db.execute('SELECT requests,confirmed FROM days').fetchone() == (1, 3)
        assert len(calls) == 1
    asyncio.run(run())


@pytest.mark.parametrize('shutdown', [False, True])
def test_event_disconnect_shutdown_releases_capacity(app_factory, shutdown):
    async def run():
        entered, cancelled = asyncio.Event(), asyncio.Event()
        async def upstream(request):
            entered.set()
            try:
                await asyncio.Future()
            finally:
                cancelled.set()
        app = app_factory(upstream)
        async with app.router.lifespan_context(app):
            service = app.state.chat_service
            delivered = False
            async def receive():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {'type': 'http.request', 'body': (FIXTURES/'request.game.json').read_bytes(), 'more_body': False}
                await entered.wait()
                if shutdown:
                    await asyncio.Future()
                return {'type': 'http.disconnect'}
            sent = []
            async def send(value):
                sent.append(value)
            scope = {'type': 'http', 'asgi': {'version': '3.0'}, 'path': '/v3/events', 'method': 'POST',
                'headers': [(b'content-type', b'application/json')], 'query_string': b'', 'scheme': 'http',
                'server': ('test', 80), 'client': ('127.0.0.1', 123), 'http_version': '1.1'}
            task = asyncio.create_task(app(scope, receive, send))
            await entered.wait()
            if shutdown:
                await service.close()
            await asyncio.wait_for(task, 1)
            await asyncio.wait_for(cancelled.wait(), 1)
            assert not sent
            with sqlite3.connect(service.ledger.path) as db:
                assert db.execute('SELECT requests,reserved,uncertain FROM days').fetchone() == (1, 0, RESERVATION)
                assert db.execute("SELECT count(*) FROM entries WHERE state='flight'").fetchone()[0] == 0
    asyncio.run(run())


def test_event_short_deadline_with_late_usage_never_replays_success(app_factory, monkeypatch):
    monkeypatch.setattr('wisp_backend.service.EVENT_DEADLINE', .01)
    async def run():
        release = asyncio.Event()
        class LateProvider:
            async def complete(self, messages, settings, timeout, reply_context):
                assert timeout <= .01 and reply_context.mode == 'event'
                try:
                    await asyncio.Future()
                except asyncio.CancelledError:
                    await release.wait()
                    return ProviderResult(EventModelReply(text='late'), Usage(2, 3, 5))
        app = app_factory(lambda _: pytest.fail('real upstream'))
        async with app.router.lifespan_context(app):
            service = app.state.chat_service
            service.providers['groq'] = LateProvider()
            request = EventRequest.model_validate(fixture('request.game.json'))
            first = await service.complete(request, 'event-digest', asyncio.get_running_loop().time())
            assert first.status == 504 and json.loads(first.body)['version'] == 3
            release.set()
            while service.background:
                await asyncio.sleep(0)
            repeat = await service.complete(request, 'event-digest', asyncio.get_running_loop().time())
            assert repeat.status == 409
            with sqlite3.connect(service.ledger.path) as db:
                assert db.execute('SELECT requests,reserved,confirmed,uncertain FROM days').fetchone() == (1, 0, 5, 0)
    asyncio.run(run())


def test_event_body_deadline_is_shorter_than_chat(monkeypatch):
    from wisp_backend.api.boundary import ChatBoundary, EVENT_BODY_TIMEOUT, BODY_TIMEOUT
    assert EVENT_BODY_TIMEOUT == .5 and BODY_TIMEOUT == 2
    monkeypatch.setattr('wisp_backend.api.boundary.EVENT_BODY_TIMEOUT', .01)
    monkeypatch.setattr('wisp_backend.api.boundary.BODY_TIMEOUT', .1)
    async def run():
        async def request(path, raw):
            sent = []
            delivered = False
            async def receive():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    await asyncio.sleep(.02)
                    return {'type': 'http.request', 'body': raw, 'more_body': False}
                await asyncio.Future()
            async def send(value):
                sent.append(value)
            async def downstream(scope, replay, send):
                await replay()
                await send({'type': 'http.response.start', 'status': 200, 'headers': []})
                await send({'type': 'http.response.body', 'body': b'{}'})
            await ChatBoundary(downstream)({'type': 'http', 'path': path, 'method': 'POST',
                'headers': [(b'content-type', b'application/json')]}, receive, send)
            return sent
        event = await request('/v3/events', (FIXTURES/'request.game.json').read_bytes())
        assert event[0]['status'] == 400
        assert json.loads(event[1]['body']) == {'version': 3, 'requestId': None, 'error': {'code': 'invalid_request'}}
        chat = await request('/v3/chat', (FIXTURES/'request.chat.json').read_bytes())
        assert chat[0]['status'] == 200
    asyncio.run(run())


def test_cached_commit_cannot_replay_success_after_event_deadline(app_factory, completion, monkeypatch):
    import time
    monkeypatch.setattr('wisp_backend.service.EVENT_DEADLINE', .02)
    async def run():
        app = app_factory(lambda _: httpx.Response(200, json=completion({'text': 'ok'},
            usage={'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2})))
        async with app.router.lifespan_context(app):
            service = app.state.chat_service
            original = service.ledger._terminal
            def delayed_return(*args):
                original(*args)  # successful commit/cache just before deadline
                time.sleep(.04)  # caller receives completion after its event deadline
            service.ledger._terminal = delayed_return
            request = EventRequest.model_validate(fixture('request.game.json'))
            first = await service.complete(request, 'digest', asyncio.get_running_loop().time())
            assert first.status == 504
            while service.background:
                await asyncio.sleep(0)
            repeat = await service.complete(request, 'digest', asyncio.get_running_loop().time())
            assert repeat.status == 409
    asyncio.run(run())
