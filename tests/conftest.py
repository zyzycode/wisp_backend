import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from wisp_backend.application import create_app
from wisp_backend.config import Settings


@pytest.fixture
def body():
    return {"messages": [{"role": "user", "content": "hi"}]}


@pytest.fixture
def app_factory():
    def factory(handler):
        return create_app(httpx.MockTransport(handler), settings=Settings(api_key=SecretStr("test-key")))
    return factory


@pytest.fixture
def client_factory(app_factory):
    # Use as a context manager so every test runs startup and shutdown.
    return lambda handler: TestClient(app_factory(handler))
