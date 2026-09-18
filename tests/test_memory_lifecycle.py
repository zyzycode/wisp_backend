import asyncio
import json
from pathlib import Path
import sqlite3

import httpx
import pytest

from wisp_backend.contracts import RESERVATION, ProviderResult, Usage
from wisp_backend.memory_schemas import MemoryModelReply, MemoryRequest

FIXTURE = Path(__file__).parent/'fixtures/desktop-backend-v2/request.valid.json'


@pytest.mark.parametrize('shutdown',[False,True])
def test_memory_disconnect_shutdown_preserves_usage(app_factory,shutdown):
    async def run():
        entered,cancelled=asyncio.Event(),asyncio.Event()
        async def upstream(request):
            entered.set()
            try:
                await asyncio.Future()
            finally:
                cancelled.set()
        app=app_factory(upstream)
        async with app.router.lifespan_context(app):
            service=app.state.chat_service
            delivered=False
            async def receive():
                nonlocal delivered
                if not delivered:
                    delivered=True
                    return {'type':'http.request','body':FIXTURE.read_bytes(),'more_body':False}
                await entered.wait()
                if shutdown:
                    await asyncio.Future()
                return {'type':'http.disconnect'}
            sent=[]
            async def send(value):
                sent.append(value)
            scope={'type':'http','asgi':{'version':'3.0'},'path':'/v2/chat','method':'POST',
                'headers':[(b'content-type',b'application/json')],'query_string':b'','scheme':'http',
                'server':('test',80),'client':('127.0.0.1',123),'http_version':'1.1'}
            task=asyncio.create_task(app(scope,receive,send))
            await entered.wait()
            if shutdown:
                await service.close()
            await asyncio.wait_for(task,1)
            await asyncio.wait_for(cancelled.wait(),1)
            assert not sent
            with sqlite3.connect(service.ledger.path) as db:
                assert db.execute('SELECT requests,reserved,uncertain FROM days').fetchone()==(1,0,RESERVATION)
    asyncio.run(run())


def test_memory_timeout_late_result_never_replays_success(app_factory):
    async def run():
        release=asyncio.Event()
        class LateProvider:
            async def complete(self,messages,settings,timeout,reply_context):
                try:
                    await asyncio.Future()
                except asyncio.CancelledError:
                    await release.wait()
                    return ProviderResult(MemoryModelReply(text='late'),Usage(2,3,5))
        app=app_factory(lambda _:pytest.fail('real provider'))
        async with app.router.lifespan_context(app):
            service=app.state.chat_service
            service.providers['groq']=LateProvider()
            service.deadline=.01
            request=MemoryRequest.model_validate(json.loads(FIXTURE.read_bytes()))
            first=await service.complete(request,'v2-digest',asyncio.get_running_loop().time())
            assert first.status==504 and json.loads(first.body)['version']==2
            release.set()
            while service.background:
                await asyncio.sleep(0)
            repeat=await service.complete(request,'v2-digest',asyncio.get_running_loop().time())
            assert repeat.status==409 and json.loads(repeat.body)['version']==2
            with sqlite3.connect(service.ledger.path) as db:
                assert db.execute('SELECT requests,confirmed,uncertain,reserved FROM days').fetchone()==(1,5,0,0)
    asyncio.run(run())


def test_memory_body_deadline_uses_v2_error(monkeypatch):
    from wisp_backend.api.boundary import ChatBoundary
    monkeypatch.setattr('wisp_backend.api.boundary.BODY_TIMEOUT',.01)
    async def run():
        sent=[]
        async def receive():
            await asyncio.Future()
        async def send(value):
            sent.append(value)
        async def downstream(*args):
            pytest.fail('slow body reached route')
        await ChatBoundary(downstream)({'type':'http','path':'/v2/chat','method':'POST',
            'headers':[(b'content-type',b'application/json')]},receive,send)
        assert sent[0]['status']==400
        assert json.loads(sent[1]['body'])=={'version':2,'requestId':None,'error':{'code':'invalid_request'}}
    asyncio.run(run())
