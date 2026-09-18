"""Explicit v2 memory endpoint; shares service/ledger/lifecycle with v1."""
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from wisp_backend.api.dependencies import get_chat_service
from wisp_backend.memory_schemas import MemoryRequest, MemoryResponse, MemoryErrorResponse
from wisp_backend.service import ChatService

router = APIRouter(prefix='/v2', tags=['memory chat'])


@router.post('/chat', response_model=MemoryResponse, response_model_exclude_none=True,
             responses={status: {'model': MemoryErrorResponse} for status in (400, 409, 413, 429, 502, 503, 504)})
async def chat(body: MemoryRequest, request: Request, service: Annotated[ChatService, Depends(get_chat_service)]):
    outcome = await service.complete(body, request.state.digest, request.state.started)
    return Response(outcome.body, status_code=outcome.status, media_type='application/json')
