"""Чтение входа и запись ответа в той же форме контейнера, что пришла.

Формат контейнера организаторы пока не зафиксировали (см. docs/QUESTIONS.md, Q1), поэтому принимаем:
массив записей, объект с единственным ключом-списком (records/data/items/...), одиночную запись, JSONL.
"""

from __future__ import annotations

import json
import re
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


class RawFloat(float):
    """Дробное число из входа вместе с исходной записью: id вида 1e3 или 1.50 возвращается байт в байт,
    а не как 1000.0 / 1.5 (json пишет float через repr)."""

    text: str

    def __new__(cls, text: str) -> RawFloat:
        obj = super().__new__(cls, text)
        obj.text = text
        return obj


def parse_value(s: str) -> Any:
    return json.loads(s, parse_float=RawFloat)


_parse = parse_value


def loads(data: bytes | str) -> tuple[list[dict[str, Any]], Container]:
    text = decode(data) if isinstance(data, bytes) else data.lstrip("\ufeff")
    stripped = text.strip()
    if not stripped:
        return [], Container("list")
    try:
        obj = _parse(stripped)
    except json.JSONDecodeError as exc:
        lines = [ln for ln in stripped.splitlines() if ln.strip()]
        try:
            items = [_parse(ln) for ln in lines]
        except ValueError:
            raise InputFormatError(f"не JSON и не JSONL: {exc}") from exc
        return [_as_record(i) for i in items], Container("jsonl")
    except ValueError as exc:
        # синтаксис верный, значение нет: целое длиннее 4300 цифр (лимит Python) — ошибка входа, а не сервера
        raise InputFormatError(f"недопустимое значение: {exc}") from exc
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


_LONE_SURROGATE = re.compile("[\ud800-\udfff]")


_RAW_MARK = "\ue000raw:"  # символ из частной области: в адресах его нет, json пишет его как есть


def _mark_raw(obj: Any, raws: list[str]) -> Any:
    """RawFloat -> строка-метка с номером; после json.dumps метка заменяется исходной записью числа."""
    if isinstance(obj, RawFloat):
        raws.append(obj.text)
        return f"{_RAW_MARK}{len(raws) - 1}\ue000"
    if isinstance(obj, dict):
        return {k: _mark_raw(v, raws) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_mark_raw(v, raws) for v in obj]
    return obj


def dump_value(obj: Any, indent: int | None = None) -> str:
    """Кириллица как есть. Одиночный суррогат (json.loads его пропускает) в UTF-8 не кодируется и уронил бы
    весь ответ; в JSON-тексте он бывает только внутри строки, поэтому пишем его escape-последовательностью:
    значение то же, остальные записи не трогаем. Дробные числа входа пишутся так, как пришли."""
    raws: list[str] = []
    text = json.dumps(_mark_raw(obj, raws), ensure_ascii=False, indent=indent)
    if raws:
        text = re.sub(
            f'"{_RAW_MARK}(\\d+)\ue000"',
            lambda m: raws[int(m.group(1))] if int(m.group(1)) < len(raws) else m.group(),
            text,
        )
    return _LONE_SURROGATE.sub(lambda m: f"\\u{ord(m.group()):04x}", text)


_dump = dump_value


def dumps(results: list[dict[str, Any]], container: Container, indent: int | None = None) -> str:
    if container.kind == "jsonl":
        return "".join(_dump(r) + "\n" for r in results)
    return _dump(to_obj(results, container), indent)
