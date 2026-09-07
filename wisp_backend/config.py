"""Configuration loaded at startup, without mutating the process environment."""

import os
from pathlib import Path

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True)

    api_key: SecretStr
    base_url: str = "https://api.x.ai/v1/"
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
        key = values.get("XAI_API_KEY") or values.get("token_api")
        if not key or not key.strip():
            raise RuntimeError("Set XAI_API_KEY or token_api in the project .env")
        return cls(api_key=SecretStr(key))
