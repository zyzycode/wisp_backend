"""Configuration loaded at startup, without mutating the process environment."""

import os
from pathlib import Path

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class AssistantSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = "Assistant"
    provider: str = "groq"
    model: str = Field(default="openai/gpt-oss-20b", min_length=1)
    max_output_tokens: int = Field(default=4096, gt=0)
    temperature: float | None = Field(default=None, ge=0, le=2)


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True)

    api_key: SecretStr
    assistants: dict[str, AssistantSettings] = Field(
        default_factory=lambda: {"default": AssistantSettings()}, min_length=1,
    )
    base_url: str = "https://api.groq.com/openai/v1/"
    request_timeout: float = Field(default=3600, gt=0)
    connect_timeout: float = Field(default=15, gt=0)
    pool_timeout: float = Field(default=15, gt=0)

    @field_validator("api_key")
    @classmethod
    def validate_key(cls, value: SecretStr) -> SecretStr:
        key = value.get_secret_value().strip()
        if not key:
            raise ValueError("API key must not be blank")
        return SecretStr(key)

    @classmethod
    def from_env(cls, env_file: Path = ENV_FILE) -> "Settings":
        values = {**dotenv_values(env_file), **os.environ}
        key = values.get("GROQ_API_KEY") or values.get("token_api")
        if not key or not key.strip():
            raise RuntimeError("Set GROQ_API_KEY or token_api in the project .env")
        assistants = values.get("ASSISTANTS_JSON")
        if assistants:
            import json
            return cls(api_key=SecretStr(key), assistants=json.loads(assistants))
        return cls(api_key=SecretStr(key))
