from fastapi import Request

from wisp_backend.proxy import ChatProxy


def get_chat_proxy(request: Request) -> ChatProxy:
    return request.app.state.chat_proxy
