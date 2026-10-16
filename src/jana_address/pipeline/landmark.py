"""Шаг 7. Ориентир: «магазин береке», «Qazpost Солнечный», «напротив школы 5», «ТЦ Мега».

landmark начинается с маркера (предлог / объект / бренд) и идёт до конца сегмента или до токена,
занятого другим полем. Номер входит в ориентир только после «нумеруемых» объектов («школа 25»).
Текст берётся из оригинальной строки как написан.
"""

from __future__ import annotations

from ..reference.normalize import fold
from ..rules_loader import Rules, get_rules
from .base import ParseState, StepTrace
from .util import mark, match_phrase, segments, value_from


class Landmark:
    name = "landmark"

    def __init__(self, rules: Rules | None = None) -> None:
        self.rules = rules or get_rules()

    def __call__(self, state: ParseState) -> ParseState:
        tr = StepTrace(step=self.name)
        r = self.rules
        toks = state.tokens
        found: list[list[int]] = []
        for seg in segments(toks):
            k = 0
            while k < len(seg):
                t = toks[seg[k]]
                if not t.free or t.kind != "word":
                    k += 1
                    continue
                m = None
                is_prep = False
                for idx in (r.lm_prepositions, r.lm_objects, r.lm_brands):
                    m = match_phrase(state, idx, seg, k)  # type: ignore[arg-type]
                    if m:
                        is_prep = idx is r.lm_prepositions
                        break
                if not m:
                    k += 1
                    continue
                n = m[1]
                run = list(seg[k : k + n])
                j = k + n
                while j < len(seg):
                    u = toks[seg[j]]
                    if not u.free:
                        break
                    if u.kind == "num":
                        prev_words = [fold(toks[i].text) for i in run if toks[i].kind == "word"]
                        prev = toks[seg[j - 1]]
                        if (prev_words and prev_words[-1] in r.lm_numbered) or prev.text in "№#":
                            run.append(seg[j])
                            j += 1
                            continue
                        break
                    if u.kind == "word" and (u.text in r.details or u.text in r.street_types):
                        break
                    if u.kind in ("word", "punct"):
                        run.append(seg[j])
                    j += 1
                words = [i for i in run if toks[i].kind in ("word", "num")]
                # одиночный предлог без объекта это не ориентир
                if is_prep and len(words) == n:
                    k = j
                    continue
                found.append(words)
                k = j
        if found:
            parts = [value_from(state, [toks[i] for i in w]) for w in found]
            parts_ok = [p for p in parts if p]
            if parts_ok:
                value = ", ".join(p[0] for p in parts_ok)
                span = (parts_ok[0][1][0], parts_ok[-1][1][1])
                state.set_field("landmark", value, span=span)
                tr.notes.append(f"landmark {value!r}")
            for w in found:
                mark(state, w, "landmark")
        state.trace.append(tr)
        return state
