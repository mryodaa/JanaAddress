"""Шаг 4. Область, город, район по маркерам и словарю справочника (рус/каз/лат, дубли, район вместо города).

Значения отдаются в каноническом виде справочника (docs/QUESTIONS.md, Q9). Исключение: район,
написанный по-русски, отдаётся как в строке без слова «район», потому что метрика сравнивает его со строкой.
"""

from __future__ import annotations

import re
from itertools import takewhile

from ..reference.normalize import fold
from ..reference.store import Entity, Store, ambiguous_city_keys, get_store
from ..rules_loader import Rules, get_rules
from .base import ParseState, StepTrace
from .util import has_kazakh, is_cyrillic, mark, marker_ok, match_phrase, segments, value_from

ADJ_ENDINGS = ("ский", "цкий", "ской", "ская", "кий", "ный", "инский", "ий", "ый", "ой")
PROVINCE_BARE = frozenset({"вко", "зко", "ско", "юко"})


class Admin:
    name = "admin"

    def __init__(self, store: Store | None = None, rules: Rules | None = None) -> None:
        self.store = store or get_store()
        self.rules = rules or get_rules()

    # ---------- вспомогательное ----------
    def _words_around(self, state: ParseState, seg: list[int], k: int, n: int) -> tuple[list[int], list[int]]:
        """Свободные слова сразу до маркера (до 3) и сразу после (до 3), без чисел и чужих маркеров."""
        before: list[int] = []
        j = k - 1
        while j >= 0 and len(before) < 3:
            t = state.tokens[seg[j]]
            if t.kind == "punct" and t.text in ".-":
                j -= 1
                continue
            if t.kind != "word" or not t.free:
                break
            before.insert(0, seg[j])
            j -= 1
        after: list[int] = []
        j = k + n
        while j < len(seg) and len(after) < 3:
            t = state.tokens[seg[j]]
            if t.kind == "punct" and t.text in ".-":
                j += 1
                continue
            if t.kind != "word" or not t.free:
                break
            after.append(seg[j])
            j += 1
        return before, after

    def _street_follows(self, state: ParseState, free: list[int], pos: int, city_id: int) -> bool:
        """После позиции pos (через возможный тип улицы) идёт название улицы, известной в этом городе."""
        toks = state.tokens
        j = pos
        while j < len(free) and toks[free[j]].kind == "word" and toks[free[j]].text in self.rules.street_types:
            j += 1
        words: list[str] = []
        while j < len(free) and toks[free[j]].kind == "word" and len(words) < 3:
            words.append(toks[free[j]].text)
            j += 1
        return any(self.store.streets(" ".join(words[:m]), city_id) for m in range(len(words), 0, -1))

    def _is_marker_word(self, text: str) -> bool:
        r = self.rules
        return any(
            text in idx
            for idx in (
                r.street_types,
                r.details,
                r.province_markers,
                r.district_markers,
                r.city_prefix,
                r.settlement_prefix,
                r.lm_objects,
                r.lm_prepositions,
            )
        )

    def _best(
        self, state: ParseState, cand_lists: list[list[int]], etypes: tuple[str, ...], filt: object = None
    ) -> tuple[Entity, list[int]] | None:
        for toks in cand_lists:
            if not toks:
                continue
            text = " ".join(state.tokens[i].text for i in toks)
            found = self.store.lookup(text, etypes)
            if callable(filt):
                found = [e for e in found if filt(e)] or found
            if found:
                return self._prefer(state, found), toks
        return None

    def _prefer(self, state: ParseState, found: list[Entity]) -> Entity:
        """Из нескольких одноимённых сущностей выбираем согласованную с уже найденной областью/городом."""
        pid = state.ref_ids.get("province")
        cid = state.ref_ids.get("city")
        rank = {"republican": 0, "city": 1, "town": 2, "village": 3}

        def key(e: Entity) -> tuple[int, int, int]:
            return (
                0 if (cid and e.city_id == cid) or (pid and e.province_id == pid) else 1,
                0 if e.source == "seed" else 1,
                rank.get(e.kind or "", 4),
            )

        return sorted(found, key=key)[0]

    def _set_province(self, state: ParseState, e: Entity, toks: list[int], tr: StepTrace, score: float = 1.0) -> None:
        span = value_from(state, [state.tokens[i] for i in toks])
        if state.set_field("province", e.name, span=span[1] if span else None, score=score):
            state.ref_ids["province"] = e.id
            tr.notes.append(f"province {e.name!r} по {[state.tokens[i].text for i in toks]}")

    def _set_city(self, state: ParseState, e: Entity, toks: list[int], tr: StepTrace, score: float = 1.0) -> None:
        span = value_from(state, [state.tokens[i] for i in toks])
        if state.set_field("city", e.name, span=span[1] if span else None, score=score):
            state.ref_ids["city"] = e.id
            if e.kind == "republican" and "province" not in state.ref_ids:
                state.ref_ids["province"] = e.province_id
            tr.notes.append(f"city {e.name!r} ({e.kind})")
        elif state.ref_ids.get("city") != e.id:
            # второй, другой город в строке: это может быть название улицы/мкр, поэтому не помечаем
            return
        mark(state, toks, "admin:city")

    # ---------- основной проход ----------
    def __call__(self, state: ParseState) -> ParseState:
        tr = StepTrace(step=self.name)
        r = self.rules
        segs = segments(state.tokens)

        # 0) сельский округ: маркер и его название не идут ни в одно поле
        for seg in segs:
            for k in range(len(seg)):
                m = match_phrase(state, r.rural_okrug, seg, k)  # type: ignore[arg-type]
                if m and state.tokens[seg[k]].free:
                    n = m[1]
                    before, after = self._words_around(state, seg, k, n)
                    name = before[-1:] if before else after[:1]
                    mark(state, seg[k : k + n] + name, "admin:okrug")

        # 0b) шум: «РК», «Республика Казахстан», «адрес:» в начале строки или отдельным сегментом
        for si, seg in enumerate(segs):
            words = [i for i in seg if state.tokens[i].kind in ("word", "num") and state.tokens[i].free]
            noisy = [i for i in words if state.tokens[i].kind == "word" and state.tokens[i].text in r.noise]
            if noisy and len(noisy) == len(words):
                mark(state, noisy, "noise")
            elif si == 0:
                lead = []
                for i in words:
                    if state.tokens[i].kind == "word" and state.tokens[i].text in r.noise:
                        lead.append(i)
                    else:
                        break
                mark(state, lead, "noise")

        # 1) область по маркеру
        for seg in segs:
            for k in range(len(seg)):
                if not state.tokens[seg[k]].free:
                    continue
                m = match_phrase(state, r.province_markers, seg, k)  # type: ignore[arg-type]
                if not m:
                    continue
                n = m[1]
                before, after = self._words_around(state, seg, k, n)
                found = self._best(
                    state,
                    [before[-2:], before[-1:], after[:1], after[:2]],
                    ("province",),
                    lambda e: e.kind == "oblast",  # рядом с «область» город респ. значения не подходит
                )
                if found:
                    e, toks = found
                    self._set_province(state, e, toks, tr)
                    mark(state, toks + seg[k : k + n], "admin:province")
                elif before and fold(state.tokens[before[-1]].text).endswith(("ская", "кая")):
                    t = state.tokens[before[-1]]
                    v = value_from(state, [t])
                    if v and state.set_field("province", f"{v[0][:1].upper()}{v[0][1:]} область", span=v[1], score=0.6):
                        state.flags.add("fuzzy_admin")
                    mark(state, [before[-1], *seg[k : k + n]], "admin:province")

        # 1b) области без маркера: ВКО/ЗКО/СКО/ЮКО
        for t_i, t in enumerate(state.tokens):
            if t.free and t.kind == "word" and fold(t.text) in PROVINCE_BARE:
                bare = self.store.lookup(t.text, ("province",))
                if bare:
                    self._set_province(state, bare[0], [t_i], tr)
                    mark(state, [t_i], "admin:province")

        # 2) город/посёлок по маркеру
        for seg in segs:
            for k in range(len(seg)):
                t = state.tokens[seg[k]]
                if not t.free or t.kind != "word":
                    continue
                pre = match_phrase(state, r.city_prefix, seg, k) or match_phrase(state, r.settlement_prefix, seg, k)  # type: ignore[arg-type]
                suf = match_phrase(state, r.city_suffix, seg, k) or match_phrase(state, r.settlement_suffix, seg, k)  # type: ignore[arg-type]
                if not pre and not suf:
                    continue
                n = (pre or suf)[1]  # type: ignore[index]
                weak = (n == 1 and fold(t.text) in r.weak_prefixes) or (n == 1 and len(t.text) == 1)
                before, after = self._words_around(state, seg, k, n)
                if pre and suf:  # «қ» бывает и до, и после названия: «қ. Алматы», «Алматы қ.»
                    cands = [after[:3], after[:2], after[:1], before[-3:], before[-2:], before[-1:]]
                elif pre:
                    cands = [after[:3], after[:2], after[:1]]
                else:
                    cands = [before[-3:], before[-2:], before[-1:]]
                pid = state.ref_ids.get("province")
                found = self._best(state, cands, ("city",), (lambda e, pid=pid: e.province_id == pid) if pid else None)
                if found:
                    e, toks = found
                    self._set_city(state, e, toks, tr)
                    mark(state, seg[k : k + n], "marker:city")
                    continue
                name_toks = (after if pre else before)[:2] if not weak else []
                # чужой маркер обрывает имя, а не пропускается: «city Ул . Елибаева» не город «Елибаева»
                name_toks = list(takewhile(lambda i: not self._is_marker_word(state.tokens[i].text), name_toks))
                if weak and fold(t.text) == "г" and (after if pre else before):
                    # «г Алматы» без точки: город из справочника не найден, пробуем нечётко
                    name_toks = (after if pre else before)[:1]
                if not name_toks:
                    continue
                text = " ".join(state.tokens[i].text for i in name_toks)
                fz = self.store.fuzzy(text, "city", cutoff=88)
                if fz:
                    self._set_city(state, fz[0], name_toks, tr, score=0.7)
                    state.flags.add("fuzzy_admin")
                elif not weak:
                    v = value_from(state, [state.tokens[i] for i in name_toks])
                    if v and state.set_field("city", v[0], span=v[1], score=0.6):
                        tr.notes.append(f"city {v[0]!r} нет в справочнике, взят из строки")
                    mark(state, name_toks, "admin:city")
                else:
                    continue
                mark(state, seg[k : k + n], "marker:city")

        # 3) район по маркеру
        for seg in segs:
            for k in range(len(seg)):
                t = state.tokens[seg[k]]
                if not t.free or t.kind != "word":
                    continue
                m = match_phrase(state, r.district_markers, seg, k)  # type: ignore[arg-type]
                if not m or not marker_ok(state, r, seg, k, m[1]):
                    continue
                if k > 0 and fold(state.tokens[seg[k - 1]].text) in r.district_blockers:
                    continue  # «шағын ауданы» = микрорайон
                n = m[1]
                before, after = self._words_around(state, seg, k, n)
                before = [i for i in before if not self._is_marker_word(state.tokens[i].text)]
                after = [i for i in after if not self._is_marker_word(state.tokens[i].text)]
                cid, pid = state.ref_ids.get("city"), state.ref_ids.get("province")

                def in_scope(e: Entity, cid: int | None = cid, pid: int | None = pid) -> bool:
                    return (cid is not None and e.city_id == cid) or (
                        cid is None and pid is not None and e.province_id == pid
                    )

                found = self._best(
                    state, [before[-2:], before[-1:], after[:3], after[:2], after[:1]], ("district",), in_scope
                )
                toks = []
                ent: Entity | None = None
                if found:
                    ent, toks = found
                elif before and fold(state.tokens[before[-1]].text).endswith(ADJ_ENDINGS):
                    toks = before[-1:]
                elif after:
                    toks = after[:1]
                elif before:
                    toks = before[-1:]
                if not toks:
                    continue
                v = value_from(state, [state.tokens[i] for i in toks])
                if not v:
                    continue
                value = v[0] if (is_cyrillic(v[0]) and not has_kazakh(v[0])) or ent is None else ent.name
                if state.set_field("district", value, span=v[1], score=1.0 if ent else 0.7):
                    if ent:
                        state.ref_ids["district"] = ent.id
                    tr.notes.append(f"district {value!r}" + (f" -> справочник {ent.name!r}" if ent else ""))
                mark(state, toks + seg[k : k + n], "admin:district")

        # 4) город без маркера («Алматы, ...», «Алматы Абая 1»): только в начале/конце сегмента,
        #    не рядом с типом улицы и не перед номером (иначе это улица: «Туркестан 12»)
        amb = ambiguous_city_keys()
        for seg in segs:
            free = [
                i
                for i in seg
                if state.tokens[i].free
                and state.tokens[i].kind in ("word", "num")
                and not re.fullmatch(r"\d{6}", state.tokens[i].text)  # почтовый индекс
            ]
            if not free:
                continue
            for n in (3, 2, 1):
                for start in {0, max(0, len(free) - n)}:
                    toks = free[start : start + n]
                    if len(toks) < n or any(state.tokens[i].kind != "word" or not state.tokens[i].free for i in toks):
                        continue
                    if seg.index(toks[-1]) - seg.index(toks[0]) > 2 * n:
                        continue
                    text = " ".join(state.tokens[i].text for i in toks)
                    cities = self.store.lookup(text, ("city",))
                    if not cities:
                        continue
                    whole = len(toks) == len(free)
                    nxt = free[start + n] if start + n < len(free) else None
                    after_nxt = free[start + n + 1] if start + n + 1 < len(free) else None
                    if fold(text) in amb and not whole:
                        # «Балхаш Гагарина 56»: имя совпадает с улицами, но дальше идёт улица этого города;
                        # «Шу микрорайон 8»: дальше номерной микрорайон / квартал
                        st_n = r.street_types.get(state.tokens[nxt].text) if nxt is not None else None
                        numbered_area = (
                            st_n is not None
                            and st_n.kind != "street"
                            and after_nxt is not None
                            and state.tokens[after_nxt].kind == "num"
                        )
                        confirmed = [
                            e
                            for e in cities
                            if start == 0
                            and ((numbered_area and e.kind != "village") or self._street_follows(state, free, n, e.id))
                        ]
                        if not confirmed:
                            continue
                        cities = confirmed
                    if nxt is not None and state.tokens[nxt].kind == "num":
                        # «Туркестан 12» это улица, но «Актау 14 мкр» это город + номер микрорайона
                        st_after = r.street_types.get(state.tokens[after_nxt].text) if after_nxt is not None else None
                        if st_after is None or st_after.kind != "area":
                            continue
                    pos = seg.index(toks[0])
                    prev = seg[pos - 1] if pos > 0 else None
                    if prev is not None and (
                        state.tokens[prev].text in r.street_types
                        or (state.tokens[prev].used_by or "").startswith("marker")
                    ):
                        continue
                    # тип улицы ПОСЛЕ названия («Абай даңғылы, 52») значит это улица;
                    # тип с названием дальше («Петропавловск ул Конституции») значит город;
                    # площадной тип с номером («Шымкент квартал 19») тоже город
                    st_nxt = r.street_types.get(state.tokens[nxt].text) if nxt is not None else None
                    if (
                        st_nxt is not None
                        and (after_nxt is None or state.tokens[after_nxt].kind != "word")
                        and not (st_nxt.kind != "street" and after_nxt is not None)
                    ):
                        continue
                    e = self._prefer(state, cities)
                    if e.kind == "village" and not whole:
                        continue
                    self._set_city(state, e, toks, tr, score=0.9)

        state.trace.append(tr)
        return state
