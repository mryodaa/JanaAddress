"""Сборка пайплайна и безопасный разбор записи.

Гарантии: на каждую запись ровно один ответ, id и raw_address как пришли, любое исключение
превращается в объект со всеми null и низким confidence.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable, Sequence
from typing import Any

from ..models import PARSED_FIELDS
from .base import ParseState, Step, StepTrace

log = logging.getLogger(__name__)

FAIL_CONFIDENCE = 0.0
EMPTY_CONFIDENCE = 0.0


def default_steps(tagger_mode: str | None = None) -> list[Step]:
    """Порядок шагов. Импорт внутри, чтобы справочник грузился лениво."""
    from . import steps

    return steps.build_default(tagger_mode)


class Pipeline:
    def __init__(self, steps: Sequence[Step] | None = None, tagger_mode: str | None = None) -> None:
        self.steps: list[Step] = list(steps) if steps is not None else default_steps(tagger_mode)

    def predict_models(self, raws: Sequence[str | None]) -> list[Any]:
        """Разметка теггером всего батча одним вызовом (батчи по длине). Любой сбой: None, то есть правила."""
        out: list[Any] = [None] * len(raws)
        step = next((s for s in self.steps if hasattr(s, "predict_many")), None)
        if step is None:
            return out
        idx = [i for i, r in enumerate(raws) if isinstance(r, str) and r.strip()]
        try:
            preds = step.predict_many([raws[i] for i in idx])
            for i, p in zip(idx, preds, strict=True):
                out[i] = p
        except Exception:
            log.exception("разметка батча теггером не удалась, работаем на правилах")
        return out

    def run(self, raw: str, model: Any = None, model_tried: bool = False) -> ParseState:
        state = ParseState(raw=raw, model=model, model_tried=model_tried)
        for step in self.steps:
            before = {k: v.value for k, v in state.fields.items()}
            t0 = time.perf_counter()
            state = step(state)
            ms = (time.perf_counter() - t0) * 1000
            # шаг мог сам добавить trace со своими notes, дополняем его
            tr = state.trace[-1] if state.trace and state.trace[-1].step == step.name else None
            if tr is None:
                tr = StepTrace(step=step.name)
                state.trace.append(tr)
            tr.ms = round(ms, 3)
            for k, fv in state.fields.items():
                if before.get(k) != fv.value:
                    tr.changes[k] = {"value": fv.value, "source": fv.source}
        return state


def empty_result(rec: dict[str, Any], confidence: float = FAIL_CONFIDENCE) -> dict[str, Any]:
    out: dict[str, Any] = {"id": rec.get("id"), "raw_address": rec.get("raw_address")}
    for f in PARSED_FIELDS:
        out[f] = None
    out["confidence"] = confidence
    return out


def state_to_result(rec: dict[str, Any], state: ParseState) -> dict[str, Any]:
    out = empty_result(rec)
    for f in PARSED_FIELDS:
        fv = state.fields.get(f)
        out[f] = fv.value if fv and fv.value else None
    out["confidence"] = round(min(1.0, max(0.0, state.confidence)), 3)
    return out


def explain_extra(state: ParseState) -> dict[str, Any]:
    fields = {
        f: {
            "value": fv.value,
            "source": fv.source,
            "span": list(fv.span) if fv.span else None,
        }
        for f, fv in state.fields.items()
    }
    unparsed = [state.orig_slice(t.start, t.end) for t in state.tokens if t.free and t.kind in ("word", "num")]
    trace = [{"step": t.step, "ms": t.ms, "changes": t.changes, "notes": t.notes} for t in state.trace]
    out: dict[str, Any] = {"fields": fields, "trace": trace, "unparsed": unparsed}
    if state.model is not None:
        out["model"] = {"spans": state.model.to_json(), **state.arbiter}
    return out


def parse_record(
    pipeline: Pipeline, rec: dict[str, Any], explain: bool = False, model: Any = None, model_tried: bool = False
) -> dict[str, Any]:
    raw = rec.get("raw_address")
    if not isinstance(raw, str) or not raw.strip():
        out = empty_result(rec, EMPTY_CONFIDENCE)
        if explain:
            out.update({"fields": {}, "trace": [], "unparsed": []})
        return out
    try:
        state = pipeline.run(raw, model, model_tried)
        out = state_to_result(rec, state)
        if explain:
            out.update(explain_extra(state))
        return out
    except Exception as exc:  # одна плохая запись не должна ронять батч
        log.exception("parse failed for id=%r", rec.get("id"))
        out = empty_result(rec, FAIL_CONFIDENCE)
        if explain:
            out.update(
                {
                    "fields": {},
                    # наружу только тип исключения: текст и трейс в логе сервера
                    "trace": [
                        {"step": "error", "ms": 0, "changes": {}, "notes": [f"ошибка разбора: {type(exc).__name__}"]}
                    ],
                    "unparsed": [],
                }
            )
        return out


def parse_records(pipeline: Pipeline, records: Iterable[dict[str, Any]], explain: bool = False) -> list[dict[str, Any]]:
    recs = list(records)
    models = pipeline.predict_models([r.get("raw_address") for r in recs])
    has_model = any(hasattr(s, "predict_many") for s in pipeline.steps)
    return [parse_record(pipeline, r, explain, m, has_model) for r, m in zip(recs, models, strict=True)]
