"""Шаг 5. Квартира, подъезд, этаж, дом по маркерам (рус/каз/лат, с опечатками).

Маркер может стоять до числа («кв 70») или после («239 кв», «4подьезд»). Порядок решения:
  1) слитное написание связывает однозначно: «11дом» -> 11, «кв70» -> 70;
  2) для остальных маркеров выбираем ориентацию строки целиком (все маркеры «до» или все «после»)
     по числу удовлетворённых маркеров со штрафом за число в другом сегменте; ничья -> «до».
"""

from __future__ import annotations

from dataclasses import dataclass

from ..reference.normalize import fold
from ..rules_loader import Rules, get_rules
from .base import ParseState, StepTrace, Token
from .util import followed_by_dot, house_value, mark, segment_of

DETAIL_FIELDS = ("house", "apartment", "entrance", "floor")


@dataclass
class Marker:
    field: str
    first: int  # индекс первого токена маркера
    last: int  # индекс последнего токена маркера


def _is_num(t: Token) -> bool:
    return t.kind == "num" and t.free


class Details:
    name = "details"

    def __init__(self, rules: Rules | None = None) -> None:
        self.rules = rules or get_rules()

    def _find_markers(self, state: ParseState) -> list[Marker]:
        toks = state.tokens
        out: list[Marker] = []
        i = 0
        while i < len(toks):
            t = toks[i]
            if t.kind != "word" or not t.free:
                i += 1
                continue
            folds: list[str] = []
            j = i
            while j < len(toks) and toks[j].kind == "word" and toks[j].free and len(folds) < 3:
                folds.append(fold(toks[j].text))
                j += 1
            m = self.rules.details.match(folds, 0)
            if not m:
                i += 1
                continue
            fname, n = m
            last = i + n - 1
            word = folds[0]
            # однобуквенные: «д» только перед числом или с точкой
            if n == 1 and len(word) == 1:
                nxt = toks[i + 1] if i + 1 < len(toks) else None
                if not (followed_by_dot(state, i) or (nxt is not None and nxt.kind == "num")):
                    i += 1
                    continue
            out.append(Marker(fname, i, last))
            i = last + 1
        return out

    def _neighbor_num(self, state: ParseState, m: Marker, direction: int) -> int | None:
        """Ближайшее свободное число до/после маркера, через пробелы, точки, «№», «-», «:»."""
        toks = state.tokens
        j = m.last + 1 if direction > 0 else m.first - 1
        while 0 <= j < len(toks):
            t = toks[j]
            if t.kind == "num":
                return j if t.free else None
            if t.kind == "punct" and t.text in ".№#:-":
                j += direction
                continue
            return None  # слово или запятая между маркером и числом: связи нет
        return None

    def __call__(self, state: ParseState) -> ParseState:
        tr = StepTrace(step=self.name)
        toks = state.tokens
        markers = self._find_markers(state)
        seg = segment_of(toks)
        assigned: dict[int, int] = {}  # индекс маркера -> индекс числа

        # 1) слитное написание
        for mi, m in enumerate(markers):
            after = m.last + 1
            if after < len(toks) and toks[after].glued_left and _is_num(toks[after]):
                assigned[mi] = after
                continue
            before = m.first - 1
            if before >= 0 and toks[m.first].glued_left and _is_num(toks[before]):
                assigned[mi] = before
        taken = set(assigned.values())

        # 2) ориентация для остальных
        rest = [mi for mi in range(len(markers)) if mi not in assigned]
        plans: dict[int, dict[int, int]] = {}
        scores: dict[int, float] = {}
        for direction in (+1, -1):
            plan: dict[int, int] = {}
            used = set(taken)
            score = 0.0
            for mi in rest:
                j = self._neighbor_num(state, markers[mi], direction)
                if j is None or j in used:
                    continue
                if seg[j] != seg[markers[mi].first]:
                    score -= 0.5
                plan[mi] = j
                used.add(j)
                score += 1
            plans[direction], scores[direction] = plan, score
        direction = +1 if scores[+1] >= scores[-1] else -1
        # ничья обычно означает «Абая 10 кв 5» (маркер «до»); сомнительна, только если строка
        # заканчивается маркером без числа после него
        last_word = next((t for t in reversed(toks) if t.kind in ("word", "num")), None)
        if (
            rest
            and scores[+1] == scores[-1] > 0
            and last_word is not None
            and last_word.kind == "word"
            and any(markers[mi].last == toks.index(last_word) for mi in rest)
        ):
            state.flags.add("ambiguous_orientation")
        assigned.update(plans[direction])
        # маркеры, которым в выбранной ориентации числа не хватило, пробуют другую сторону
        # («д. 50, кв. 3, 2 подъезд, 1 этаж»: кв «до», подъезд/этаж «после»)
        used_nums = set(assigned.values())
        for mi in rest:
            if mi in assigned:
                continue
            j = self._neighbor_num(state, markers[mi], -direction)
            if j is not None and j not in used_nums:
                assigned[mi] = j
                used_nums.add(j)

        for mi, m in enumerate(markers):
            j = assigned.get(mi)
            mark(state, list(range(m.first, m.last + 1)), f"marker:{m.field}")
            if j is None:
                state.flags.add("marker_without_number")
                tr.notes.append(f"маркер {m.field} без номера")
                continue
            if m.field in state.fields:
                state.flags.add("extra_numbers")
                continue
            value, span = house_value(state, toks[j])
            state.set_field(m.field, value, span=span)
            toks[j].used_by = m.field
            how = "слитно" if toks[j].glued_left or toks[m.first].glued_left else "до" if j > m.last else "после"
            tr.notes.append(f"{m.field}={value!r} ({how})")
        tr.changes["orientation"] = "до числа" if direction > 0 else "после числа"
        state.trace.append(tr)
        return state
