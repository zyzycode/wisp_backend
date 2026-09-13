"""Groq request mapping and bounded model-output validation."""
import httpx
from pydantic import ValidationError

from wisp_backend.config import AssistantSettings
from wisp_backend.errors import ServiceError, invalid_response
from wisp_backend.json_codec import decode_json
from wisp_backend.schemas import ModelReply

MAX_UPSTREAM_BYTES = 256 * 1024


class GroqProvider:
    def __init__(self, client: httpx.AsyncClient):
        self.client = client

    async def complete(self, messages: list[dict[str, str]], settings: AssistantSettings) -> ModelReply:
        payload = {
            "model": settings.model, "messages": messages, "stream": False,
            "max_completion_tokens": settings.max_output_tokens,
            "response_format": {"type": "json_object"},
        }
        if settings.temperature is not None:
            payload["temperature"] = settings.temperature
        try:
            async with self.client.stream("POST", "chat/completions", json=payload) as response:
                # Provider throttling is not our own deployment admission policy.
                if not response.is_success:
                    raise ServiceError("upstream_unavailable")
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(content) + len(chunk) > MAX_UPSTREAM_BYTES:
                        raise invalid_response()
                    content.extend(chunk)
                try:
                    data = decode_json(content.decode("utf-8"))
                    choice = data["choices"][0]
                    if choice["finish_reason"] != "stop":
                        raise invalid_response()
                    proposed = choice["message"]["content"]
                    if not isinstance(proposed, str):
                        raise invalid_response()
                    return ModelReply.model_validate(decode_json(proposed))
                except (ValueError, KeyError, IndexError, TypeError, ValidationError, RecursionError):
                    raise invalid_response() from None
        except httpx.TimeoutException:
            raise ServiceError("upstream_timeout") from None
        except httpx.RequestError:
            raise ServiceError("upstream_unavailable") from None
