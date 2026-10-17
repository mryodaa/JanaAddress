"""Шаг 7c. Населённый пункт без маркера в отдельном сегменте перед улицей:
«Илийский район, Боралдай, ул. Ленина 1/2» -> city «Боралдай».

Берём, только если город ещё не найден, группа слов занимает сегмент целиком, стоит раньше улицы и
либо известна справочнику, либо рядом есть район/область из строки (тогда флаг guessed_city).
"""

from __future__ import annotations

from ..reference.store import Store, get_store
from .base import ParseState, StepTrace
from .util import as_written, mark, segments, value_from


class Leftover:
    name = "leftover"

    def __init__(self, store: Store | None = None) -> None:
        self.store = store or get_store()

    def __call__(self, state: ParseState) -> ParseState:
        tr = StepTrace(step=self.name)
        toks = state.tokens
        if "city" not in state.fields:
            street_start = min(
                (i for i, t in enumerate(toks) if t.used_by in ("street_name", "marker:street", "living_area")),
                default=len(toks),
            )
            for seg in segments(toks):
                content = [i for i in seg if toks[i].kind in ("word", "num")]
                free = [i for i in content if toks[i].free]
                if not free or free != content or any(toks[i].kind != "word" for i in free) or len(free) > 3:
                    continue
                if free[0] > street_start:
                    break
                text = " ".join(toks[i].text for i in free)
                pid = state.ref_ids.get("province")
                did = state.ref_ids.get("district")
                found = self.store.lookup(text, ("city",))
                if did:
                    found = [e for e in found if e.district_id == did] or found
                if pid:
                    found = [e for e in found if e.province_id == pid] or found
                v = value_from(state, [toks[i] for i in free])
                if not v:
                    continue
                if found:
                    e = found[0]
                    # Q22: город как в строке, справочник только для привязки (как в admin._set_city)
                    state.set_field("city", as_written(v[0], e.name), span=v[1], score=0.85)
                    state.ref_ids["city"] = e.id
                    tr.notes.append(f"city {e.name!r} по справочнику (сегмент без маркера)")
                elif "district" in state.fields or "province" in state.fields:
                    state.set_field("city", v[0], span=v[1], score=0.5)
                    state.flags.add("guessed_city")
                    tr.notes.append(f"city {v[0]!r} угадан по позиции")
                else:
                    continue
                mark(state, free, "admin:city")
                break
        state.trace.append(tr)
        return state
