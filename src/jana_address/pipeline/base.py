"""Общие структуры пайплайна.

Каждый шаг это объект с `name` и `__call__(state) -> state`, который пишет свои изменения в
`state.trace`. Шаги не знают друг о друге: общаются только через ParseState.
Все спаны (start, end) у токенов заданы в координатах ОЧИЩЕННОЙ строки `state.text`,
перевод в координаты оригинала через `state.orig_span`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from ..models import PARSED_FIELDS

SOURCE_STRING = "string"


@dataclass
class Token:
    text: str  # как в очищенной строке
    norm: str  # для сравнения со словарями: нижний регистр, ё->е, без точек
    start: int  # [start, end) в state.text
    end: int
    kind: str  # word | num | sep | punct
    used_by: str | None = None  # поле или служебная метка (marker:*, admin, kz_dup, ...)
    glued_left: bool = False  # нет пробела между этим токеном и предыдущим
    tags: set[str] = field(default_factory=set)

    @property
    def free(self) -> bool:
        return self.used_by is None


@dataclass
class FieldValue:
    value: str
    source: str = SOURCE_STRING
    span: tuple[int, int] | None = None  # в координатах оригинала
    score: float = 1.0  # уверенность в этом конкретном поле


@dataclass
class StepTrace:
    step: str
    ms: float = 0.0
    changes: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


@dataclass
class ParseState:
    raw: str
    text: str = ""
    offsets: list[int] = field(default_factory=list)  # offsets[i] = индекс в raw для text[i]; len = len(text)+1
    tokens: list[Token] = field(default_factory=list)
    fields: dict[str, FieldValue] = field(default_factory=dict)
    flags: set[str] = field(default_factory=set)  # конфликты/предупреждения для confidence
    ref_ids: dict[str, Any] = field(default_factory=dict)  # id сущностей справочника, найденных по ходу
    confidence: float = 0.0
    trace: list[StepTrace] = field(default_factory=list)

    # --- координаты ---
    def orig_span(self, start: int, end: int) -> tuple[int, int]:
        """[start, end) в text -> [s, e) в raw."""
        if not self.offsets or start >= end:
            return (0, 0)
        return (self.offsets[start], self.offsets[end - 1] + 1)

    def orig_slice(self, start: int, end: int) -> str:
        s, e = self.orig_span(start, end)
        return self.raw[s:e]

    # --- поля ---
    def get(self, name: str) -> str | None:
        fv = self.fields.get(name)
        return fv.value if fv else None

    def has(self, name: str) -> bool:
        return name in self.fields

    def set_field(
        self,
        name: str,
        value: str | None,
        *,
        source: str = SOURCE_STRING,
        span: tuple[int, int] | None = None,
        score: float = 1.0,
        overwrite: bool = False,
    ) -> bool:
        assert name in PARSED_FIELDS, name
        if value is None or not value.strip():
            return False
        if name in self.fields and not overwrite:
            return False
        # строковое значение никогда не перезаписывается справочным
        if name in self.fields and self.fields[name].source == SOURCE_STRING and source != SOURCE_STRING:
            return False
        self.fields[name] = FieldValue(value=value, source=source, span=span, score=score)
        return True

    def free_tokens(self) -> list[Token]:
        return [t for t in self.tokens if t.free and t.kind in ("word", "num")]


class Step(Protocol):
    name: str

    def __call__(self, state: ParseState) -> ParseState: ...
