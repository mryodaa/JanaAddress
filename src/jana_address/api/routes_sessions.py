"""Эндпоинты UI: пакет -> сессия, список с фильтрами, ручная правка, экспорт в формате sample_output.json."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from .. import config, sessions
from ..models import PARSED_FIELDS, ConfigOut, FieldExplain, OutputRecord, StepTraceOut
from .routes_parse import UPLOAD_BODY_DOC, parse_payload, read_payload

router = APIRouter(prefix="/api/v1", tags=["sessions"])


class SessionCreated(BaseModel):
    id: str
    total: int


class Summary(BaseModel):
    threshold: float = Field(description="порог этой сессии: сохраняется при загрузке, у старых сессий 0.6")
    uncertain: int
    confident: int = Field(description="записей с confidence не ниже порога")
    reviewed: int
    edited: int = Field(description="записей, где оператор исправил хотя бы одно поле")
    to_review: int = Field(description="очередь проверки: неуверенные, не проверенные, не исправленные, не отложенные")
    skipped: int = Field(0, description="отложенных оператором")
    review_total: int = Field(0, description="записей, неуверенных по оценке разбора (вся очередь проверки)")
    review_done: int = Field(0, description="из них уже подтверждено или исправлено")
    mean_confidence: float | None
    histogram: list[int] = Field(description="10 корзин confidence: [0-0.1), ..., [0.9-1.0]")
    histogram_uncertain: list[int] = Field(description="сколько в каждой корзине ниже порога")
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
    skipped: bool = False
    unparsed: list[str]
    pending: bool
    trace: list[StepTraceOut] | None = None
    parsed: dict[str, Any] | None = None


class RecordList(BaseModel):
    total: int = Field(description="записей с этими фильтрами всего (страница может быть короче)")
    offset: int = 0
    items: list[RecordItem]


class RecordPosition(BaseModel):
    position: int | None = Field(description="место записи в списке с этими фильтрами и порядком; null: её там нет")


class RecordPatch(BaseModel):
    fields: dict[str, str | None] = Field(default_factory=dict, description="поле -> значение (null = очистить)")
    reviewed: bool | None = None
    skipped: bool | None = Field(None, description="true: отложить (вне очереди неуверенных), false: вернуть")


@router.get("/config", summary="Параметры UI (порог неуверенности)", response_model=ConfigOut)
def get_config() -> dict[str, Any]:
    return {"uncertain_threshold": config.UNCERTAIN_THRESHOLD}


@router.post(
    "/sessions",
    summary="Загрузить пакет (JSON-тело или файл) и начать разбор",
    response_model=SessionCreated,
    openapi_extra=UPLOAD_BODY_DOC,
    responses={413: {"description": "файл больше лимита"}, 422: {"description": "неверный формат или нет записей"}},
)
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
    responses={404: {"description": "сессия не найдена"}},
)
def get_session(sid: str) -> dict[str, Any]:
    s = sessions.get_session(sid)
    if s is None:
        raise HTTPException(404, "сессия не найдена")
    return s


SortParam = Literal["idx", "confidence", "raw", "added"]
BUCKET_QUERY = Query(
    None, ge=0, le=9, description="столбец гистограммы сводки: уверенность [b/10, (b+1)/10), у 9 включая 1.0"
)
DirParam = Literal["asc", "desc"]


def _require(sid: str) -> None:
    if not sessions.session_exists(sid):
        raise HTTPException(404, "сессия не найдена")


@router.get(
    "/sessions/{sid}/records",
    summary="Записи с фильтрами, страницами, в заданном порядке",
    response_model=RecordList,
    responses={404: {"description": "сессия не найдена"}},
)
def list_records(
    sid: str,
    uncertain: bool = False,
    reviewed: bool | None = None,
    edited: bool | None = None,
    q: str = Query("", description="подстрока исходной строки или значения поля, без учёта регистра"),
    sort: SortParam = "idx",
    dir: DirParam = "asc",
    bucket: int | None = BUCKET_QUERY,
    skipped: bool | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(500, ge=1, le=sessions.PAGE_MAX),
) -> dict[str, Any]:
    _require(sid)
    return sessions.list_records(sid, uncertain, reviewed, q, offset, limit, edited, sort, dir, bucket, skipped)


@router.get(
    "/sessions/{sid}/records/position",
    summary="Место записи в списке с этими фильтрами и порядком",
    response_model=RecordPosition,
    responses={404: {"description": "сессия не найдена"}},
)
def record_position(
    sid: str,
    idx: int,
    uncertain: bool = False,
    reviewed: bool | None = None,
    edited: bool | None = None,
    q: str = "",
    sort: SortParam = "idx",
    dir: DirParam = "asc",
    bucket: int | None = BUCKET_QUERY,
    skipped: bool | None = None,
) -> dict[str, Any]:
    _require(sid)
    return {"position": sessions.record_position(sid, idx, uncertain, reviewed, q, edited, sort, dir, bucket, skipped)}


@router.get(
    "/sessions/{sid}/records/{idx}",
    summary="Запись целиком, с trace по шагам",
    response_model=RecordItem,
    responses={404: {"description": "запись не найдена"}},
)
def get_record(sid: str, idx: int) -> dict[str, Any]:
    r = sessions.get_record(sid, idx)
    if r is None:
        raise HTTPException(404, "запись не найдена")
    return r


@router.patch(
    "/sessions/{sid}/records/{idx}",
    summary="Ручная правка полей, отметка «проверено»",
    response_model=RecordItem,
    responses={404: {"description": "запись не найдена"}, 422: {"description": "неизвестное поле"}},
)
def patch_record(sid: str, idx: int, body: RecordPatch) -> dict[str, Any]:
    unknown = sorted(set(body.fields) - set(PARSED_FIELDS))
    if unknown:
        raise HTTPException(422, f"неизвестные поля: {', '.join(unknown)}")
    r = sessions.patch_record(sid, idx, body.fields, body.reviewed, body.skipped)
    if r is None:
        raise HTTPException(404, "запись не найдена")
    return r


ExportFormat = Literal["json", "csv"]


@router.get(
    "/sessions/{sid}/export",
    summary="Результат с правками: весь пакет (sample_output.json) или отфильтрованный список, JSON или CSV",
    description=(
        "Без параметров: весь пакет в форме входа, все поля, как ответ батча. Фильтры те же, что у списка записей "
        "(uncertain, reviewed, edited, q, bucket) и порядок (sort, dir). fields: поля через запятую "
        "(id и raw_address всегда), sources: источник каждого непустого поля."
    ),
    response_class=Response,
    responses={
        200: {
            "content": {
                "application/json": {
                    "schema": {"type": "array", "items": {"$ref": "#/components/schemas/OutputRecord"}}
                },
                "text/csv": {"schema": {"type": "string"}},
            }
        },
        404: {"description": "сессия не найдена"},
        409: {"description": "пакет ещё разбирается"},
        422: {"description": "неизвестное поле в fields"},
    },
)
def export(
    sid: str,
    uncertain: bool = False,
    reviewed: bool | None = None,
    edited: bool | None = None,
    q: str = "",
    bucket: int | None = BUCKET_QUERY,
    skipped: bool | None = None,
    sort: SortParam = "idx",
    dir: DirParam = "asc",
    fields: str | None = Query(None, description="province,city,... (id и raw_address всегда); пусто = все"),
    format: ExportFormat = "json",
    sources: bool = Query(False, description="добавить источник поля: _sources в JSON, колонки *_source в CSV"),
) -> Response:
    chosen: list[str] | None = None
    if fields is not None:
        chosen = [f for f in (x.strip() for x in fields.split(",")) if f]
        unknown = sorted(set(chosen) - set(sessions.EXPORT_KEYS))
        if unknown:
            raise HTTPException(422, f"неизвестные поля: {', '.join(unknown)}")
        chosen = [k for k in sessions.EXPORT_KEYS if k in chosen]  # порядок как в ответе жюри
    opts = sessions.ExportOptions(
        uncertain=uncertain,
        reviewed=reviewed,
        edited=edited,
        q=q,
        bucket=bucket,
        skipped=skipped,
        sort=sort,
        direction=dir,
        fields=chosen,
        fmt=format,
        sources=sources,
    )
    try:
        data = sessions.export(sid, opts)
    except sessions.NotReady:
        raise HTTPException(409, "пакет ещё разбирается: экспорт будет доступен после разбора") from None
    if data is None:
        raise HTTPException(404, "сессия не найдена")
    suffix = "_filtered" if opts.filtered or chosen is not None else ""
    media = "text/csv" if format == "csv" else "application/json"
    return Response(
        data,
        media_type=f"{media}; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="jana_address_{sid}{suffix}.{format}"'},
    )


@router.delete("/sessions/{sid}", summary="Удалить сессию", responses={404: {"description": "сессия не найдена"}})
def delete(sid: str) -> dict[str, bool]:
    if not sessions.delete(sid):
        raise HTTPException(404, "сессия не найдена")
    return {"deleted": True}
