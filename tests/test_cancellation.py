import asyncio
import hashlib
import json
import sqlite3

import httpx
import pytest

from wisp_backend.api.boundary import ChatBoundary
from wisp_backend.contracts import ProviderResult, RESERVATION, Usage
from wisp_backend.schemas import ChatRequest, ModelReply


def test_slow_body_never_admitted(monkeypatch):
    monkeypatch.setattr('wisp_backend.api.boundary.BODY_TIMEOUT', .01)
    async def run():
        sent = []
        async def receive():
            await asyncio.Future()
        async def send(value):
            sent.append(value)
        async def downstream(*args):
            pytest.fail('slow input reached downstream')
        await ChatBoundary(downstream)({'type':'http','path':'/v1/chat','method':'POST',
            'headers':[(b'content-type',b'application/json')]}, receive, send)
        assert sent[0]['status'] == 400
        assert json.loads(sent[1]['body'])['error']['code'] == 'invalid_request'
    asyncio.run(run())


@pytest.mark.parametrize('shutdown', [False, True])
def test_disconnect_or_shutdown_cancels_provider_and_releases_slot(app_factory, body, shutdown):
    async def run():
        entered = asyncio.Event()
        cancelled = asyncio.Event()
        async def upstream(request):
            entered.set()
            try:
                await asyncio.Future()
            finally:
                cancelled.set()
        app = app_factory(upstream)
        sent = []
        async with app.router.lifespan_context(app):
            service = app.state.chat_service
            read = False
            async def receive():
                nonlocal read
                if not read:
                    read = True
                    return {'type':'http.request','body':json.dumps(body).encode(),'more_body':False}
                await entered.wait()
                if shutdown:
                    await asyncio.Future()
                return {'type':'http.disconnect'}
            async def send(value):
                sent.append(value)
            scope = {'type':'http','asgi':{'version':'3.0'},'path':'/v1/chat','method':'POST',
                'headers':[(b'content-type',b'application/json')], 'query_string':b'',
                'scheme':'http','server':('test',80),'client':('127.0.0.1',123),'http_version':'1.1'}
            task = asyncio.create_task(app(scope, receive, send))
            await entered.wait()
            if shutdown:
                await service.close()
            await asyncio.wait_for(task, 1)
            await asyncio.wait_for(cancelled.wait(), 1)
            with sqlite3.connect(service.ledger.path) as db:
                assert db.execute('SELECT reserved,uncertain FROM days').fetchone() == (0, RESERVATION)
                assert db.execute("SELECT count(*) FROM entries WHERE state='flight'").fetchone()[0] == 0
            assert not sent
    asyncio.run(run())


def test_late_result_refines_usage_but_never_overwrites_timeout(app_factory, body):
    async def run():
        release = asyncio.Event()
        class LateProvider:
            async def complete(self, messages, settings, timeout):
                try:
                    await asyncio.Future()
                except asyncio.CancelledError:
                    await release.wait()
                    return ProviderResult(ModelReply(text='late'), Usage(2,3,5))
        app = app_factory(lambda _: pytest.fail('real upstream'))
        async with app.router.lifespan_context(app):
            service = app.state.chat_service
            service.providers['groq'] = LateProvider()
            service.deadline = .01
            request = ChatRequest.model_validate(body)
            digest = hashlib.sha256(json.dumps(body).encode()).hexdigest()
            outcome = await service.complete(request, digest, asyncio.get_running_loop().time())
            assert outcome.status == 504
            release.set()
            while service.background:
                await asyncio.sleep(0)
            repeat = await service.complete(request, digest, asyncio.get_running_loop().time())
            assert repeat.status == 409
            with sqlite3.connect(service.ledger.path) as db:
                assert db.execute('SELECT requests,reserved,confirmed,uncertain FROM days').fetchone() == (1,0,5,0)
    asyncio.run(run())


def test_admission_timeout_has_no_dispatch_and_settles_late_reservation(app_factory, body):
    async def run():
        release = asyncio.Event()
        app = app_factory(lambda _: pytest.fail('expired admission reached upstream'))
        async with app.router.lifespan_context(app):
            service = app.state.chat_service
            original = service.ledger.admit
            async def slow(*args):
                await release.wait()
                return await original(*args)
            service.ledger.admit = slow
            service.deadline = .01
            outcome = await service.complete(ChatRequest.model_validate(body), 'digest', asyncio.get_running_loop().time())
            assert outcome.status == 504
            release.set()
            while service.background:
                await asyncio.sleep(0)
            with sqlite3.connect(service.ledger.path) as db:
                assert db.execute('SELECT reserved,uncertain FROM days').fetchone() == (0,RESERVATION)
    asyncio.run(run())


def test_slow_terminal_disk_write_cannot_exceed_deadline_or_cache_success(app_factory, body):
    async def run():
        release = asyncio.Event()
        app = app_factory(lambda _: httpx.Response(200, json={'choices':[{'message':{'content':'{"text":"ok"}'},'finish_reason':'stop'}],
            'usage':{'prompt_tokens':1,'completion_tokens':1,'total_tokens':2}}))
        async with app.router.lifespan_context(app):
            service = app.state.chat_service
            original = service.ledger.settle
            async def slow(*args):
                await release.wait()
                return await original(*args)
            service.ledger.settle = slow
            service.deadline = .02
            request = ChatRequest.model_validate(body)
            outcome = await asyncio.wait_for(service.complete(request, 'digest', asyncio.get_running_loop().time()), .1)
            assert outcome.status == 504
            release.set()
            while service.background:
                await asyncio.sleep(0)
            repeat = await service.complete(request, 'digest', asyncio.get_running_loop().time())
            assert repeat.status == 409
    asyncio.run(run())


def test_disconnect_during_settlement_never_caches_success(app_factory, body):
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        app = app_factory(lambda _: httpx.Response(200, json={'choices':[{'message':{'content':'{"text":"ok"}'},'finish_reason':'stop'}],
            'usage':{'prompt_tokens':1,'completion_tokens':1,'total_tokens':2}}))
        async with app.router.lifespan_context(app):
            service = app.state.chat_service
            original = service.ledger.settle
            async def slow(*args):
                entered.set()
                await release.wait()
                return await original(*args)
            service.ledger.settle = slow
            request = ChatRequest.model_validate(body)
            task = asyncio.create_task(service.complete(request, 'digest', asyncio.get_running_loop().time()))
            await entered.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            release.set()
            while service.background:
                await asyncio.sleep(0)
            assert task not in service.requests
            repeat = await service.complete(request, 'digest', asyncio.get_running_loop().time())
            assert repeat.status == 409
    asyncio.run(run())
