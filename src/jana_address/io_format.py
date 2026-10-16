"""Чтение входа и запись ответа в той же форме контейнера, что пришла.

Формат контейнера организаторы пока не зафиксировали (см. docs/QUESTIONS.md, Q1), поэтому принимаем:
массив записей, объект с единственным ключом-списком (records/data/items/...), одиночную запись, JSONL.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

PREFERRED_KEYS = ("records", "data", "items", "addresses", "rows", "input", "test")


@dataclass
class Container:
    kind: str  # list | object | single | jsonl
    key: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)  # прочие ключи верхнего уровня, отдаём как были


class InputFormatError(ValueError):
    pass


def _as_record(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return item
    if isinstance(item, str):
        return {"id": None, "raw_address": item}
    return {"id": None, "raw_address": None}


def decode(data: bytes) -> str:
    """UTF-8 (с BOM или без); UTF-16 по BOM; иначе cp1251. Файл из Excel/Windows не должен ронять весь
    батч (docs/QUESTIONS.md, Q16). Ответ всегда в UTF-8."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1251")


def loads(data: bytes | str) -> tuple[list[dict[str, Any]], Container]:
    text = decode(data) if isinstance(data, bytes) else data.lstrip("\ufeff")
    stripped = text.strip()
    if not stripped:
        return [], Container("list")
    try:
        obj = json.loads(stripped)
    except json.JSONDecodeError as exc:
        lines = [ln for ln in stripped.splitlines() if ln.strip()]
        try:
            items = [json.loads(ln) for ln in lines]
        except json.JSONDecodeError:
            raise InputFormatError(f"не JSON и не JSONL: {exc}") from exc
        return [_as_record(i) for i in items], Container("jsonl")
    return from_obj(obj)


def from_obj(obj: Any) -> tuple[list[dict[str, Any]], Container]:
    if isinstance(obj, list):
        return [_as_record(i) for i in obj], Container("list")
    if isinstance(obj, dict):
        if "raw_address" in obj:
            return [obj], Container("single")
        list_keys = [k for k, v in obj.items() if isinstance(v, list)]
        key = next((k for k in PREFERRED_KEYS if k in list_keys), None)
        if key is None and len(list_keys) == 1:
            key = list_keys[0]
        if key is not None:
            extra = {k: v for k, v in obj.items() if k != key}
            return [_as_record(i) for i in obj[key]], Container("object", key=key, extra=extra)
    raise InputFormatError("ожидался массив записей {id, raw_address} или объект со списком записей")


def to_obj(results: list[dict[str, Any]], container: Container) -> Any:
    if container.kind == "object" and container.key:
        out = dict(container.extra)
        out[container.key] = results
        return out
    if container.kind == "single":
        return results[0] if results else {}
    return results


def dumps(results: list[dict[str, Any]], container: Container, indent: int | None = None) -> str:
    if container.kind == "jsonl":
        return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in results)
    return json.dumps(to_obj(results, container), ensure_ascii=False, indent=indent)
