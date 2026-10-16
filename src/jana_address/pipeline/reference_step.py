"""Шаг 8. Восстановление недостающих province, city, district, living_area, street_type по справочнику.

Заполняются только пустые поля. Значение из строки никогда не перезаписывается справочным
(это гарантирует ParseState.set_field). Источник поля: reference:<seed|osm|kato>.
Цепочки: город -> область; район -> город, область; мкр -> район, город; улица (+дом) -> район, тип,
город (если улица уникальна в справочнике или подсказана районом).
"""

from __future__ import annotations

from collections import Counter

from ..reference.store import Entity, Store, get_store
from .base import SOURCE_STRING, ParseState, StepTrace

AREA_TYPES = frozenset(
    {"микрорайон", "квартал", "жилой массив", "жилой комплекс", "дачный массив", "разъезд", "промзона"}
)
DOMINANT_SHARE = 0.8


class Reference:
    name = "reference"

    def __init__(self, store: Store | None = None) -> None:
        self.store = store or get_store()

    def _fill(
        self,
        state: ParseState,
        fname: str,
        e: Entity | None,
        tr: StepTrace,
        value: str | None = None,
        score: float = 0.8,
    ) -> bool:
        if e is None:
            return False
        v = value or e.name
        if state.set_field(fname, v, source=e.ref_source, score=score):
            tr.notes.append(f"{fname} <- {v!r} ({e.ref_source}, {e.etype}#{e.id})")
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
            self._fill(state, "city", city, tr)

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
                    self._fill(state, "city", city, tr, score=0.7)

        # улица
        street_name = state.get("street_name")
        streets: list[Entity] = []
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
                    if self._fill(state, "city", city, tr, score=0.6):
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
                if not state.has("street_type"):
                    types = {st.kind for st in streets if st.kind}
                    if len(types) == 1:
                        self._fill(state, "street_type", streets[0], tr, value=next(iter(types)), score=0.7)
            elif city is not None:
                state.flags.add("street_not_in_reference")

        # область
        if prov is None:
            if city is not None:
                prov = s.province_of(city)
            elif dist is not None:
                prov = s.get("province", dist.province_id)
            elif area is not None:
                prov = s.get("province", area.province_id)
            self._fill(state, "province", prov, tr)
        elif not state.has("province"):
            self._fill(state, "province", prov, tr)  # город респ. значения: province = город
        elif (
            city is not None
            and city.province_id != prov.id
            and state.fields.get("city", None) is not None
            and state.fields["city"].source == SOURCE_STRING
            and state.fields["province"].source == SOURCE_STRING
        ):
            state.flags.add("city_province_conflict")

        # район
        if not state.has("district"):
            did: int | None = None
            house = state.get("house")
            if streets and house:
                for st in streets:
                    h = s.house(st.id, house)
                    if h and h[0]:
                        did = h[0]
                        state.flags.add("house_in_reference")
                        if h[1] and not state.has("living_area") and state.get("street_type") not in AREA_TYPES:
                            self._fill(state, "living_area", s.get("living_area", h[1]), tr, score=0.6)
                        break
            if did is None and area is not None and area.district_id:
                did = area.district_id
            if did is None and streets:
                weights: Counter[int] = Counter()
                for st in streets:
                    for d, w in s.street_districts.get(st.id, ()):
                        weights[d] += w
                if weights:
                    top, w = weights.most_common(1)[0]
                    if w / sum(weights.values()) >= DOMINANT_SHARE:
                        did = top
                    else:
                        state.flags.add("district_ambiguous")
                        tr.notes.append(f"улица в нескольких районах: {len(weights)}, district не ставим")
            if did is None and city is not None and city.district_id:
                did = city.district_id  # посёлок -> район области
            if did is not None:
                self._fill(state, "district", s.get("district", did), tr, score=0.7)
        state.trace.append(tr)
        return state
