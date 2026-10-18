"""Защита API при интеграции (docs/SECURITY.md): ключ доступа, проверка Origin и Host, заголовки ответа.

По умолчанию всё, что может помешать вызову батча, выключено: ключа нет, Host любой. Включается переменными
окружения JANA_API_KEY и JANA_ALLOWED_HOSTS. Проверка Origin включена всегда: её проходит любой клиент,
кроме браузера на чужом сайте (сервисы и curl Origin не шлют).
"""

from __future__ import annotations

import hashlib
import hmac
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

COOKIE = "jana_auth"
COOKIE_DAYS = 30
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# без ключа: проверка живости (healthcheck докера) и сам вход
OPEN_PATHS = frozenset({"/api/v1/health", "/api/v1/auth"})
HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}


@dataclass(frozen=True)
class Settings:
    api_key: str | None
    allowed_hosts: tuple[str, ...]  # пусто: любой Host
    allowed_origins: frozenset[str]  # чужие сайты, которым можно менять данные (интеграция из браузера)

    @property
    def cookie_token(self) -> str:
        # в cookie не сам ключ, а производный от него токен: утечка cookie не раскрывает ключ для API
        assert self.api_key is not None
        return hmac.new(self.api_key.encode(), b"jana-ui-cookie", hashlib.sha256).hexdigest()


def _list(env: str) -> list[str]:
    return [x.strip().lower() for x in os.environ.get(env, "").split(",") if x.strip()]


def load_settings() -> Settings:
    key = os.environ.get("JANA_API_KEY", "").strip() or None
    return Settings(key, tuple(_list("JANA_ALLOWED_HOSTS")), frozenset(_list("JANA_ALLOWED_ORIGINS")))


def _hostname(host: str) -> str:
    host = host.strip().lower()
    if host.startswith("["):  # IPv6: [::1]:8000
        return host[: host.find("]") + 1] if "]" in host else host
    return host.rsplit(":", 1)[0] if ":" in host else host


def host_allowed(host: str, patterns: tuple[str, ...]) -> bool:
    """Host против списка: точное имя или *.домен. Защита от DNS rebinding: чужое имя, указывающее на 127.0.0.1."""
    if not patterns:
        return True
    name = _hostname(host)
    return any(name == p or (p.startswith("*.") and name.endswith(p[1:])) for p in patterns)


def origin_allowed(origin: str, host: str, allowed: frozenset[str]) -> bool:
    """Запрос на изменение из браузера: Origin совпадает с адресом самого сервиса или явно разрешён."""
    o = origin.strip().lower()
    if o in allowed:
        return True
    if o == "null":  # file://, песочница: свой интерфейс так не ходит
        return False
    return urlsplit(o).netloc == host.strip().lower()


def _supplied_key(request: Request) -> str | None:
    if key := request.headers.get("x-api-key"):
        return key
    auth = request.headers.get("authorization", "")
    return auth[7:].strip() if auth.lower().startswith("bearer ") else None


def authorized(request: Request, s: Settings) -> bool:
    if s.api_key is None:
        return True
    key = _supplied_key(request)
    if key is not None and hmac.compare_digest(key.encode(), s.api_key.encode()):
        return True
    cookie = request.cookies.get(COOKIE)
    return cookie is not None and hmac.compare_digest(cookie.encode(), s.cookie_token.encode())


def install(app: FastAPI, s: Settings) -> None:
    app.state.security = s

    @app.middleware("http")
    async def guard(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        host = request.headers.get("host", "")
        path = request.url.path
        if not host_allowed(host, s.allowed_hosts):
            resp: Response = JSONResponse({"detail": "недопустимый Host"}, status_code=400)
        elif (
            request.method not in SAFE_METHODS
            and (origin := request.headers.get("origin")) is not None
            and not origin_allowed(origin, host, s.allowed_origins)
        ):
            # чужой сайт в браузере оператора: CORS не даёт прочитать ответ, но запрос бы выполнился
            resp = JSONResponse({"detail": "запрос с чужого сайта отклонён"}, status_code=403)
        elif path.startswith("/api/") and path not in OPEN_PATHS and not authorized(request, s):
            resp = JSONResponse(
                {"detail": "передайте ключ в заголовке X-API-Key или Authorization: Bearer"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        else:
            resp = await call_next(request)
        for k, v in HEADERS.items():
            resp.headers.setdefault(k, v)
        return resp

    app.include_router(router)


router = APIRouter(prefix="/api/v1", tags=["service"])


class AuthIn(BaseModel):
    key: str


class AuthOut(BaseModel):
    required: bool
    ok: bool


@router.get("/auth", summary="Нужен ли ключ и принят ли он (для UI)", response_model=AuthOut)
def auth_status(request: Request) -> dict[str, Any]:
    s: Settings = request.app.state.security
    return {"required": s.api_key is not None, "ok": authorized(request, s)}


@router.post(
    "/auth",
    summary="Вход в UI по ключу: ставит cookie (HttpOnly, SameSite=Strict)",
    response_model=AuthOut,
    responses={401: {"description": "неверный ключ"}},
)
def auth_login(body: AuthIn, request: Request, response: Response) -> dict[str, Any]:
    s: Settings = request.app.state.security
    if s.api_key is None:
        return {"required": False, "ok": True}
    if not hmac.compare_digest(body.key.strip().encode(), s.api_key.encode()):
        raise HTTPException(401, "неверный ключ")
    # за туннелем или прокси сервис видит http, а браузер https: Secure по заголовку прокси
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").lower() == "https"
    response.set_cookie(
        COOKIE,
        s.cookie_token,
        max_age=COOKIE_DAYS * 86400,
        httponly=True,
        samesite="strict",
        secure=secure,
        path="/",
    )
    return {"required": True, "ok": True}


@router.delete("/auth", summary="Выйти из UI: удалить cookie", response_model=AuthOut)
def auth_logout(request: Request, response: Response) -> dict[str, Any]:
    s: Settings = request.app.state.security
    response.delete_cookie(COOKIE, path="/")
    return {"required": s.api_key is not None, "ok": s.api_key is None}
