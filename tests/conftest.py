import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from wisp_backend.application import create_app
from wisp_backend.config import Settings


@pytest.fixture
def body():
    return json.loads((Path(__file__).parent / "fixtures/request.local.json").read_text(encoding="utf-8"))


@pytest.fixture
def app_factory():
    def factory(handler):
        return create_app(httpx.MockTransport(handler), settings=Settings(api_key=SecretStr("test-key")))
    return factory


@pytest.fixture
def client_factory(app_factory):
    return lambda handler: TestClient(app_factory(handler))


@pytest.fixture
def completion():
    def factory(reply=None, **extra):
        return {"choices": [{"message": {"content": json.dumps(reply if reply is not None else {"text": "Привет!"})},
                              "finish_reason": "stop"}], **extra}
    return factory
