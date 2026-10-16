"""Шаг 9. confidence в [0, 1]: доля распознанных токенов, неразобранный остаток, качество сопоставления,
конфликты. Веса в rules/confidence.yaml, калибровка проверяется scripts/eval.py (ECE).
"""

from __future__ import annotations

import re

from ..rules_loader import Rules, get_rules
from .base import SOURCE_STRING, ParseState, StepTrace
from .reference_step import AREA_TYPES


class Confidence:
    name = "confidence"

    def __init__(self, rules: Rules | None = None) -> None:
        self.rules = rules or get_rules()

    def __call__(self, state: ParseState) -> ParseState:
        tr = StepTrace(step=self.name)
        cfg = self.rules.confidence
        content = [t for t in state.tokens if t.kind in ("word", "num") and t.used_by != "kz_dup"]
        if not content:
            state.confidence = 0.02
            tr.notes.append("в строке нет слов и чисел")
            state.trace.append(tr)
            return state
        unparsed = [t for t in content if t.free]
        ratio = 1 - len(unparsed) / len(content)

        parts: dict[str, float] = {"base": cfg["base"], "consumed": cfg["consumed_ratio"] * ratio}
        if state.has("street_name"):
            parts["street_name"] = cfg["has_street_name"]
        if state.has("house"):
            parts["house"] = cfg["has_house"]
        if state.has("city") or state.has("province"):
            parts["admin"] = cfg["has_city_or_province"]
        if unparsed:
            parts["unparsed"] = max(cfg["max_unparsed_penalty"], cfg["per_unparsed_token"] * len(unparsed))
        if not state.has("street_name") and not state.has("house"):
            parts["no_street_house"] = cfg["no_street_and_house"]

        st, house, name = state.get("street_type"), state.get("house"), state.get("street_name") or ""
        if st in AREA_TYPES and house and re.fullmatch(r"\d", house) and not re.search(r"\d", name):
            state.flags.add("house_like_area_number")
        for flag in sorted(state.flags):
            if flag in cfg.get("flags", {}):
                parts[f"flag:{flag}"] = cfg["flags"][flag]
            elif flag in cfg.get("bonus", {}):
                parts[f"bonus:{flag}"] = cfg["bonus"][flag]

        raw = sum(parts.values())
        # слабые совпадения в полях из строки тянут вниз
        scores = [fv.score for fv in state.fields.values() if fv.source == SOURCE_STRING]
        if scores:
            raw *= 0.75 + 0.25 * min(scores)
        state.confidence = round(min(0.99, max(0.02, raw)), 3)
        tr.changes = {
            "confidence": state.confidence,
            "parts": {k: round(v, 3) for k, v in parts.items()},
            "unparsed": [t.text for t in unparsed],
        }
        state.trace.append(tr)
        return state
