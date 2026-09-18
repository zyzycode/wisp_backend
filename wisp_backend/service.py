"""Admission, bounded provider lifetime and independent terminal settlement."""
import asyncio
from threading import Event
from collections.abc import Mapping

from pydantic import ValidationError
from starlette.responses import JSONResponse

from wisp_backend.config import AssistantSettings
from wisp_backend.contracts import Ledger, Outcome, ProviderResult, ReplyContext
from wisp_backend.errors import ERROR_STATUS, ServiceError
from wisp_backend.prompts import build_messages
from wisp_backend.providers.base import Provider
from wisp_backend.schemas import ChatRequest, ChatResponse, ErrorDetail, ErrorResponse, ModelReply, trim_text
from wisp_backend.memory_schemas import MemoryRequest, MemoryResponse, MemoryModelReply, MemoryErrorResponse


def failure(code, request_id, retry_after_ms=None, version=1):
    error = ErrorDetail(code=code, **({"retryAfterMs": retry_after_ms} if retry_after_ms is not None else {}))
    response_type = MemoryErrorResponse if version == 2 else ErrorResponse
    body = response_type(version=version, requestId=request_id, error=error).model_dump(exclude_none=True)
    body['requestId'] = request_id
    return Outcome(ERROR_STATUS[code], JSONResponse(body).body)


class ChatService:
    def __init__(self, providers: Mapping[str, Provider], assistants: Mapping[str, AssistantSettings],
                 ledger: Ledger, deadline: float = 10):
        self.providers, self.assistants, self.ledger = dict(providers), dict(assistants), ledger
        self.deadline = deadline
        self.closing = False
        self.requests: set[asyncio.Task] = set()
        self.background: set[asyncio.Task] = set()
        if "default" not in self.assistants:
            raise ValueError("A default assistant is required")
        for settings in self.assistants.values():
            if settings.provider not in self.providers:
                raise ValueError("Assistant references an unregistered provider")

    def _track(self, task):
        self.background.add(task)
        def finished(done):
            self.background.discard(done)
            if not done.cancelled():
                done.exception()  # never log provider payload/exception details
        task.add_done_callback(finished)
        return task

    async def _late(self, task, request_id, settlement):
        try:
            await asyncio.shield(settlement)
            result = await task
            if isinstance(result, ProviderResult) and result.usage:
                await self.ledger.settle(request_id, result.usage, None)
        except (asyncio.CancelledError, Exception):
            pass  # uncertain reservation is already durable

    async def _abandoned_admission(self, task, request_id):
        try:
            admission = await task
            if admission.replay is None:
                await self.ledger.settle(request_id, None, None)
        except ServiceError:
            pass

    async def complete(self, body: ChatRequest | MemoryRequest, digest: str, started: float,
                       legacy_digest: str | None = None) -> Outcome:
        current = asyncio.current_task()
        self.requests.add(current)
        current.add_done_callback(self.requests.discard)
        publication_cancelled = Event()
        admitted = False
        provider_task = None
        result = None
        outcome = None
        admission_task = None
        cancelled = False
        end = started + self.deadline
        try:
            if self.closing:
                raise ServiceError("upstream_unavailable")
            if asyncio.get_running_loop().time() >= end:
                raise ServiceError("upstream_timeout")
            admission_task = asyncio.create_task(self.ledger.admit(body.requestId, digest, legacy_digest))
            done, _ = await asyncio.wait({admission_task}, timeout=end - asyncio.get_running_loop().time())
            if not done:
                self._track(asyncio.create_task(self._abandoned_admission(admission_task, body.requestId)))
                admission_task = None
                raise ServiceError("upstream_timeout")
            admission = admission_task.result()
            if admission.replay:
                return admission.replay
            admitted = True
            remaining = end - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise ServiceError("upstream_timeout")
            settings = self.assistants['default']
            provider = self.providers[settings.provider]
            if isinstance(body, MemoryRequest):
                call = provider.complete(build_messages(body), settings, remaining,
                                         ReplyContext(2, trim_text(body.messages[-1].content)))
            else:
                call = provider.complete(build_messages(body), settings, remaining)
            provider_task = asyncio.create_task(call)
            done, _ = await asyncio.wait({provider_task}, timeout=remaining)
            if not done:
                raise ServiceError("upstream_timeout")
            result = provider_task.result()
            if not isinstance(result, ProviderResult):
                raise ServiceError("invalid_model_response")
            if result.error:
                raise ServiceError(result.error)
            try:
                model_type = MemoryModelReply if isinstance(body, MemoryRequest) else ModelReply
                response_type = MemoryResponse if isinstance(body, MemoryRequest) else ChatResponse
                context = {'evidence_quote': trim_text(body.messages[-1].content)}
                reply = model_type.model_validate(result.reply.model_dump(exclude_none=True), context=context)
                response = response_type.model_validate(
                    {'version': body.version, 'requestId': body.requestId, **reply.model_dump(exclude_none=True)}, context=context)
                outcome = Outcome(200, JSONResponse(response.model_dump(exclude_none=True)).body)
                if len(outcome.body) > 16 * 1024:
                    raise ServiceError("payload_too_large")
            except (ValidationError, AttributeError, TypeError):
                raise ServiceError("invalid_model_response") from None
        except asyncio.CancelledError:
            cancelled = True
            publication_cancelled.set()
            # Cancellation may race a committed admission on the SQLite worker.
            if admission_task and not admitted:
                self._track(asyncio.create_task(self._abandoned_admission(admission_task, body.requestId)))
        except ServiceError as error:
            outcome = failure(error.code, body.requestId, error.retry_after_ms, version=body.version)
        except Exception:
            outcome = failure("upstream_unavailable", body.requestId, version=body.version)
        finally:
            if provider_task and not provider_task.done():
                provider_task.cancel()
            if admitted:
                usage = result.usage if isinstance(result, ProviderResult) else None
                settlement = self._track(asyncio.create_task(self.ledger.settle(body.requestId, usage, outcome, end, publication_cancelled)))
                try:
                    if cancelled:
                        await asyncio.shield(settlement)
                    else:
                        done, _ = await asyncio.wait({settlement}, timeout=max(0, end - asyncio.get_running_loop().time()))
                        if not done:
                            outcome = failure("upstream_timeout", body.requestId, version=body.version)
                        else:
                            settlement.result()
                except ServiceError:
                    outcome = failure("upstream_unavailable", body.requestId, version=body.version)
                except asyncio.CancelledError:
                    publication_cancelled.set()
                    raise
                finally:
                    if provider_task and result is None:
                        self._track(asyncio.create_task(self._late(provider_task, body.requestId, settlement)))
            self.requests.discard(current)
        if cancelled:
            raise asyncio.CancelledError
        return outcome

    async def close(self):
        self.closing = True
        tasks = list(self.requests)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        # Cooperative provider HTTP tasks close streams on cancellation. A provider
        # ignoring cancellation never blocks shutdown or rewrites a terminal reply.
        remaining = list(self.background)
        if remaining:
            _, pending = await asyncio.wait(remaining, timeout=0.5)
            for task in pending:
                task.cancel()
            await asyncio.gather(*remaining, return_exceptions=True)
