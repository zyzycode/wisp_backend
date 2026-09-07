from contextlib import aclosing
from typing import Annotated

from fastapi import APIRouter, Depends
from starlette.responses import StreamingResponse

from wisp_backend.api.dependencies import get_chat_service
from wisp_backend.errors import ServiceError
from wisp_backend.schemas import (
    AssistantsResponse, ChatRequest, ChatResponse, DeltaEvent, DoneEvent,
    ErrorDetail, ErrorEvent, ErrorResponse,
)
from wisp_backend.service import ChatService

router = APIRouter(prefix="/v1", tags=["chat"])
Service = Annotated[ChatService, Depends(get_chat_service)]


@router.get("/assistants", response_model=AssistantsResponse)
async def assistants(service: Service):
    return AssistantsResponse(assistants=service.list_assistants())


def encode_event(event):
    return f"event: {event.type}\ndata: {event.model_dump_json()}\n\n"


@router.post(
    "/chat/completions", response_model=ChatResponse,
    responses={
        200: {"description": "Text response or SSE events: delta, done, error.",
              "content": {"text/event-stream": {"schema": {"type": "string"},
                  "example": 'event: delta\ndata: {"type":"delta","text":"Hello"}\n\n'}}},
        **{status: {"model": ErrorResponse} for status in (422, 429, 502, 504)},
    },
)
async def chat(body: ChatRequest, service: Service):
    if not body.stream:
        return await service.complete(body)
    events = service.stream(body)  # Resolve profile before sending response headers.

    async def generate():
        async with aclosing(events):
            try:
                async for event in events:
                    yield encode_event(event)
            except ServiceError as error:
                yield encode_event(ErrorEvent(error=ErrorDetail(code=error.code, message=error.message)))

    return StreamingResponse(generate(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
