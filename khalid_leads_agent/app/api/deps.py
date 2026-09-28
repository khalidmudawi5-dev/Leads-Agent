from __future__ import annotations

from fastapi import Request

from app.container import AppContainer


def container(request: Request) -> AppContainer:
    return request.app.state.container
