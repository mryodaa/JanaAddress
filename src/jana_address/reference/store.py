"""Справочник: read-only SQLite (reference/reference.sqlite), поднятый в память при старте.

Малые таблицы (области, районы, города, микрорайоны, улицы, алиасы) живут в памяти с индексами
по fold-ключу. Дома запрашиваются из SQLite по (street_id, номер) с индексом.
Индексы строятся только по топонимам. Целых адресных строк в справочнике нет (ТЗ, раздел 7).
"""

from __future__ import annotations

import json
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
        for eid, key in con.execute("SELECT eid, key FROM aliases WHERE etype = 'street'"):
            st = self.entities[("street", eid)]
            self.streets_by_city[st.city_id][key].append(eid)
            self.street_keys_global[key].append(eid)
        self.street_districts: dict[int, list[tuple[int, int]]] = defaultdict(list)
        for sid, did, w in con.execute("SELECT street_id, district_id, weight FROM street_districts"):
            self.street_districts[sid].append((did, w))
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
        for k in keys(text):
            for etype, eid in self.alias.get(k, ()):
                if etype in etypes:
                    e = self.entities[(etype, eid)]
                    if e not in out:
                        out.append(e)
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
        ids: list[int] = []
        for k in keys(name):
            src = self.streets_by_city.get(city_id, {}) if city_id is not None else self.street_keys_global
            ids.extend(i for i in src.get(k, ()) if i not in ids)
        return [self.entities[("street", i)] for i in ids]

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

    def house(self, street_id: int, number: str) -> tuple[int | None, int | None] | None:
        """(district_id, living_area_id) дома или None, если дома нет в справочнике."""
        key = fold(number).replace(" ", "")
        row = (
            self._con()
            .execute(
                "SELECT district_id, living_area_id FROM houses WHERE street_id = ? AND key = ? LIMIT 1",
                (street_id, key),
            )
            .fetchone()
        )
        return (row[0], row[1]) if row else None


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
