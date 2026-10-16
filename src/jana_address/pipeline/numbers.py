"""Шаг 7b. Дом и квартира без маркеров, по позиции.

Первое свободное число после названия улицы -> house; «150-23» -> house 150, apartment 23 (Q8);
следующее свободное число -> apartment, если квартира ещё не найдена. Индексы (6 цифр) и телефоны
(7+ цифр) пропускаются.
"""

from __future__ import annotations

import re

from ..rules_loader import Rules, get_rules
from .base import ParseState, StepTrace
from .util import house_value

_POSTCODE = re.compile(r"^\d{6}$")
_LONG = re.compile(r"^\d{7,}$")


class Numbers:
    name = "numbers"

    def __init__(self, rules: Rules | None = None) -> None:
        self.rules = rules or get_rules()

    def __call__(self, state: ParseState) -> ParseState:
        tr = StepTrace(step=self.name)
        toks = state.tokens
        street_end = state.ref_ids.get("street_end", -1)
        free = []
        for i, t in enumerate(toks):
            if t.kind != "num" or not t.free:
                continue
            if _POSTCODE.match(t.text) or _LONG.match(t.text):
                t.used_by = "noise:number"
                continue
            free.append(i)
        # сначала числа после улицы, затем остальные по порядку
        ordered = [i for i in free if i > street_end] + [i for i in free if i <= street_end]
        if not ordered:
            state.trace.append(tr)
            return state

        if "house" not in state.fields:
            i = ordered.pop(0)
            value, span = house_value(state, toks[i])
            state.set_field("house", value, span=span, score=0.9 if "street_name" in state.fields else 0.6)
            toks[i].used_by = "house"
            tr.notes.append(f"house={value!r} по позиции")
            # «150-23»: дом-квартира
            if (
                self.rules.house_dash_apartment
                and i + 2 < len(toks)
                and toks[i + 1].text == "-"
                and toks[i + 1].glued_left
                and toks[i + 2].glued_left
                and toks[i + 2].kind == "num"
                and toks[i + 2].free
                and "apartment" not in state.fields
            ):
                value, span = house_value(state, toks[i + 2])
                state.set_field("apartment", value, span=span, score=0.8)
                toks[i + 2].used_by = "apartment"
                toks[i + 1].used_by = "apartment"
                if i + 2 in ordered:
                    ordered.remove(i + 2)
                tr.notes.append(f"apartment={value!r} из «дом-квартира»")

        if ordered and "apartment" not in state.fields and "house" in state.fields:
            i = ordered.pop(0)
            value, span = house_value(state, toks[i])
            state.set_field("apartment", value, span=span, score=0.6)
            toks[i].used_by = "apartment"
            tr.notes.append(f"apartment={value!r} по позиции")
        if ordered:
            state.flags.add("extra_numbers")
        state.trace.append(tr)
        return state
