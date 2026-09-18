import os
from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from wisp_backend.config import Settings


@pytest.fixture
def env_values(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("token_api", raising=False)
    monkeypatch.delenv("ASSISTANTS_JSON", raising=False)
    values = {}
    monkeypatch.setattr("wisp_backend.config.dotenv_values", lambda _: values)
    return values


def test_environment_precedence_and_no_mutation(monkeypatch, env_values):
    env_values.update(GROQ_API_KEY="file-key", token_api="legacy-key")
    monkeypatch.setenv("GROQ_API_KEY", " process-key ")
    settings = Settings.from_env()
    assert settings.api_key.get_secret_value() == "process-key"
    assert "token_api" not in os.environ
    assert "process-key" not in repr(settings)


def test_custom_env_file(monkeypatch):
    def read(path):
        assert path == Path("custom.env")
        return {"GROQ_API_KEY": "file-key"}
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr("wisp_backend.config.dotenv_values", read)
    assert Settings.from_env(Path("custom.env")).api_key.get_secret_value() == "file-key"


@pytest.mark.parametrize("values", [{"token_api": "legacy"}, {"GROQ_API_KEY": "", "token_api": "legacy"}])
def test_legacy_key(env_values, values):
    env_values.update(values)
    assert Settings.from_env().api_key.get_secret_value() == "legacy"


@pytest.mark.parametrize("values", [{}, {"GROQ_API_KEY": "   "}])
def test_missing_key(env_values, values):
    env_values.update(values)
    with pytest.raises(RuntimeError, match="Set GROQ_API_KEY"):
        Settings.from_env()


@pytest.mark.parametrize("kwargs", [
    {"api_key": SecretStr(" ")}, {"api_key": SecretStr("key"), "request_timeout": 0},
])
def test_explicit_settings_validation(kwargs):
    with pytest.raises(ValidationError):
        Settings(**kwargs)


def test_server_profiles_from_environment(env_values):
    env_values.update(GROQ_API_KEY="key", ASSISTANTS_JSON=
        '{"default":{"provider":"groq","model":"openai/gpt-oss-20b","max_output_tokens":256}}')
    settings = Settings.from_env()
    assert settings.assistants["default"].model == "openai/gpt-oss-20b"
    assert settings.assistants["default"].max_output_tokens == 256


@pytest.mark.parametrize('profile', [
    {'model':'unreviewed'}, {'provider':'other'}, {'max_output_tokens':4097},
    {'max_output_tokens': True},
])
def test_unreviewed_profile_or_limits_rejected(profile):
    with pytest.raises(ValidationError):
        Settings(api_key=SecretStr('test'), assistants={'default':profile})


def test_operator_limits_and_ledger_path(env_values):
    env_values.update(GROQ_API_KEY='test', WISP_LEDGER_PATH='/tmp/operator.sqlite',
        WISP_LIMITS_JSON='{"rate_limit":4,"concurrent_limit":1,"daily_requests":8,"daily_tokens":131072}')
    config = Settings.from_env()
    assert config.ledger_path == Path('/tmp/operator.sqlite')
    assert config.ledger.rate_limit == 4
    for invalid in ({'rate_limit':True}, {'daily_tokens':131071}, {'concurrent_limit':0}, {'extra':1}):
        with pytest.raises(ValidationError):
            Settings(api_key=SecretStr('test'), ledger=invalid)
