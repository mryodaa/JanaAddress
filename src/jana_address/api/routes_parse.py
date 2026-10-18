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
        "description": (
            "Тело в формате sample_input.json (application/json) или файл (multipart/form-data, поле file). "
            'Принимается и объект со списком записей ({"records": [...]}), одиночная запись, JSONL: '
            "ответ возвращается в той же форме контейнера"
        ),
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


# загрузка пакета в UI: то же тело, что у батча
UPLOAD_BODY_DOC = _BATCH_BODY_DOC

_ERRORS: dict[int | str, dict[str, Any]] = {
    413: {"description": "тело больше лимита JANA_MAX_UPLOAD_MB"},
    422: {"description": "не JSON/JSONL или нет записей"},
}


# запас на заголовки и границы multipart поверх самого файла
MULTIPART_SLACK = 64 * 1024


async def read_payload(request: Request) -> bytes:
    """JSON-тело или первый файл из multipart, как есть, без перекодирования. Лимит проверяется до чтения
    (Content-Length) и по ходу чтения: тело больше лимита не попадает в память целиком."""
    limit = config.MAX_UPLOAD_MB * 1024 * 1024
    too_big = HTTPException(413, f"файл больше {config.MAX_UPLOAD_MB} МБ")
    length = request.headers.get("content-length", "")
    if length.isdigit() and int(length) > limit + MULTIPART_SLACK:
        raise too_big
    ctype = request.headers.get("content-type", "").lower()
    if ctype.startswith("multipart/form-data"):
        form = await request.form()
        upload = form.get("file") or next((v for v in form.values() if hasattr(v, "read")), None)
        if upload is None or not hasattr(upload, "read"):
            raise HTTPException(400, "в multipart нет файла (ожидается поле file)")
        data: bytes = await upload.read()
    else:
        chunks: list[bytes] = []
        size = 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > limit:
                raise too_big
            chunks.append(chunk)
        data = b"".join(chunks)
    if len(data) > limit:
        raise too_big
    return data


def parse_payload(data: bytes) -> tuple[list[dict[str, Any]], io_format.Container]:
    try:
        return io_format.loads(data)
    except (io_format.InputFormatError, UnicodeDecodeError) as exc:
        raise HTTPException(422, f"неверный формат входа: {exc}") from exc
    except RecursionError:
        # json.loads падает на сверхглубокой вложенности: это ошибка входа, а не сервера
        raise HTTPException(422, "неверный формат входа: слишком глубокая вложенность JSON") from None


@router.post(
    "/parse/batch",
    summary="Разбор пакета в формате sample_input.json -> sample_output.json",
    response_model=list[OutputRecord],
    openapi_extra=_BATCH_BODY_DOC,
    responses={
        200: {
            "description": "Ответ в той же форме контейнера, что вход; для JSONL application/x-ndjson",
            "content": {"application/x-ndjson": {"schema": {"type": "string"}}},
        },
        **_ERRORS,
    },
)
async def parse_batch(
    request: Request, explain: bool = Query(False, description="добавить источники полей и trace")
) -> Response:
    records, container = parse_payload(await read_payload(request))
    results = await asyncio.to_thread(engine.parse_many, records, explain)
    media = "application/x-ndjson" if container.kind == "jsonl" else "application/json"
    return Response(io_format.dumps(results, container), media_type=f"{media}; charset=utf-8")


@router.post("/parse", summary="Разбор одной строки", response_model=ExplainRecord)
async def parse_one(
    body: ParseOneRequest, explain: bool = Query(True, description="источники полей и trace по шагам")
) -> dict[str, Any]:
    return await asyncio.to_thread(engine.parse_one, body.model_dump(), explain)
