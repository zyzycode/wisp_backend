from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from wisp_backend.api.boundary import MAX_RESPONSE_BYTES, error_response
from wisp_backend.api.dependencies import get_chat_service
from wisp_backend.schemas import ChatRequest, ChatResponse, ErrorResponse
from wisp_backend.service import ChatService

router = APIRouter(prefix="/v1", tags=["chat"])


@router.post("/chat", response_model=ChatResponse, response_model_exclude_none=True,
             responses={status: {"model": ErrorResponse} for status in (400, 409, 413, 429, 502, 503, 504)})
async def chat(body: ChatRequest, service: Annotated[ChatService, Depends(get_chat_service)]):
    result = await service.complete(body)
    response = JSONResponse(result.model_dump(exclude_none=True))
    if len(response.body) > MAX_RESPONSE_BYTES:
        return error_response("payload_too_large", body.requestId)
    return response
