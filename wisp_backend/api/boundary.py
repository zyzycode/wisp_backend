"""Bounded input and downstream disconnect cancellation, before FastAPI parsing."""
import asyncio
import hashlib

from starlette.responses import Response

from wisp_backend.json_codec import decode_json
from wisp_backend.schemas import read_request_id
from wisp_backend.service import failure

MAX_REQUEST_BYTES = 32 * 1024
MAX_RESPONSE_BYTES = 16 * 1024
BODY_TIMEOUT = 2


def error_response(code, request_id=None, retry_after_ms=None, version=1):
    outcome = failure(code, request_id, retry_after_ms, version)
    return Response(outcome.body, status_code=outcome.status, media_type="application/json")


class ChatBoundary:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] not in ("/v1/chat", "/v2/chat") or scope["method"] != "POST":
            return await self.app(scope, receive, send)
        started = asyncio.get_running_loop().time()
        version = 2 if scope["path"] == "/v2/chat" else 1
        scope.setdefault("state", {})['wire_version'] = version
        headers = dict(scope["headers"])
        content_type = headers.get(b"content-type", b"").decode("latin-1").lower()
        if content_type.split(";", 1)[0].strip() != "application/json" or headers.get(b"content-encoding", b"identity") != b"identity":
            return await error_response("invalid_request", version=version)(scope, receive, send)
        chunks = bytearray()

        async def read():
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return "disconnected"
                chunk = message.get("body", b"")
                if len(chunks) + len(chunk) > MAX_REQUEST_BYTES:
                    return "payload_too_large"
                chunks.extend(chunk)
                if not message.get("more_body", False):
                    return None
        try:
            error = await asyncio.wait_for(read(), BODY_TIMEOUT)
        except asyncio.TimeoutError:
            error = "invalid_request"
        if error == "disconnected":
            return
        if error:
            return await error_response(error, version=version)(scope, receive, send)
        try:
            data = decode_json(chunks.decode("utf-8"))
        except (ValueError, UnicodeError, RecursionError):
            return await error_response("invalid_request", version=version)(scope, receive, send)
        request_id = read_request_id(data)
        namespace = scope['method'] + ' ' + scope['path']
        digest = namespace + ':' + hashlib.sha256(namespace.encode() + b'\0' + chunks).hexdigest()
        legacy_digest = hashlib.sha256(chunks).hexdigest() if version == 1 else None
        scope['state'].update(request_id=request_id, started=started, digest=digest, legacy_digest=legacy_digest)
        if isinstance(data, dict) and "version" in data and type(data["version"]) is int and data["version"] != version:
            return await error_response("unsupported_version", request_id, version=version)(scope, receive, send)
        delivered = asyncio.Event()

        async def replay():
            if not delivered.is_set():
                delivered.set()
                return {"type": "http.request", "body": bytes(chunks), "more_body": False}
            # Only the disconnect watcher reads from the original receive channel.
            await asyncio.Future()

        async def disconnected():
            await delivered.wait()
            while True:
                if (await receive())["type"] == "http.disconnect":
                    return

        request_task = asyncio.create_task(self.app(scope, replay, send))
        watcher = asyncio.create_task(disconnected())
        try:
            done, _ = await asyncio.wait({request_task, watcher}, return_when=asyncio.FIRST_COMPLETED)
            if watcher in done and not request_task.done():
                request_task.cancel()
            await request_task
        except asyncio.CancelledError:
            request_task.cancel()
            await asyncio.gather(request_task, return_exceptions=True)
        finally:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)
