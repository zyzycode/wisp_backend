"""Groq wire protocol, normalization and SSE parsing stay inside this adapter."""
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from pydantic import ValidationError

from wisp_backend.config import AssistantSettings
from wisp_backend.errors import ServiceError, invalid_response
from wisp_backend.schemas import ChatResponse, DeltaEvent, DoneEvent, Message, Usage


def finish_reason(value):
    return {"stop": "stop", "length": "length", "content_filter": "filtered"}.get(value, "other")


def usage_from(value):
    if value is None:
        return None
    return Usage(input_tokens=value["prompt_tokens"], output_tokens=value["completion_tokens"],
                 total_tokens=value["total_tokens"])


class GroqProvider:
    def __init__(self, client: httpx.AsyncClient):
        self.client = client

    @asynccontextmanager
    async def response(self, messages, settings, streaming):
        payload = {
            "model": settings.model,
            "messages": [message.model_dump() for message in messages],
            "stream": streaming,
            "max_completion_tokens": settings.max_output_tokens,
        }
        if settings.temperature is not None:
            payload["temperature"] = settings.temperature
        try:
            async with self.client.stream("POST", "chat/completions", json=payload) as response:
                if response.status_code == 429:
                    raise ServiceError("rate_limited", "The assistant is busy. Try again later.", 429)
                if not response.is_success:
                    raise ServiceError("unavailable", "The assistant is temporarily unavailable.", 502)
                yield response
        except httpx.TimeoutException:
            raise ServiceError("timeout", "The assistant request timed out.", 504) from None
        except httpx.RequestError:
            raise ServiceError("unavailable", "The assistant is temporarily unavailable.", 502) from None

    async def complete(self, messages, settings) -> ChatResponse:
        async with self.response(messages, settings, False) as response:
            try:
                data = json.loads(await response.aread())
                choice = data["choices"][0]
                text = choice["message"]["content"]
                if not isinstance(text, str) or choice.get("finish_reason") is None:
                    raise invalid_response()
                return ChatResponse(text=text, finish_reason=finish_reason(choice["finish_reason"]),
                                    usage=usage_from(data.get("usage")))
            except (ValueError, KeyError, IndexError, TypeError, ValidationError):
                raise invalid_response() from None

    async def stream(self, messages, settings) -> AsyncIterator[DeltaEvent | DoneEvent]:
        async with self.response(messages, settings, True) as response:
            reason = None
            usage = None
            try:
                async for event in sse_data(response):
                    if event == "[DONE]":
                        if reason is None:
                            raise invalid_response()
                        yield DoneEvent(finish_reason=reason, usage=usage)
                        return
                    data = json.loads(event)
                    if "error" in data:
                        raise invalid_response()
                    raw_usage = data.get("usage") or data.get("x_groq", {}).get("usage")
                    if raw_usage is not None:
                        usage = usage_from(raw_usage)
                    choices = data["choices"]
                    if not choices:
                        continue
                    choice = choices[0]
                    delta = choice["delta"]
                    text = delta.get("content")
                    if text is not None:
                        if not isinstance(text, str) or reason is not None:
                            raise invalid_response()
                        if text:
                            yield DeltaEvent(text=text)
                    if choice.get("finish_reason") is not None:
                        reason = finish_reason(choice["finish_reason"])
            except (ValueError, KeyError, IndexError, TypeError, AttributeError, ValidationError):
                raise invalid_response() from None
            raise invalid_response()  # An incomplete stream must never look successful.


async def sse_data(response: httpx.Response) -> AsyncIterator[str]:
    parts = []
    size = 0
    async for line in response.aiter_lines():
        if line == "":
            if parts:
                yield "\n".join(parts)
                parts = []
                size = 0
        elif line.startswith("data:"):
            value = line[5:].removeprefix(" ")
            size += len(value)
            if size > 1_000_000:
                raise invalid_response()
            parts.append(value)
    if parts:
        yield "\n".join(parts)
