"""Шаг 11. confidence: вероятность, что запись разобрана верно целиком (все поля метрики).

Логистическая регрессия на признаках разбора: доля распознанных токенов, наличие полей, остаток, флаги, бонусы
справочника, худший score поля из строки. Веса в rules/confidence.yaml подбирает training/fit_confidence.py на
dev-наборах, вручную их не правят. В trace: признаки (для подбора) и вклады в вероятность, сумма вкладов = итог.
"""

from __future__ import annotations

import math
import re

from ..rules_loader import Rules, get_rules
from .base import SOURCE_STRING, ParseState, StepTrace, Token
from .reference_step import AREA_TYPES

MAX_UNPARSED = 5  # дальше остаток уже ничего не добавляет: строка и так разобрана плохо
LO, HI = 0.02, 0.99


def _sigmoid(z: float) -> float:
    return 1 / (1 + math.exp(-z)) if z >= 0 else math.exp(z) / (1 + math.exp(z))


def _content(state: ParseState) -> list[Token]:
    return [t for t in state.tokens if t.kind in ("word", "num") and t.used_by != "kz_dup"]


def features(state: ParseState) -> dict[str, float] | None:
    """Признаки записи; None, если в строке нет слов и чисел (там ответ всегда LO)."""
    content = _content(state)
    if not content:
        return None
    unparsed = sum(1 for t in content if t.free)
    st, house, name = state.get("street_type"), state.get("house"), state.get("street_name") or ""
    if st in AREA_TYPES and house and re.fullmatch(r"\d", house) and not re.search(r"\d", name):
        state.flags.add("house_like_area_number")
    scores = [fv.score for fv in state.fields.values() if fv.source == SOURCE_STRING]
    x: dict[str, float] = {
        "consumed": 1 - unparsed / len(content),
        "street_name": float(state.has("street_name")),
        "house": float(state.has("house")),
        "admin": float(state.has("city") or state.has("province")),
        "unparsed": float(min(unparsed, MAX_UNPARSED)),
        "no_street_house": float(not state.has("street_name") and not state.has("house")),
        "min_score": min(scores) if scores else 0.0,
    }
    for flag in sorted(state.flags):
        x[f"flag:{flag}"] = 1.0
    return x


class Confidence:
    name = "confidence"

    def __init__(self, rules: Rules | None = None) -> None:
        self.rules = rules or get_rules()

    def __call__(self, state: ParseState) -> ParseState:
        tr = StepTrace(step=self.name)
        x = features(state)
        if x is None:
            state.confidence = LO
            tr.notes.append("в строке нет слов и чисел")
            state.trace.append(tr)
            return state
        content = _content(state)
        cfg = self.rules.confidence
        # формат проверен при загрузке (rules_loader._check_confidence)
        weights: dict[str, float] = {
            **cfg["features"],
            **{f"flag:{k}": v for k, v in (cfg.get("flags") or {}).items()},
        }
        # вклад каждого признака в вероятность по порядку: база, признаки, флаги; сумма вкладов = итог.
        # Обрезка до [LO, HI] только в конце и отдельной строкой cap, иначе потолок прятал бы вклады
        z = float(cfg["intercept"])
        prev = _sigmoid(z)
        parts: dict[str, float] = {"base": prev}
        for k, v in x.items():
            w = weights.get(k, 0.0)
            if not v or not w:
                continue
            z += w * v
            cur = _sigmoid(z)
            parts[k] = cur - prev
            prev = cur
        final = min(HI, max(LO, prev))
        if final != prev:
            parts["cap"] = final - prev
        state.confidence = round(final, 3)
        # слагаемые модели в баллах (логитах): вес × значение признака. В отличие от parts они не зависят от
        # порядка, сумма intercept + points = logit, p = sigmoid(logit): по ним UI объясняет, почему такой итог
        terms = [
            {"key": k, "x": round(v, 3), "w": round(weights[k], 3), "points": round(weights[k] * v, 3)}
            for k, v in x.items()
            if v and weights.get(k)
        ]
        tr.changes = {
            "confidence": state.confidence,
            "parts": {k: round(v, 3) for k, v in parts.items()},
            "features": {k: round(v, 3) for k, v in x.items()},
            "intercept": round(float(cfg["intercept"]), 3),
            "terms": terms,
            "logit": round(z, 3),
            "bounds": [LO, HI],
            "unparsed": [t.text for t in content if t.free],
            # для объяснения в UI: сколько слов и чисел в строке, надёжность каждого поля из строки (самое слабое
            # даёт min_score) и числа, которые не пригодились (флаг extra_numbers)
            "content": len(content),
            "scores": {f: round(fv.score, 2) for f, fv in state.fields.items() if fv.source == SOURCE_STRING},
            "extra": [t.text for t in state.tokens if (t.used_by or "").startswith("extra")],
        }
        state.trace.append(tr)
        return state
