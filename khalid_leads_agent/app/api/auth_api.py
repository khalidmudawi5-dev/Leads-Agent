"""Sign-in settings (Settings › الأمان) and the agent version (open on the PC for run.py)."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.login_service import COOKIE, LoginService
from app.version import VERSION

router = APIRouter(prefix="/api")


class PasswordIn(BaseModel):
    username: str = Field(default="", max_length=40)
    password: str = Field(default="", max_length=200)
    current_password: str = Field(default="", max_length=200)


class CurrentIn(BaseModel):
    current_password: str = Field(default="", max_length=200)


def _login(request: Request) -> LoginService:
    return request.app.state.login


def _client(request: Request) -> str:
    return request.client.host if request.client else ""


@router.get("/version")
def version() -> dict:
    return {"version": VERSION}


@router.get("/auth/status")
def auth_status(request: Request) -> dict:
    return {**_login(request).status(), "remote": request.app.state.remote is not None}


@router.post("/auth/password")
def auth_set_password(body: PasswordIn, request: Request):
    """Turn sign-in on, or change the username/password (the current password is required when on).
    This browser stays signed in; every other device must sign in again."""
    login = _login(request)
    login.set_password(_client(request), body.username, body.password, body.current_password)
    value, ttl = login.token(remember=False)
    resp = JSONResponse(login.status())
    resp.set_cookie(COOKIE, value, httponly=True, samesite="strict")
    return resp


@router.post("/auth/disable")
def auth_disable(body: CurrentIn, request: Request) -> dict:
    _login(request).disable(_client(request), body.current_password)
    return _login(request).status()


@router.post("/auth/sign-out-all")
def auth_sign_out_all(request: Request):
    login = _login(request)
    login.sign_out_everywhere()
    value, _ = login.token(remember=False)
    resp = JSONResponse({"ok": True})
    resp.set_cookie(COOKIE, value, httponly=True, samesite="strict")  # keep this browser signed in
    return resp
