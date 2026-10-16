"""FastAPI-приложение: API + статика UI."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__, config, engine
from ..models import InputRecord
from . import routes_parse

log = logging.getLogger("jana_address")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # справочник и словари грузим до приёма запросов; health отдаёт 503, пока не готово
    await asyncio.to_thread(engine.get_pipeline)
    log.info("pipeline ready: %s", engine.info())
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Jana Address API",
        version=__version__,
        description="Разбор адресов Казахстана на поля с восстановлением по собственному справочнику.",
        lifespan=lifespan,
    )
    app.include_router(routes_parse.router)
    try:
        from . import routes_sessions

        app.include_router(routes_sessions.router)
    except ImportError:  # pragma: no cover - модуль сессий появляется на шаге UI
        pass

    @app.get("/api/v1/health", tags=["service"], summary="Готовность: справочник и словари загружены")
    def health() -> JSONResponse:
        ready = engine.is_ready()
        body: dict[str, Any] = {"status": "ok" if ready else "loading", "version": __version__}
        body.update(engine.info())
        return JSONResponse(body, status_code=200 if ready else 503)

    # схема InputRecord нужна в OpenAPI для батча, который читает тело вручную
    original_openapi = app.openapi

    def openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = original_openapi()
        schema.setdefault("components", {}).setdefault("schemas", {})["InputRecord"] = InputRecord.model_json_schema()
        app.openapi_schema = schema
        return schema

    app.openapi = openapi  # type: ignore[method-assign]

    index = config.STATIC_DIR / "index.html"
    if index.exists():
        assets = config.STATIC_DIR / "assets"
        if assets.exists():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            candidate = (config.STATIC_DIR / path).resolve()
            if path and candidate.is_file() and config.STATIC_DIR.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(index)

    return app


app = create_app()
