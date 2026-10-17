"""Шаг 7. Ориентир: «магазин береке», «Qazpost Солнечный», «напротив школы 5», «ТЦ Мега».

landmark начинается с маркера (предлог / объект / бренд) и идёт до конца сегмента или до токена,
занятого другим полем. Номер входит в ориентир только после «нумеруемых» объектов («школа 25»).
Текст берётся из оригинальной строки как написан.
"""

from __future__ import annotations

from ..reference.normalize import fold
from ..rules_loader import Rules, get_rules
from .base import ParseState, StepTrace
from .util import mark, match_phrase, segments, tidy_value, value_from

_CLOSE_QUOTES = '"»”“'


def _unbalanced(text: str) -> bool:
    """Открывающих кавычек больше, чем закрывающих (прямая " считается парой сама с собой)."""
    straight = text.count('"') % 2
    curly = sum(text.count(c) for c in "«„") - sum(text.count(c) for c in "»”")
    return bool(straight) or curly > 0


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
        parts = [(w, v) for w in found if (v := value_from(state, [toks[i] for i in w]))]
        if parts:
            # несколько кусков склеиваются только если между ними в оригинале одни разделители
            # («магазин Береке, напротив школы»): значение всегда один спан исходной строки
            used, (s, e) = [parts[0][0]], parts[0][1][1]
            for w, (_, (ps, pe)) in parts[1:]:
                if state.raw[e:ps].strip(" ,;\t") or ps < e:
                    tr.notes.append("остальные ориентиры не рядом: берём первый")
                    break
                used.append(w)
                e = pe
            value = tidy_value(state.raw[s:e])
            # спан идёт по словам: открывающая кавычка внутри, закрывающая за краем, «ТЦ "Мега» выглядит обрезанным.
            # Закрывающую добавляем, если она стоит в исходной строке сразу за значением (tidy_value срезал бы её)
            if value and _unbalanced(value) and e < len(state.raw) and state.raw[e] in _CLOSE_QUOTES:
                value += state.raw[e]
                e += 1
            if value:
                state.set_field("landmark", value, span=(s, e))
                tr.notes.append(f"landmark {value!r}")
                for w in used:
                    mark(state, w, "landmark")
        state.trace.append(tr)
        return state
