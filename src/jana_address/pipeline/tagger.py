"""Шаг tagger: посимвольная разметка raw моделью (src/jana_address/tagger). Поля не трогает, это делает arbiter.

Батч жюри размечается одним вызовом заранее (Pipeline.run_many -> predict_many), здесь только забираем готовое;
для одной строки (UI, /parse) шаг вызывает модель сам. Нет модели или она упала: state.model = None,
дальше всё работает на правилах, как без теггера.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Sequence
from typing import Any

from .. import config
from ..tagger.runtime import Prediction, Tagger, load
from .base import ParseState, StepTrace

log = logging.getLogger(__name__)
_lock = threading.Lock()
_tagger: Tagger | None = None
_loaded = False


def get_tagger() -> Tagger | None:
    """Модель на процесс (не кэш результатов: каждая строка размечается заново)."""
    global _tagger, _loaded
    if not _loaded:
        with _lock:
            if not _loaded:
                _tagger = load(config.TAGGER_MODEL, config.TAGGER_META)
                _loaded = True
    return _tagger


class ModelTag:
    name = "tagger"

    def __init__(self, tagger: Tagger | None, mode: str) -> None:
        self.tagger = tagger
        self.mode = mode

    def predict_many(self, raws: Sequence[str]) -> list[Prediction | None]:
        if self.tagger is None:
            return [None] * len(raws)
        try:
            return list(self.tagger.predict(raws))
        except Exception:
            log.exception("теггер упал на батче из %d строк, работаем на правилах", len(raws))
            return [None] * len(raws)

    def __call__(self, state: ParseState) -> ParseState:
        tr = StepTrace(step=self.name)
        if self.tagger is None:
            tr.notes.append("модель не загружена: только правила")
        else:
            if not state.model_tried:
                state.model = self.predict_many([state.raw])[0]
                state.model_tried = True
            if state.model is None:
                tr.notes.append("модель не дала разметку: только правила")
            else:
                tr.notes.append(
                    f"режим {self.mode}; спаны: " + "; ".join(_fmt(state, s) for s in state.model.to_json())
                )
        state.trace.append(tr)
        return state


def _fmt(state: ParseState, s: dict[str, Any]) -> str:
    return f"{s['label']} {state.raw[s['start'] : s['end']]!r} p={s['p_cal']}"


def info() -> dict[str, Any]:
    t = _tagger if _loaded else None
    return {"mode": config.tagger_mode(), "loaded": t is not None, **(t.info() if t else {})}
