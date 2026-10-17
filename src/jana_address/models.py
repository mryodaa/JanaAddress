"""Схемы входа и выхода. Порядок полей ответа фиксирован форматом жюри."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# Поля разбора в порядке выдачи (между raw_address и confidence)
PARSED_FIELDS: tuple[str, ...] = (
    "province",
    "city",
    "district",
    "living_area",
    "street_type",
    "street_name",
    "house",
    "apartment",
    "entrance",
    "floor",
    "landmark",
)
OUTPUT_KEYS: tuple[str, ...] = ("id", "raw_address", *PARSED_FIELDS, "confidence")


class InputRecord(BaseModel):
    """Запись входа. id и raw_address не валидируются по типу: возвращаем их как пришли."""

    model_config = ConfigDict(extra="allow")
    id: Any = None
    raw_address: Any = None


class OutputRecord(BaseModel):
    """Ровно схема ответа жюри."""

    model_config = ConfigDict(extra="forbid")
    id: Any
    raw_address: Any
    province: str | None = None
    city: str | None = None
    district: str | None = None
    living_area: str | None = None
    street_type: str | None = None
    street_name: str | None = None
    house: str | None = None
    apartment: str | None = None
    entrance: str | None = None
    floor: str | None = None
    landmark: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)


class FieldExplain(BaseModel):
    value: str | None
    source: str | None = Field(
        description="string | reference:osm:<house|street|polygon|point|poi> | reference:<seed|kato> | manual"
    )
    span: tuple[int, int] | None = Field(default=None, description="[start, end) в символах ОРИГИНАЛЬНОЙ raw_address")


class StepTraceOut(BaseModel):
    step: str
    ms: float
    changes: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class ExplainRecord(OutputRecord):
    model_config = ConfigDict(extra="forbid")
    fields: dict[str, FieldExplain] = Field(default_factory=dict)
    trace: list[StepTraceOut] = Field(default_factory=list)
    unparsed: list[str] = Field(default_factory=list, description="куски строки, не ушедшие ни в одно поле")
    model: dict[str, Any] | None = Field(
        default=None, description="разметка теггера (спаны в raw, p) и решения арбитра по полям; нет модели: null"
    )


class ParseOneRequest(BaseModel):
    raw_address: str
    id: Any = None


class ReferenceInfo(BaseModel):
    file: str | None = None
    counts: dict[str, int] = Field(default_factory=dict, description="записей справочника по типам")
    houses: int | None = None
    built_at: str | None = None
    sources: list[str] = Field(default_factory=list)


class TaggerInfo(BaseModel):
    mode: str = Field(description="off | shadow | on | only")
    loaded: bool
    version: str | None = None
    max_len: int | None = None
    warmup_ms: float | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)


class HealthOut(BaseModel):
    status: str = Field(description="ok | loading (503, пока грузятся справочник и модель)")
    version: str
    load_seconds: float | None = None
    reference: ReferenceInfo | None = None
    tagger: TaggerInfo | None = None


class ConfigOut(BaseModel):
    uncertain_threshold: float
