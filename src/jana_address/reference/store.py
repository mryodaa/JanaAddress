"""Справочник: read-only SQLite (reference/reference.sqlite), поднятый в память при старте.

Малые таблицы (области, районы, города, микрорайоны, улицы, алиасы) живут в памяти с индексами
по fold-ключу. Дома, доли улиц по районам/мкр, объекты-ориентиры запрашиваются из SQLite лениво по индексам.
Геометрии в рантайме нет: все привязки посчитаны при сборке (scripts/build_reference/assign_districts.py).
Индексы строятся только по топонимам. Целых адресных строк в справочнике нет (ТЗ, раздел 7).
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz, process

from .. import config
from .normalize import fold, keys

# номер дома без корпуса/строения: «5 корп 2» -> «5», «11к2» -> «11», «30/1 стр. 2» -> «30/1»
_HOUSE_BASE = re.compile(r"^\s*(\d+(?:[ -]?[^\W\d_](?![^\W\d_]|\d))?(?:/\d+(?:[ -]?[^\W\d_](?![^\W\d_]|\d))?)?)")


@dataclass(frozen=True)
class Entity:
    etype: str  # province | district | city | living_area | street
    id: int
    name: str
    kind: str | None = None  # province: oblast|city; district: oblast|city; city: republican|city|town|village
    province_id: int | None = None
    city_id: int | None = None
    district_id: int | None = None
    source: str = "seed"

    @property
    def ref_source(self) -> str:
        return f"reference:{self.source}"


def ref_source(origin: str, via: str | None = None) -> str:
    """Источник восстановленного поля: reference:osm:<house|street|polygon|point|poi>, reference:seed,
    reference:kato. Способ (via) пишется только у OSM: у ядра и КАТО привязка табличная."""
    return f"reference:{origin}:{via}" if origin == "osm" and via else f"reference:{origin}"


@dataclass(frozen=True)
class House:
    district_id: int | None
    living_area_id: int | None
    source: str
    la_method: str | None = None  # polygon | point (мкр по ближайшей place-точке)


@dataclass(frozen=True)
class StreetInfo:
    type_share: float | None
    dom_district_id: int | None
    dom_district_share: float | None
    dom_area_id: int | None
    dom_area_share: float | None
    houses: int | None


@dataclass(frozen=True)
class Poi:
    id: int
    name: str
    kind: str
    brand: str | None
    district_id: int | None
    living_area_id: int | None


class Store:
    def __init__(self, path: Path) -> None:
        self.path = path
        uri = f"file:{path.as_posix()}?mode=ro&immutable=1"
        self._local = threading.local()
        self._uri = uri
        con = self._con()
        self.meta: dict[str, Any] = {k: json.loads(v) for k, v in con.execute("SELECT key, value FROM meta")}
        self.entities: dict[tuple[str, int], Entity] = {}
        for row in con.execute("SELECT id, name, kind, source FROM provinces"):
            self._put(Entity("province", row[0], row[1], row[2], province_id=row[0], source=row[3]))
        for row in con.execute("SELECT id, name, kind, province_id, city_id, source FROM districts"):
            self._put(Entity("district", row[0], row[1], row[2], row[3], row[4], row[0], source=row[5]))
        for row in con.execute("SELECT id, name, kind, province_id, district_id, source FROM cities"):
            self._put(Entity("city", row[0], row[1], row[2], row[3], row[0], row[4], source=row[5]))
        for row in con.execute(
            "SELECT a.id, a.name, a.type, c.province_id, a.city_id, a.district_id, a.source "
            "FROM living_areas a LEFT JOIN cities c ON c.id = a.city_id"
        ):
            self._put(Entity("living_area", row[0], row[1], row[2], row[3], row[4], row[5], source=row[6]))
        for row in con.execute(
            "SELECT s.id, s.name, s.type, c.province_id, s.city_id, s.source "
            "FROM streets s LEFT JOIN cities c ON c.id = s.city_id"
        ):
            self._put(Entity("street", row[0], row[1], row[2], row[3], row[4], None, source=row[5]))

        self.province_center: dict[int, int] = {
            r[0]: r[1] for r in con.execute("SELECT id, center_city_id FROM provinces") if r[1]
        }
        # алиасы: key -> [(etype, id)]
        self.alias: dict[str, list[tuple[str, int]]] = defaultdict(list)
        for etype, eid, key in con.execute("SELECT etype, eid, key FROM aliases"):
            if (etype, eid) not in self.alias[key]:
                self.alias[key].append((etype, eid))
        # улицы по городу: city_id -> key -> [street_id]
        self.streets_by_city: dict[int | None, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
        self.street_keys_global: dict[str, list[int]] = defaultdict(list)
        # старые названия улиц (old_name OSM) отдельно: старое имя одной улицы бывает текущим у другой
        # («Бердибай», бывшая «Толе би»), поэтому по нему ищем, только если текущих совпадений нет
        self.old_streets_by_city: dict[int | None, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
        self.old_street_keys_global: dict[str, list[int]] = defaultdict(list)
        for eid, key, lang in con.execute("SELECT eid, key, lang FROM aliases WHERE etype = 'street'"):
            st = self.entities[("street", eid)]
            if lang == "old":
                self.old_streets_by_city[st.city_id][key].append(eid)
                self.old_street_keys_global[key].append(eid)
            else:
                self.streets_by_city[st.city_id][key].append(eid)
                self.street_keys_global[key].append(eid)
        # доли улиц по районам/мкр, дома, объекты и метод привязки пункта запрашиваются лениво по индексам:
        # в память при старте не грузятся. Старая схема (до street_areas/pois) читается тоже.
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        self._v2 = "street_areas" in tables
        # ключи по типам для нечёткого поиска
        self._keys_by_type: dict[str, list[str]] = defaultdict(list)
        for key, items in self.alias.items():
            for etype in {e for e, _ in items}:
                if etype != "street":
                    self._keys_by_type[etype].append(key)
        self.n_houses = con.execute("SELECT count(*) FROM houses").fetchone()[0]

    # ---------- служебное ----------
    def _put(self, e: Entity) -> None:
        self.entities[(e.etype, e.id)] = e

    def _con(self) -> sqlite3.Connection:
        con: sqlite3.Connection | None = getattr(self._local, "con", None)
        if con is None:
            con = sqlite3.connect(self._uri, uri=True, check_same_thread=False)
            self._local.con = con
        return con

    def get(self, etype: str, eid: int | None) -> Entity | None:
        return self.entities.get((etype, eid)) if eid is not None else None

    def stats(self) -> dict[str, Any]:
        counts: dict[str, int] = defaultdict(int)
        for etype, _ in self.entities:
            counts[etype] += 1
        return {
            "file": self.path.name,
            "counts": dict(counts),
            "houses": self.n_houses,
            "built_at": self.meta.get("built_at"),
            "sources": self.meta.get("sources"),
        }

    # ---------- поиск ----------
    def lookup(self, text: str, etypes: tuple[str, ...]) -> list[Entity]:
        """Точное + нормализованное совпадение по алиасам (fold, транслит)."""
        out: list[Entity] = []
        seen: set[tuple[str, int]] = set()  # у частых имён («Абая») тысячи улиц: проверка по списку была бы O(n²)
        for k in keys(text):
            for etype, eid in self.alias.get(k, ()):
                if etype in etypes and (etype, eid) not in seen:
                    seen.add((etype, eid))
                    out.append(self.entities[(etype, eid)])
        return out

    def fuzzy(
        self, text: str, etype: str, cutoff: float = 88.0, within: list[Entity] | None = None
    ) -> tuple[Entity, float] | None:
        """Нечёткий поиск rapidfuzz по алиасам типа etype (или среди кандидатов within)."""
        k = fold(text)
        if len(k) < 4:
            return None
        if within is not None:
            choices = {fold(e.name): e for e in within}
            m = process.extractOne(k, list(choices), scorer=fuzz.ratio, score_cutoff=cutoff)
            return (choices[m[0]], float(m[1])) if m else None
        m = process.extractOne(k, self._keys_by_type.get(etype, []), scorer=fuzz.ratio, score_cutoff=cutoff)
        if not m:
            return None
        for et, eid in self.alias[m[0]]:
            if et == etype:
                return self.entities[(et, eid)], float(m[1])
        return None

    def province_of(self, e: Entity) -> Entity | None:
        return self.get("province", e.province_id)

    def city_of_province(self, prov: Entity) -> Entity | None:
        """Для города респ. значения province == city."""
        return self.get("city", self.province_center.get(prov.id)) if prov.kind == "city" else None

    def streets(self, name: str, city_id: int | None) -> list[Entity]:
        """Улицы по текущему названию (рус/каз/лат); нет таких: по старому названию."""
        for by_city, glob in (
            (self.streets_by_city, self.street_keys_global),
            (self.old_streets_by_city, self.old_street_keys_global),
        ):
            src = by_city.get(city_id, {}) if city_id is not None else glob
            ids = list(dict.fromkeys(i for k in keys(name) for i in src.get(k, ())))  # без O(n²) у «Абая»
            if ids:
                return [self.entities[("street", i)] for i in ids]
        return []

    def street_fuzzy(self, name: str, city_id: int, cutoff: float = 90.0) -> tuple[list[Entity], float] | None:
        cand = self.streets_by_city.get(city_id)
        if not cand:
            return None
        k = fold(name)
        if len(k) < 5:
            return None
        m = process.extractOne(k, list(cand), scorer=fuzz.ratio, score_cutoff=cutoff)
        if not m:
            return None
        return [self.entities[("street", i)] for i in cand[m[0]]], float(m[1])

    def house(self, street_id: int, number: str) -> House | None:
        """Дом из справочника или None. «5 корп 2», «11к2», «30/1 стр. 2»: если с корпусом не нашёлся,
        ищем номер без корпуса (участок и район у них общие)."""
        keys_ = [fold(number).replace(" ", "")]
        base = _HOUSE_BASE.match(number)
        if base and fold(base.group(1)).replace(" ", "") != keys_[0]:
            keys_.append(fold(base.group(1)).replace(" ", ""))
        con = self._con()
        cols = "district_id, living_area_id, source" + (", la_method" if self._v2 else "")
        for key in keys_:
            row = con.execute(
                f"SELECT {cols} FROM houses WHERE street_id = ? AND key = ? LIMIT 1", (street_id, key)
            ).fetchone()
            if row:
                return House(row[0], row[1], row[2], row[3] if self._v2 else None)
        return None

    def street_info(self, street_id: int) -> StreetInfo | None:
        """Доля типа среди одноимённых улиц города и доминирующие район / мкр (посчитаны при сборке)."""
        if not self._v2:
            return None
        row = (
            self._con()
            .execute(
                "SELECT type_share, dom_district_id, dom_district_share, dom_area_id, dom_area_share, houses "
                "FROM streets WHERE id = ?",
                (street_id,),
            )
            .fetchone()
        )
        return StreetInfo(*row) if row else None

    def district_shares(self, street_id: int) -> list[tuple[int, float, int]]:
        """[(district_id, доля, домов)] улицы: доли по домам (если их >= 3) или по длине сегментов."""
        con = self._con()
        if self._v2:
            q = "SELECT district_id, share, houses FROM street_districts WHERE street_id = ?"
            return [(d, float(s or 0.0), int(h or 0)) for d, s, h in con.execute(q, (street_id,))]
        rows = list(con.execute("SELECT district_id, weight FROM street_districts WHERE street_id = ?", (street_id,)))
        total = sum(w for _, w in rows) or 1
        return [(d, w / total, int(w)) for d, w in rows]

    def area_shares(self, street_id: int) -> list[tuple[int, float, int]]:
        if not self._v2:
            return []
        q = "SELECT area_id, share, houses FROM street_areas WHERE street_id = ?"
        return [(a, float(s or 0.0), int(h or 0)) for a, s, h in self._con().execute(q, (street_id,))]

    def city_district_method(self, city_id: int) -> str | None:
        """Как найден район области у пункта: polygon | near (OSM), seed, kato."""
        if not self._v2:
            return None
        row = self._con().execute("SELECT district_method FROM cities WHERE id = ?", (city_id,)).fetchone()
        return row[0] if row else None

    def pois(self, text: str, city_id: int) -> list[Poi]:
        """Объекты-ориентиры города по названию или бренду (fold/транслит), без нечёткого поиска."""
        if not self._v2:
            return []
        out: dict[int, Poi] = {}
        con = self._con()
        for k in keys(text):
            for row in con.execute(
                "SELECT p.id, p.name, p.kind, p.brand, p.district_id, p.living_area_id FROM poi_aliases a "
                "JOIN pois p ON p.id = a.poi_id WHERE a.key = ? AND p.city_id = ? LIMIT 200",
                (k, city_id),
            ):
                out.setdefault(row[0], Poi(*row))
        return list(out.values())


_store: Store | None = None
_lock = threading.Lock()


def is_available() -> bool:
    return config.REFERENCE_DB.exists()


def get_store() -> Store:
    global _store
    if _store is None:
        with _lock:
            if _store is None:
                if not is_available():
                    raise FileNotFoundError(f"справочник не найден: {config.REFERENCE_DB}")
                _store = Store(config.REFERENCE_DB)
    return _store


@lru_cache(maxsize=1)
def ambiguous_city_keys() -> frozenset[str]:
    """Названия городов, совпадающие с улицами/районами/микрорайонами: без маркера «г.» их не берём."""
    s = get_store()
    out: set[str] = set()
    for key, items in s.alias.items():
        types = {e for e, _ in items}
        if "city" in types and types - {"city", "province", "district"}:  # район берётся только с маркером
            out.add(key)
    for key in s.street_keys_global:
        if any(e == "city" for e, _ in s.alias.get(key, ())):
            out.add(key)
    # города респ. значения и областные центры: улицы «Алматы»/«Астана» есть почти везде, но без маркера
    # в начале адреса это всё равно город (защита «Туркестан 12» = улица держится на правиле номера)
    major = {s.province_center[p] for p in s.province_center}
    for cid in major:
        city = s.get("city", cid)
        if city is not None:
            for k in keys(city.name):
                out.discard(k)
            for key, items in s.alias.items():
                if ("city", cid) in items:
                    out.discard(key)
    return frozenset(out)
