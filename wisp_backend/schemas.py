"""Standalone Desktop/Backend v1 wire schemas."""
import re
import unicodedata
from typing import Annotated, Literal

from pydantic import (
    BaseModel, ConfigDict, Field, StrictBool, ValidationError,
    AfterValidator, BeforeValidator, field_validator, model_validator,
)


# ECMAScript trim whitespace, matching the desktop transport boundary.
TRIM_CHARACTERS = '\t\n\x0b\x0c\r \xa0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff'


def trim_text(value: str) -> str:
    return value.strip(TRIM_CHARACTERS)


def omittable():
    # A missing optional TS field is valid; an explicit null is not its default.
    return Field(default=None, json_schema_extra=lambda schema: schema.pop("default", None))


def validate_text(value: str, limit: int) -> str:
    # Validate original length: trimming must not rescue an oversized value.
    if any(unicodedata.category(char) in ("Cc", "Cs") and char not in "\n\t" for char in value):
        raise ValueError("Forbidden control character")
    if len(value.encode("utf-16-le")) // 2 > limit or not trim_text(value):
        raise ValueError("Invalid UTF-16 text length")
    return value


def text_type(limit):
    return Annotated[str, AfterValidator(lambda value: validate_text(value, limit)),
                     Field(description=f"Nonblank plain text, at most {limit} UTF-16 code units; no controls except newline/tab.")]


def version(value):
    if type(value) is not int or value != 1:
        raise ValueError("Expected integer version 1")
    return value


def false_only(value):
    if value is not False:
        raise ValueError("Only stream=false is supported")
    return value


UUID4_PATTERN = r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-4[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
RequestId = Annotated[str, Field(pattern=UUID4_PATTERN)]
Version = Annotated[Literal[1], BeforeValidator(version)]
Percent = Annotated[float, Field(strict=True, ge=0, le=100, allow_inf_nan=False)]
Unit = Annotated[float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)]
Bond = Annotated[float, Field(strict=True, ge=0, le=1000, allow_inf_nan=False)]
Behavior = Literal["respond", "think", "react_happy", "react_confused", "play", "sleep", "wake", "wander", "idle", "quiet"]
Tone = Literal["warm", "playful", "sleepy", "curious", "confused", "quiet", "shy", "affectionate"]
Mood = Literal["neutral", "happy", "playful", "sleepy", "confused", "shy", "affectionate"]
CharacterTone = Literal["shy", "sleepy", "playful", "curious", "neutral", "affectionate", "flustered"]
ErrorCode = Literal["invalid_request", "unsupported_version", "payload_too_large", "request_conflict",
                    "request_in_progress", "rate_limited", "budget_exhausted", "upstream_unavailable",
                    "upstream_timeout", "invalid_model_response"]


def read_request_id(value):
    if isinstance(value, dict):
        candidate = value.get("requestId")
        if isinstance(candidate, str) and re.fullmatch(UUID4_PATTERN, candidate):
            return candidate
    return None


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class HealthResponse(Contract):
    status: Literal["ok"] = "ok"


class Message(Contract):
    role: Literal["user", "assistant"]
    content: str

    @model_validator(mode="after")
    def content_length(self):
        validate_text(self.content, 240 if self.role == "user" else 2000)
        return self


class Needs(Contract):
    energy: Percent
    attention: Percent
    play: Percent
    comfort: Percent
    boredom: Percent = omittable()


class Relationship(Contract):
    friendship: Bond
    love: Bond
    loveUnlocked: StrictBool


class Traits(Contract):
    shyness: Unit
    playfulness: Unit
    sensitivity: Unit
    boldness: Unit


class Personality(Contract):
    presetId: text_type(128)
    aiSelfConcept: text_type(500)
    traits: Traits


class Intimacy(Contract):
    flirtiness: Percent
    romanticCharge: Percent
    userConsentEnabled: StrictBool


class CharacterContext(Contract):
    needs: Needs
    relationship: Relationship
    personality: Personality
    intimacy: Intimacy
    synthesizedTone: CharacterTone


class Event(Contract):
    type: Literal["user_message"]


class ChatRequest(Contract):
    model_config = ConfigDict(
        extra="forbid", strict=True, allow_inf_nan=False,
        json_schema_extra=
        {'examples': [{'version': 1,
                       'requestId': '02d80270-1a72-47c9-a713-335b872ad24b',
                       'event': {'type': 'user_message'},
                       'messages': [{'role': 'user', 'content': 'Привет!'}],
                       'stream': False,
                       'locale': 'ru',
                       'character': {'needs': {'energy': 80,
                                               'attention': 50,
                                               'play': 60,
                                               'comfort': 80},
                                     'relationship': {'friendship': 100,
                                                      'love': 0,
                                                      'loveUnlocked': False},
                                     'personality': {'presetId': 'default',
                                                     'aiSelfConcept': 'Я Wisp, твой компаньон.',
                                                     'traits': {'shyness': 0.4,
                                                                'playfulness': 0.6,
                                                                'sensitivity': 0.5,
                                                                'boldness': 0.4}},
                                     'intimacy': {'flirtiness': 0,
                                                  'romanticCharge': 0,
                                                  'userConsentEnabled': False},
                                     'synthesizedTone': 'curious'}}]},
    )

    version: Version
    requestId: RequestId
    event: Event
    messages: list[Message] = Field(min_length=1, max_length=7)
    stream: Annotated[Literal[False], BeforeValidator(false_only)]
    locale: Literal["ru", "en"]
    character: CharacterContext

    @field_validator("messages")
    @classmethod
    def alternating_messages(cls, messages):
        if len(messages) % 2 != 1 or any(
            item.role != ("user" if index % 2 == 0 else "assistant")
            for index, item in enumerate(messages)
        ):
            raise ValueError("Expected user, assistant, ..., user")
        return messages


class Decision(Contract):
    behavior: Behavior
    tone: Tone = omittable()
    mood: Mood = omittable()
    confidence: Unit


class ModelReply(Contract):
    """Only this content may be proposed by a provider, never the wire envelope."""
    text: text_type(2000)
    decision: Decision = omittable()

    @model_validator(mode="before")
    @classmethod
    def discard_invalid_hint(cls, value):
        if isinstance(value, dict) and "decision" in value:
            try:
                Decision.model_validate(value["decision"])
            except ValidationError:
                value = {key: item for key, item in value.items() if key != "decision"}
        return value

    @field_validator("text")
    @classmethod
    def trim_text(cls, value):
        return trim_text(value)


class ChatResponse(ModelReply):
    version: Version
    requestId: RequestId


class ErrorDetail(Contract):
    code: ErrorCode
    retryAfterMs: Annotated[int, Field(ge=1, le=86_400_000)] = omittable()


class ErrorResponse(Contract):
    version: Version
    requestId: RequestId | None
    error: ErrorDetail
