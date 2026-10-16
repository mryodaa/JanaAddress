"""Разбор: батч (основной путь жюри) и одна строка."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, Response

from .. import config, engine, io_format
from ..models import ExplainRecord, OutputRecord, ParseOneRequest

router = APIRouter(prefix="/api/v1", tags=["parse"])

_BATCH_BODY_DOC: dict[str, Any] = {
    "requestBody": {
        "required": True,
        "description": "Тело в формате sample_input.json (application/json) или файл (multipart/form-data, поле file)",
        "content": {
            "application/json": {
                "schema": {"type": "array", "items": {"$ref": "#/components/schemas/InputRecord"}},
                "example": [{"id": "rec_00417", "raw_address": "город Алматы/Алматы қаласы, Мкр Аксай 3а, 59, кв 70"}],
            },
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "properties": {"file": {"type": "string", "format": "binary"}},
                    "required": ["file"],
                }
            },
        },
    }
}


async def read_payload(request: Request) -> bytes:
    """JSON-тело или первый файл из multipart, как есть, без перекодирования."""
    ctype = request.headers.get("content-type", "")
    if ctype.startswith("multipart/form-data"):
        form = await request.form()
        upload = form.get("file") or next((v for v in form.values() if hasattr(v, "read")), None)
        if upload is None or not hasattr(upload, "read"):
            raise HTTPException(400, "в multipart нет файла (ожидается поле file)")
        data: bytes = await upload.read()
    else:
        data = await request.body()
    if len(data) > config.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"файл больше {config.MAX_UPLOAD_MB} МБ")
    return data


def parse_payload(data: bytes) -> tuple[list[dict[str, Any]], io_format.Container]:
    try:
        return io_format.loads(data)
    except (io_format.InputFormatError, UnicodeDecodeError) as exc:
        raise HTTPException(422, f"неверный формат входа: {exc}") from exc


@router.post(
    "/parse/batch",
    summary="Разбор пакета в формате sample_input.json -> sample_output.json",
    response_model=list[OutputRecord],
    openapi_extra=_BATCH_BODY_DOC,
)
async def parse_batch(
    request: Request, explain: bool = Query(False, description="добавить источники полей и trace")
) -> Response:
    records, container = parse_payload(await read_payload(request))
    results = await asyncio.to_thread(engine.parse_many, records, explain)
    return Response(io_format.dumps(results, container), media_type="application/json; charset=utf-8")


@router.post("/parse", summary="Разбор одной строки", response_model=ExplainRecord)
async def parse_one(
    body: ParseOneRequest, explain: bool = Query(True, description="источники полей и trace по шагам")
) -> dict[str, Any]:
    return await asyncio.to_thread(engine.parse_one, body.model_dump(), explain)
