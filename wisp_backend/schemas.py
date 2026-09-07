"""Provider-independent public API contracts."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HealthResponse(Contract):
    status: Literal["ok"] = "ok"


class Message(Contract):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=100_000)


class ChatRequest(Contract):
    messages: list[Message] = Field(min_length=1, max_length=200)
    assistant: str = Field(default="default", min_length=1, max_length=64)
    stream: StrictBool = False
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [{
        "messages": [{"role": "user", "content": "Привет!"}],
        "assistant": "default", "stream": False,
    }]})


class Usage(Contract):
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)


class ChatResponse(Contract):
    text: str
    finish_reason: Literal["stop", "length", "filtered", "other"]
    usage: Usage | None = None


class ErrorDetail(Contract):
    code: Literal["invalid_request", "unknown_assistant", "rate_limited", "unavailable", "timeout", "invalid_response"]
    message: str


class ErrorResponse(Contract):
    error: ErrorDetail


class DeltaEvent(Contract):
    type: Literal["delta"] = "delta"
    text: str


class DoneEvent(Contract):
    type: Literal["done"] = "done"
    finish_reason: Literal["stop", "length", "filtered", "other"]
    usage: Usage | None = None


class ErrorEvent(ErrorResponse):
    type: Literal["error"] = "error"


class AssistantInfo(Contract):
    id: str
    name: str


class AssistantsResponse(Contract):
    assistants: list[AssistantInfo]
