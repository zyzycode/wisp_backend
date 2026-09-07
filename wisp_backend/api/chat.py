from typing import Annotated

from fastapi import APIRouter, Depends
from starlette.responses import Response

from wisp_backend.api.dependencies import get_chat_proxy
from wisp_backend.proxy import ChatProxy
from wisp_backend.schemas import ChatRequest

router = APIRouter(prefix="/v1", tags=["chat"])


@router.post("/chat/completions")
async def chat(
    body: ChatRequest, proxy: Annotated[ChatProxy, Depends(get_chat_proxy)],
) -> Response:
    return await proxy.complete(body)
