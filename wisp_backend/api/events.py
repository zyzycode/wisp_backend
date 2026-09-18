"""Explicit v3 event and follow-up chat endpoints sharing the existing ledger."""
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from wisp_backend.api.dependencies import get_chat_service
from wisp_backend.events_schemas import (
    EventRequest, EventResponse, EventErrorResponse, EventAwareChatRequest, EventAwareChatResponse,
)
from wisp_backend.service import ChatService

router = APIRouter(prefix='/v3', tags=['companion events'])
ERROR_RESPONSES = {status: {'model': EventErrorResponse} for status in (400, 409, 413, 429, 502, 503, 504)}


@router.post('/events', response_model=EventResponse, responses=ERROR_RESPONSES)
async def event(body: EventRequest, request: Request, service: Annotated[ChatService, Depends(get_chat_service)]):
    outcome = await service.complete(body, request.state.digest, request.state.started)
    return Response(outcome.body, status_code=outcome.status, media_type='application/json')


@router.post('/chat', response_model=EventAwareChatResponse, response_model_exclude_none=True, responses=ERROR_RESPONSES)
async def chat(body: EventAwareChatRequest, request: Request, service: Annotated[ChatService, Depends(get_chat_service)]):
    outcome = await service.complete(body, request.state.digest, request.state.started)
    return Response(outcome.body, status_code=outcome.status, media_type='application/json')
