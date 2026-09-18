"""Bounded Groq output; retain safe usage even when model content is invalid."""
import httpx
from pydantic import ValidationError

from wisp_backend.config import AssistantSettings
from wisp_backend.contracts import ProviderResult, Usage
from wisp_backend.json_codec import decode_json
from wisp_backend.schemas import ModelReply

MAX_UPSTREAM_BYTES = 256 * 1024


class GroqProvider:
    def __init__(self, client: httpx.AsyncClient):
        self.client = client

    async def complete(self, messages: list[dict[str, str]], settings: AssistantSettings,
                       timeout: float) -> ProviderResult:
        payload = {
            "model": settings.model, "messages": messages, "stream": False,
            "max_completion_tokens": settings.max_output_tokens,
            "response_format": {"type": "json_object"},
        }
        if settings.temperature is not None:
            payload["temperature"] = settings.temperature
        usage = None
        try:
            budget = httpx.Timeout(timeout, connect=min(3, timeout, self.client.timeout.connect),
                                   pool=min(3, timeout, self.client.timeout.pool))
            async with self.client.stream("POST", "chat/completions", json=payload, timeout=budget) as response:
                if not response.is_success:
                    return ProviderResult(error="upstream_unavailable")
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(content) + len(chunk) > MAX_UPSTREAM_BYTES:
                        return ProviderResult(error="invalid_model_response")
                    content.extend(chunk)
                try:
                    data = decode_json(content.decode("utf-8"))
                    usage = Usage.parse(data.get("usage")) if isinstance(data, dict) else None
                    choice = data["choices"][0]
                    if choice["finish_reason"] != "stop":
                        return ProviderResult(usage=usage, error="invalid_model_response")
                    proposed = choice["message"]["content"]
                    if not isinstance(proposed, str):
                        return ProviderResult(usage=usage, error="invalid_model_response")
                    return ProviderResult(ModelReply.model_validate(decode_json(proposed)), usage)
                except (ValueError, KeyError, IndexError, TypeError, ValidationError, RecursionError):
                    return ProviderResult(usage=usage, error="invalid_model_response")
        except httpx.TimeoutException:
            return ProviderResult(error="upstream_timeout")
        except httpx.RequestError:
            return ProviderResult(error="upstream_unavailable")
