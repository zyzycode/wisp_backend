"""Configuration loaded at startup, without mutating the process environment."""

import os
from pathlib import Path

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class AssistantSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = "Assistant"
    provider: str = "groq"
    model: str = Field(default="openai/gpt-oss-20b", min_length=1)
    max_output_tokens: int = Field(default=4096, gt=0, le=4096, strict=True)
    temperature: float | None = Field(default=None, ge=0, le=2)


class LedgerSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    rate_limit: int = Field(default=12, gt=0, strict=True)
    concurrent_limit: int = Field(default=2, gt=0, strict=True)
    daily_requests: int = Field(default=100, gt=0, strict=True)
    daily_tokens: int = Field(default=1_000_000, ge=131_072, strict=True)


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True)

    api_key: SecretStr
    assistants: dict[str, AssistantSettings] = Field(
        default_factory=lambda: {"default": AssistantSettings()}, min_length=1,
    )
    base_url: str = "https://api.groq.com/openai/v1/"
    request_timeout: float = Field(default=10, gt=0, le=10)
    connect_timeout: float = Field(default=3, gt=0, le=3)
    pool_timeout: float = Field(default=3, gt=0, le=3)
    ledger_path: Path = Path.home() / ".local" / "state" / "wisp-backend" / "ledger.sqlite"
    ledger: LedgerSettings = Field(default_factory=LedgerSettings)

    @model_validator(mode="after")
    def validate_profiles(self):
        if "default" not in self.assistants:
            raise ValueError("A default assistant is required")
        for profile in self.assistants.values():
            if profile.provider != "groq" or profile.model != "openai/gpt-oss-20b":
                raise ValueError("Unsupported model reservation profile")
            if profile.max_output_tokens > 4096:
                raise ValueError("Output tokens exceed the reviewed profile")
        return self

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
        import json
        options = {"api_key": SecretStr(key)}
        if assistants:
            options["assistants"] = json.loads(assistants)
        if values.get("WISP_LEDGER_PATH"):
            options["ledger_path"] = Path(values["WISP_LEDGER_PATH"])
        if values.get("WISP_LIMITS_JSON"):
            options["ledger"] = json.loads(values["WISP_LIMITS_JSON"])
        return cls(**options)
