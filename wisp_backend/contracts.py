"""Internal accounting contracts; never serialized onto the desktop wire."""
from dataclasses import dataclass
from typing import Literal, Protocol
from threading import Event

from wisp_backend.schemas import ModelReply, ErrorCode
from wisp_backend.memory_schemas import MemoryModelReply

RESERVATION = 131_072


@dataclass(frozen=True)
class Usage:
    prompt: int
    completion: int
    total: int

    @classmethod
    def parse(cls, value: object) -> "Usage | None":
        if not isinstance(value, dict):
            return None
        parts = [value.get(key) for key in ("prompt_tokens", "completion_tokens", "total_tokens")]
        if any(type(part) is not int or part < 0 for part in parts):
            return None
        prompt, completion, total = parts
        return cls(prompt, completion, total) if prompt + completion == total else None


@dataclass(frozen=True)
class ReplyContext:
    version: Literal[1, 2] = 1
    evidence_quote: str | None = None


@dataclass(frozen=True)
class ProviderResult:
    reply: ModelReply | MemoryModelReply | None = None
    usage: Usage | None = None
    error: ErrorCode | None = None


@dataclass(frozen=True)
class Outcome:
    status: int
    body: bytes


@dataclass(frozen=True)
class Admission:
    replay: Outcome | None = None


class Ledger(Protocol):
    async def admit(self, request_id: str, digest: str, legacy_digest: str | None = None) -> Admission: ...
    async def settle(self, request_id: str, usage: Usage | None, outcome: Outcome | None,
                     deadline: float | None = None, cancelled: Event | None = None) -> None: ...
    async def maintain(self) -> None: ...
    async def close(self) -> None: ...
