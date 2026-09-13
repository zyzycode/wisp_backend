"""Bound JSON request reads before FastAPI parses the request body."""
from starlette.responses import JSONResponse

from wisp_backend.errors import ERROR_STATUS
from wisp_backend.json_codec import decode_json
from wisp_backend.schemas import ErrorDetail, ErrorResponse, read_request_id

MAX_REQUEST_BYTES = 32 * 1024
MAX_RESPONSE_BYTES = 16 * 1024


def error_response(code, request_id=None):
    body = ErrorResponse(version=1, requestId=request_id, error=ErrorDetail(code=code))
    return JSONResponse(body.model_dump(exclude_none=True) | {"requestId": request_id}, status_code=ERROR_STATUS[code])


class ChatBoundary:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] != "/v1/chat" or scope["method"] != "POST":
            return await self.app(scope, receive, send)
        headers = dict(scope["headers"])
        content_type = headers.get(b"content-type", b"").decode("latin-1").lower()
        if content_type.split(";", 1)[0].strip() != "application/json" or headers.get(b"content-encoding", b"identity") != b"identity":
            return await error_response("invalid_request")(scope, receive, send)
        chunks = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(chunks) + len(chunk) > MAX_REQUEST_BYTES:
                return await error_response("payload_too_large")(scope, receive, send)
            chunks.extend(chunk)
            if not message.get("more_body", False):
                break
        try:
            data = decode_json(chunks.decode("utf-8"))
        except (ValueError, UnicodeError, RecursionError):
            return await error_response("invalid_request")(scope, receive, send)
        request_id = read_request_id(data)
        scope.setdefault("state", {})["request_id"] = request_id
        if isinstance(data, dict) and "version" in data and type(data["version"]) is int and data["version"] != 1:
            return await error_response("unsupported_version", request_id)(scope, receive, send)
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(chunks), "more_body": False}
            return await receive()
        await self.app(scope, replay, send)
