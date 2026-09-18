import hashlib
import json
from pathlib import Path

import httpx
import pytest

FIXTURES = Path(__file__).parent / 'fixtures' / 'desktop-backend-v1'
HASHES = {
    'request.valid.json': '64f6c769e91146c0311b0a15939760cfecba14eb39ce8df2e57a4f1ffff354e5',
    'response.success.json': 'f1c50137b48fed57b34459eb9932cbc016bc80e94b9677bac507c407206962ae',
    'response.error.json': 'f0db527096694ccacd6b0683361dcd957e2cd598e040617cad3c0a9cc86a093e',
}


@pytest.mark.parametrize('name,expected', HASHES.items())
def test_exact_desktop_fixture_bytes(name, expected):
    assert hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest() == expected


@pytest.mark.parametrize('status,name', [(200, 'response.success.json'), (503, 'response.error.json')])
def test_shared_fixture_through_real_route(client_factory, completion, status, name):
    expected = json.loads((FIXTURES / name).read_bytes())
    reply = {key: value for key, value in expected.items() if key not in ('version', 'requestId')}
    with client_factory(lambda _: httpx.Response(status, json=completion(reply))) as client:
        response = client.post('/v1/chat', content=(FIXTURES / 'request.valid.json').read_bytes(),
                               headers={'content-type': 'application/json'})
        assert response.status_code == status
        assert response.json() == expected
