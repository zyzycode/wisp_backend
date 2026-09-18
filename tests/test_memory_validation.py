from copy import deepcopy
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from wisp_backend.memory_schemas import MemoryRequest, MemoryModelReply

FIXTURE = Path(__file__).parent / 'fixtures/desktop-backend-v2/request.valid.json'


@pytest.fixture
def memory_body():
    return json.loads(FIXTURE.read_bytes())


@pytest.mark.parametrize('key,limit', [('user.display_name',80),('user.preferred_address',80),('user.favorite_topic',120)])
def test_memory_fact_utf16_limits(memory_body, key, limit):
    for value in ['😀'*(limit//2), 'a'*limit]:
        memory_body['memory']['facts'] = [{'key':key,'value':value}]
        MemoryRequest.model_validate(memory_body)
    for value in ['😀'*(limit//2+1),' '+'a'*limit,'',' ','bad\r','bad\x00','\ud800']:
        memory_body['memory']['facts'] = [{'key':key,'value':value}]
        with pytest.raises(ValidationError):
            MemoryRequest.model_validate(memory_body)


@pytest.mark.parametrize('key,accepted,rejected', [
    ('user.reply_style',['brief','detailed'],['brief ','long',1,None]),
    ('user.cursor_game',['like','dislike'],['like ','love',True,None]),
])
def test_registry_enums(memory_body, key, accepted, rejected):
    for value in accepted:
        memory_body['memory']['facts'] = [{'key':key,'value':value}]
        MemoryRequest.model_validate(memory_body)
    for value in rejected:
        memory_body['memory']['facts'] = [{'key':key,'value':value}]
        with pytest.raises(ValidationError):
            MemoryRequest.model_validate(memory_body)


@pytest.mark.parametrize('timestamp', ['2024-02-29T23:59:59.999Z','0000-02-29T00:00:00.000Z','9999-12-31T00:00:00.000Z'])
def test_calendar_boundaries(memory_body, timestamp):
    memory_body['memory']['episodes'][0]['occurredAt'] = timestamp
    MemoryRequest.model_validate(memory_body)


@pytest.mark.parametrize('timestamp', ['2025-02-29T00:00:00.000Z','2024-02-30T00:00:00.000Z',
    '2024-13-01T00:00:00.000Z','2024-01-00T00:00:00.000Z','2024-01-01T24:00:00.000Z',
    '2024-01-01T00:60:00.000Z','2024-01-01T00:00:60.000Z','2024-01-01T00:00:00Z',
    '2024-01-01T00:00:00.000+00:00','2024-01-01t00:00:00.000z'])
def test_invalid_calendar(memory_body, timestamp):
    memory_body['memory']['episodes'][0]['occurredAt'] = timestamp
    with pytest.raises(ValidationError):
        MemoryRequest.model_validate(memory_body)


def test_numeric_boundaries_and_boolean_rejection(memory_body):
    fields = [(memory_body['memory']['episodes'][0], 'executedMs', 0, 60000),
        (memory_body['memory']['characterPreferences'][0], 'value', -100, 100),
        (memory_body['memory']['characterPreferences'][0], 'confidence', .5, 1)]
    for target,key,lower,upper in fields:
        original = target[key]
        for value in [lower, upper]:
            target[key] = value
            MemoryRequest.model_validate(memory_body)
        for value in [lower-.01, upper+.01, True, str(lower), None, float('nan'), float('inf')]:
            target[key] = value
            with pytest.raises(ValidationError):
                MemoryRequest.model_validate(memory_body)
        target[key] = original


def test_exact_shapes_and_cardinality(memory_body):
    original = memory_body['memory']
    variants = [None, {}, {**original,'extra':1}, {**original,'facts':original['facts']*3},
        {**original,'facts':original['facts']*2}, {**original,'episodes':original['episodes']*2},
        {**original,'characterPreferences':original['characterPreferences']*2},
        {**original,'facts':[{'key':'user.password','value':'secret'}]},
        {**original,'facts':[{'key':'user.display_name','value':'A','sourceId':'private'}]},
        {**original,'episodes':[{**original['episodes'][0],'kind':'invented'}]},
        {**original,'episodes':[{**original['episodes'][0],'coordinates':{'x':1,'y':2}}]}]
    for projection in variants:
        with pytest.raises(ValidationError):
            MemoryRequest.model_validate({**memory_body,'memory':projection})
    MemoryRequest.model_validate({**memory_body,'memory':{'facts':[],'episodes':[],'characterPreferences':[]}})


def test_dialogue_episode_text_and_caps(memory_body):
    episode = {'kind':'dialogue','userText':'😀'*120,'assistantText':'😀'*200,'occurredAt':'2026-09-18T08:30:00.000Z'}
    memory_body['memory']['episodes'] = [episode,deepcopy(episode)]
    MemoryRequest.model_validate(memory_body)
    memory_body['memory']['episodes'].append(deepcopy(episode))
    with pytest.raises(ValidationError):
        MemoryRequest.model_validate(memory_body)
    for key in ['userText','assistantText']:
        memory_body['memory']['episodes'] = [{**episode,key:episode[key]+'a'}]
        with pytest.raises(ValidationError):
            MemoryRequest.model_validate(memory_body)


@pytest.mark.parametrize('kind', ['wrong_quote','duplicate','unknown','wrong_value','extra','null','too_many','non_list'])
def test_candidate_degradation_keeps_text_decision_usage(client_factory, memory_body, completion, kind):
    quote = memory_body['messages'][-1]['content']
    valid = {'key':'user.cursor_game','value':'like','evidenceQuote':quote}
    candidates = [valid]
    expected = []
    if kind == 'wrong_quote':
        candidates = [{**valid,'evidenceQuote':quote+' '}]
    elif kind == 'duplicate':
        candidates = [valid, {**valid,'value':'dislike'}]
    elif kind == 'unknown':
        candidates = [{**valid,'key':'user.password'},valid]
        expected = [valid]
    elif kind == 'wrong_value':
        candidates = [{**valid,'value':'love'}]
    elif kind == 'extra':
        candidates = [{**valid,'stateDelta':{'friendship':50}}]
    elif kind == 'null':
        candidates = None
        expected = None
    elif kind == 'too_many':
        candidates = [valid]*4
        expected = None
    else:
        candidates = {}
        expected = None
    calls = []
    reply = {'text':'Works','decision':{'behavior':'respond','confidence':.5},'memoryCandidates':candidates}
    def upstream(request):
        calls.append(request)
        return httpx.Response(200,json=completion(reply, usage={'prompt_tokens':1,'completion_tokens':2,'total_tokens':3}))
    with client_factory(upstream) as client:
        response = client.post('/v2/chat',json=memory_body)
        assert response.status_code == 200
        payload = response.json()
        assert payload['text'] == 'Works' and payload['decision'] == reply['decision']
        if expected is None:
            assert 'memoryCandidates' not in payload
        else:
            assert payload['memoryCandidates'] == expected
        replay = client.post('/v2/chat',json=memory_body)
        assert replay.json() == payload
    assert len(calls) == 1


def test_duplicate_invalid_element_also_removes_valid_same_key():
    quote = 'Меня зовут Аня.'
    reply = MemoryModelReply.model_validate({'text':'ok','memoryCandidates':[
        {'key':'user.display_name','value':'Аня','evidenceQuote':quote},
        {'key':'user.display_name','value':None,'evidenceQuote':quote},
        {'key':'user.reply_style','value':'brief','evidenceQuote':quote}]}, context={'evidence_quote':quote})
    assert [item.key for item in reply.memoryCandidates] == ['user.reply_style']


def test_unknown_root_and_invalid_text_remain_fatal(client_factory, memory_body, completion):
    for reply in [{'text':'ok','numericState':{'friendship':900}}, {'text':'','memoryCandidates':[]},
                  {'text':'😀'*1001}, {'text':'ok','requestId':'model-owned'}]:
        with client_factory(lambda _, reply=reply: httpx.Response(200,json=completion(reply))) as client:
            response = client.post('/v2/chat',json=memory_body)
            assert response.status_code == 502
            assert response.json()['version'] == 2
