from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from wisp_backend.api.dependencies import get_chat_service
from wisp_backend.schemas import ChatRequest, ChatResponse, ErrorResponse
from wisp_backend.service import ChatService

router = APIRouter(prefix="/v1", tags=["chat"])


@router.post("/chat", response_model=ChatResponse, response_model_exclude_none=True,
             responses={status: {"model": ErrorResponse} for status in (400, 409, 413, 429, 502, 503, 504)})
async def chat(body: ChatRequest, request: Request, service: Annotated[ChatService, Depends(get_chat_service)]):
    outcome = await service.complete(body, request.state.digest, request.state.started, request.state.legacy_digest)
    return Response(outcome.body, status_code=outcome.status, media_type="application/json")
