"""Единственный экземпляр пайплайна на процесс (справочник грузится один раз)."""

from __future__ import annotations

import threading
import time
from typing import Any

from .pipeline.runner import Pipeline, parse_record, parse_records

_lock = threading.Lock()
_pipeline: Pipeline | None = None
_info: dict[str, Any] = {}


def get_pipeline() -> Pipeline:
    global _pipeline
    if _pipeline is None:
        with _lock:
            if _pipeline is None:
                t0 = time.perf_counter()
                _pipeline = Pipeline()
                _info["load_seconds"] = round(time.perf_counter() - t0, 3)
                from .reference import store

                _info["reference"] = store.get_store().stats() if store.is_available() else None
                from .pipeline import tagger

                _info["tagger"] = tagger.info()
    return _pipeline


def reset() -> None:
    """Пересобрать пайплайн при следующем вызове (CLI/тесты меняют JANA_TAGGER)."""
    global _pipeline
    with _lock:
        _pipeline = None
        _info.clear()


def is_ready() -> bool:
    return _pipeline is not None


def info() -> dict[str, Any]:
    return dict(_info)


def parse_many(records: list[dict[str, Any]], explain: bool = False) -> list[dict[str, Any]]:
    return parse_records(get_pipeline(), records, explain)


def parse_one(rec: dict[str, Any], explain: bool = True) -> dict[str, Any]:
    return parse_record(get_pipeline(), rec, explain)
