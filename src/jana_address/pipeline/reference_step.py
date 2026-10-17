"""Шаг 8. Восстановление недостающих province, city, district, living_area, street_type по справочнику.

Заполняются только пустые поля. Значение из строки никогда не перезаписывается справочным
(это гарантирует ParseState.set_field). Источник поля: reference:osm:<house|street|polygon|point|poi>,
reference:seed, reference:kato (store.ref_source). Геометрии здесь нет: привязки посчитаны при сборке.
Порядок уверенности для district / living_area: дом найден -> его район и мкр; иначе улица -> доминирующий
район / мкр (лучший кандидат и при неоднозначности, неуверенность во флаге и confidence, Q20); мкр из строки ->
его район; населённый пункт -> район области; ориентир, однозначно найденный в городе -> его район (слабо).
"""

from __future__ import annotations

import re
from collections.abc import Callable

from ..reference.normalize import fold
from ..reference.store import Entity, Store, get_store, ref_source
from ..rules_loader import Rules, get_rules
from .base import SOURCE_STRING, ParseState, StepTrace

AREA_TYPES = frozenset(
    {"микрорайон", "квартал", "жилой массив", "жилой комплекс", "дачный массив", "разъезд", "промзона"}
)
DOMINANT_SHARE = 0.8  # ниже: лучший кандидат всё равно ставится, но с флагом неоднозначности
TYPE_SHARE = 0.6  # доминирующий тип улицы среди одноимённых в городе
_WORD = re.compile(r"[^\W_]+(?:[-'][^\W_]+)*")
# через сколько слов от начала ориентира искать название объекта («напротив ТЦ Мега» -> «Мега»)
LANDMARK_MAX_SKIP = 3


def historical_province(rules: Rules, store: Store, prov: Entity, city: Entity) -> bool:
    """Прежняя область города после передела («ВКО, г. Семей»): не конфликт (rules/admin.yaml)."""
    modern = store.province_of(city)
    return modern is not None and prov.name in rules.historical_provinces.get(modern.name, set())


def _via_source(e: Entity, via: str) -> str:
    """Привязка сущности по геометрии сборки: у OSM способ, у ядра/КАТО табличная."""
    return ref_source(e.source, via)


class Reference:
    name = "reference"

    def __init__(self, store: Store | None = None, rules: Rules | None = None) -> None:
        self.store = store or get_store()
        self.rules = rules or get_rules()

    def _fill(
        self,
        state: ParseState,
        fname: str,
        e: Entity | None,
        tr: StepTrace,
        value: str | None = None,
        score: float = 0.8,
        source: str | None = None,
    ) -> bool:
        if e is None:
            return False
        v = value or e.name
        src = source or _via_source(e, "polygon")
        if state.set_field(fname, v, source=src, score=score):
            tr.notes.append(f"{fname} <- {v!r} ({src}, {e.etype}#{e.id})")
            return True
        return False

    def __call__(self, state: ParseState) -> ParseState:
        tr = StepTrace(step=self.name)
        s = self.store
        city = s.get("city", state.ref_ids.get("city"))
        prov = s.get("province", state.ref_ids.get("province"))
        dist = s.get("district", state.ref_ids.get("district"))

        # район из строки, не сопоставленный в admin (например, город нашёлся позже)
        if dist is None and state.get("district"):
            found = s.lookup(state.get("district") or "", ("district",))
            if city:
                found = [e for e in found if e.city_id == city.id] or ([] if city.kind == "republican" else found)
            elif prov:
                found = [e for e in found if e.province_id == prov.id] or found
            if len(found) == 1 or (found and len({e.city_id or e.province_id for e in found}) == 1):
                dist = found[0]
        # район противоречит городу
        if dist and city and dist.kind == "city" and dist.city_id != city.id:
            state.flags.add("city_province_conflict")
            dist = None

        # город по району (район города -> город)
        if city is None and dist is not None and dist.city_id:
            city = s.get("city", dist.city_id)
            self._fill(state, "city", city, tr, source=_via_source(dist, "polygon"))

        # микрорайон / ЖК из строки
        area_name = state.get("living_area")
        if not area_name and state.get("street_type") in AREA_TYPES:
            area_name = state.get("street_name")
        area: Entity | None = None
        if area_name:
            found = s.lookup(area_name, ("living_area",))
            if city:
                found = [e for e in found if e.city_id == city.id]
            if len({e.city_id for e in found}) == 1:
                area = found[0]
                if city is None:
                    city = s.get("city", area.city_id)
                    self._fill(state, "city", city, tr, score=0.7, source=_via_source(area, "polygon"))

        # улица
        street_name = state.get("street_name")
        streets: list[Entity] = []
        typed: list[Entity] = []  # улицы написанного типа (или все, если такого типа в справочнике нет)
        if street_name and state.get("street_type") not in AREA_TYPES:
            streets = s.streets(street_name, city.id if city else None)
            if city is None and streets:
                if dist is not None and dist.city_id:
                    streets = [st for st in streets if st.city_id == dist.city_id] or streets
                if prov is not None:
                    streets = [st for st in streets if st.province_id == prov.id] or streets
                cities = {st.city_id for st in streets}
                if len(cities) == 1:
                    city = s.get("city", next(iter(cities)))
                    if self._fill(state, "city", city, tr, score=0.6, source=ref_source("osm", "street")):
                        tr.notes.append("город восстановлен по уникальной улице")
                else:
                    streets = []
            if not streets and city is not None:
                fz = s.street_fuzzy(street_name, city.id)
                if fz:
                    streets = fz[0]
                    tr.notes.append(f"улица найдена нечётко ({fz[1]:.0f}): {streets[0].name!r}")
            if streets:
                state.flags.add("street_in_reference")
                typ = state.get("street_type")
                typed = [st for st in streets if st.kind == typ] or streets if typ else streets
                if typ:
                    # дом ищем сначала на улице написанного типа, потом на одноимённых другого типа:
                    # в OSM дома «Орал» без типа висят на одной из одноимённых улиц
                    streets = typed + [st for st in streets if st not in typed]
                else:
                    self._street_type(state, streets, tr)
            elif city is not None:
                state.flags.add("street_not_in_reference")

        # область
        if prov is None:
            src_e: Entity | None = city or dist or area
            if city is not None:
                prov = s.province_of(city)
            elif dist is not None:
                prov = s.get("province", dist.province_id)
            elif area is not None:
                prov = s.get("province", area.province_id)
            self._fill(state, "province", prov, tr, source=_via_source(src_e, "polygon") if src_e else None)
        elif not state.has("province"):
            self._fill(state, "province", prov, tr)  # город респ. значения: province = город
        elif (
            city is not None
            and city.province_id != prov.id
            and state.fields.get("city", None) is not None
            and state.fields["city"].source == SOURCE_STRING
            and state.fields["province"].source == SOURCE_STRING
        ):
            if historical_province(self.rules, s, prov, city):
                tr.notes.append(f"область {prov.name!r} прежняя для {city.name!r} (передел): не конфликт, как написано")
            else:
                state.flags.add("city_province_conflict")

        # район и мкр
        need_area = not state.has("living_area") and state.get("street_type") not in AREA_TYPES
        if not state.has("district") or need_area:
            self._district_and_area(state, streets, typed, area, city, tr, need_area)
        state.trace.append(tr)
        return state

    # ---------- тип улицы ----------
    def _street_type(self, state: ParseState, streets: list[Entity], tr: StepTrace) -> None:
        types = {st.kind for st in streets if st.kind}
        if len(types) == 1:
            src = ref_source("osm", "street")
            self._fill(state, "street_type", streets[0], tr, value=next(iter(types)), score=0.7, source=src)
            return
        if len(types) > 1:
            # одноимённые улицы разных типов: доминирующий по длине сегментов OSM
            best: tuple[float, Entity] | None = None
            for st in streets:
                info = self.store.street_info(st.id)
                if st.kind and info and info.type_share is not None and (best is None or info.type_share > best[0]):
                    best = (info.type_share, st)
            if best is not None and best[0] >= TYPE_SHARE:
                state.flags.add("street_type_dominant")
                self._fill(
                    state, "street_type", best[1], tr, value=best[1].kind, score=0.5, source=ref_source("osm", "street")
                )

    # ---------- район / мкр ----------
    def _district_and_area(
        self,
        state: ParseState,
        streets: list[Entity],
        typed: list[Entity],
        area: Entity | None,
        city: Entity | None,
        tr: StepTrace,
        need_area: bool,
    ) -> None:
        s = self.store
        need_district = not state.has("district")
        house = state.get("house")
        # 1. дом найден в справочнике
        if streets and house:
            for st in streets:
                h = s.house(st.id, house)
                if h is None:
                    continue
                state.flags.add("house_in_reference")
                if need_district and h.district_id:
                    self._fill(state, "district", s.get("district", h.district_id), tr, score=0.75,
                               source=ref_source(h.source, "house"))  # fmt: skip
                    need_district = False
                if need_area and h.living_area_id:
                    by_point = h.la_method == "point"
                    if by_point:
                        state.flags.add("living_area_by_point")
                    self._fill(state, "living_area", s.get("living_area", h.living_area_id), tr,
                               score=0.5 if by_point else 0.6,
                               source=ref_source(h.source, "point" if by_point else "house"))  # fmt: skip
                    need_area = False
                break
        # 2. мкр из строки -> его район
        if need_district and area is not None and area.district_id:
            self._fill(state, "district", s.get("district", area.district_id), tr, score=0.7,
                       source=_via_source(area, "polygon"))  # fmt: skip
            need_district = False
        # 3. улица -> доминирующий район / мкр (лучший кандидат даже при неоднозначности)
        if streets and (need_district or need_area):
            if need_district:
                best = self._best(typed, s.district_shares)
                if best is not None:
                    did, share, n = best
                    if share < DOMINANT_SHARE:
                        state.flags.add("district_ambiguous")
                        tr.notes.append(f"улица в нескольких районах ({n}), лучший с долей {share:.2f}")
                    if self._fill(state, "district", s.get("district", did), tr,
                                  score=0.7 if share >= DOMINANT_SHARE else 0.45,
                                  source=ref_source("osm", "street")):  # fmt: skip
                        need_district = False
            if need_area:
                best = self._best(typed, s.area_shares)
                if best is not None:
                    aid, share, n = best
                    if share < DOMINANT_SHARE:
                        state.flags.add("living_area_ambiguous")
                    if self._fill(state, "living_area", s.get("living_area", aid), tr,
                                  score=0.5 if share >= DOMINANT_SHARE else 0.35,
                                  source=ref_source("osm", "street")):  # fmt: skip
                        need_area = False
        # 4. населённый пункт -> район области
        if need_district and city is not None and city.district_id:
            method = s.city_district_method(city.id)
            src = ref_source("osm", "polygon") if method in ("polygon", "near") else ref_source(method or city.source)
            if method == "near":
                state.flags.add("district_by_near_polygon")
            if self._fill(state, "district", s.get("district", city.district_id), tr, score=0.7, source=src):
                need_district = False
        # 5. улицы нет, ориентир однозначно найден в городе -> его район (подсказка с низким весом)
        if need_district and not streets and city is not None and state.get("landmark"):
            lm_did = self._landmark_district(state.get("landmark") or "", city, tr)
            if lm_did is not None and self._fill(
                state, "district", s.get("district", lm_did), tr, score=0.4, source=ref_source("osm", "poi")
            ):
                state.flags.add("district_by_landmark")

    @staticmethod
    def _best(
        streets: list[Entity], shares: Callable[[int], list[tuple[int, float, int]]]
    ) -> tuple[int, float, int] | None:
        """Лучший район / мкр по всем найденным улицам: доли складываются с весом по числу домов улицы."""
        weights: dict[int, float] = {}
        for st in streets:
            rows = shares(st.id)
            n_houses = sum(h for _, _, h in rows)
            for eid, share, _ in rows:
                weights[eid] = weights.get(eid, 0.0) + share * (1 + n_houses)
        if not weights:
            return None
        total = sum(weights.values())
        top, w = max(weights.items(), key=lambda kv: kv[1])
        return top, (w / total if total else 0.0), len(weights)

    def _landmark_district(self, text: str, city: Entity, tr: StepTrace) -> int | None:
        """Название объекта ищется хвостами ориентира: «напротив ТЦ Мега» -> «ТЦ Мега», «Мега».
        Падежное окончание последнего слова снимается («возле Магнума» -> «Магнум»)."""
        words = _WORD.findall(text)
        for i in range(min(len(words), LANDMARK_MAX_SKIP + 1)):
            tail = words[i:]
            if not tail:
                break
            variants = [" ".join(tail)]
            last = tail[-1]
            if len(last) >= 5:
                variants += [" ".join([*tail[:-1], last[:-1]]), " ".join([*tail[:-1], last[:-2]])]
            for v in variants:
                if len(fold(v)) < 4 or v in self.rules.lm_objects or v in self.rules.lm_prepositions:
                    continue  # «магазин», «школы» без названия: объектов такого вида в городе много
                hits = self.store.pois(v, city.id)
                if not hits:
                    continue
                dists = {p.district_id for p in hits}
                if len(dists) == 1 and None not in dists:
                    tr.notes.append(f"ориентир {v!r}: {len(hits)} объект(ов) в одном районе")
                    return next(iter(dists))
                tr.notes.append(f"ориентир {v!r}: объекты в {len(dists)} районах, район не берём")
                return None
        return None
