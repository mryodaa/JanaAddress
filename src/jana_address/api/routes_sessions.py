"""Эндпоинты UI: пакет -> сессия, список с фильтрами, ручная правка, экспорт в формате sample_output.json."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from .. import config, sessions
from ..models import FieldExplain, OutputRecord, StepTraceOut
from .routes_parse import parse_payload, read_payload

router = APIRouter(prefix="/api/v1", tags=["sessions"])


class SessionCreated(BaseModel):
    id: str
    total: int


class Summary(BaseModel):
    threshold: float
    uncertain: int
    reviewed: int
    mean_confidence: float | None
    histogram: list[int] = Field(description="10 корзин confidence: [0-0.1), ..., [0.9-1.0]")
    fill: dict[str, int] = Field(description="сколько записей с непустым полем")
    sources: dict[str, int] = Field(description="string / reference / manual")


class SessionInfo(BaseModel):
    id: str
    name: str | None
    created_at: float
    status: str = Field(description="processing | done | error")
    total: int
    processed: int
    seconds: float | None = None
    error: str | None = None
    summary: Summary


class SessionBrief(BaseModel):
    id: str
    name: str | None
    created_at: float
    status: str
    total: int
    processed: int


class RecordItem(BaseModel):
    idx: int
    record: OutputRecord
    fields: dict[str, FieldExplain]
    edited: list[str]
    reviewed: bool
    unparsed: list[str]
    pending: bool
    trace: list[StepTraceOut] | None = None
    parsed: dict[str, Any] | None = None


class RecordList(BaseModel):
    total: int
    items: list[RecordItem]


class RecordPatch(BaseModel):
    fields: dict[str, str | None] = Field(default_factory=dict, description="поле -> значение (null = очистить)")
    reviewed: bool | None = None


@router.get("/config", summary="Параметры UI (порог неуверенности)")
def get_config() -> dict[str, Any]:
    return {"uncertain_threshold": config.UNCERTAIN_THRESHOLD}


@router.post("/sessions", summary="Загрузить пакет (JSON-тело или файл) и начать разбор", response_model=SessionCreated)
async def create_session(request: Request, name: str = Query("upload.json")) -> SessionCreated:
    records, container = parse_payload(await read_payload(request))
    if not records:
        raise HTTPException(422, "в файле нет записей")
    sid = sessions.create(records, container, name)
    return SessionCreated(id=sid, total=len(records))


@router.get("/sessions", summary="Список сессий", response_model=list[SessionBrief])
def list_sessions() -> list[dict[str, Any]]:
    return sessions.list_sessions()


@router.get(
    "/sessions/{sid}",
    summary="Прогресс и сводка: распределение confidence, неуверенные, заполненность",
    response_model=SessionInfo,
)
def get_session(sid: str) -> dict[str, Any]:
    s = sessions.get_session(sid)
    if s is None:
        raise HTTPException(404, "сессия не найдена")
    return s


@router.get("/sessions/{sid}/records", summary="Записи с фильтрами", response_model=RecordList)
def list_records(
    sid: str,
    uncertain: bool = False,
    reviewed: bool | None = None,
    q: str = "",
    offset: int = Query(0, ge=0),
    limit: int = Query(20000, ge=1, le=100000),
) -> dict[str, Any]:
    return sessions.list_records(sid, uncertain, reviewed, q, offset, limit)


@router.get("/sessions/{sid}/records/{idx}", summary="Запись целиком, с trace по шагам", response_model=RecordItem)
def get_record(sid: str, idx: int) -> dict[str, Any]:
    r = sessions.get_record(sid, idx)
    if r is None:
        raise HTTPException(404, "запись не найдена")
    return r


@router.patch(
    "/sessions/{sid}/records/{idx}", summary="Ручная правка полей, отметка «проверено»", response_model=RecordItem
)
def patch_record(sid: str, idx: int, body: RecordPatch) -> dict[str, Any]:
    r = sessions.patch_record(sid, idx, body.fields, body.reviewed)
    if r is None:
        raise HTTPException(404, "запись не найдена")
    return r


@router.get("/sessions/{sid}/export", summary="Результат с правками в формате sample_output.json")
def export(sid: str) -> Response:
    data = sessions.export(sid)
    if data is None:
        raise HTTPException(404, "сессия не найдена")
    return Response(
        data,
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="jana_address_{sid}.json"'},
    )


@router.delete("/sessions/{sid}", summary="Удалить сессию")
def delete(sid: str) -> dict[str, bool]:
    if not sessions.delete(sid):
        raise HTTPException(404, "сессия не найдена")
    return {"deleted": True}
