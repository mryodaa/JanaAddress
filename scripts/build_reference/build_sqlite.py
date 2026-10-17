"""Сборка reference/reference.sqlite из ядра (seed/*.yaml) и, если есть, выгрузок OSM и КАТО.

    python scripts/build_reference/build_sqlite.py                       # только ядро
    python scripts/build_reference/build_sqlite.py --osm cache/osm_assigned --kato cache/kato.json

Промежуточный формат OSM/КАТО (готовят osm_extract.py + assign_districts.py, kato.py) ссылается на
сущности по названиям: {"provinces": [...], "districts": [...], "cities": [...], "living_areas": [...],
"streets": [...], "houses": [...], "pois": [...]}. OSM приходит каталогом: meta.json + streets/houses/pois.jsonl
(дома читаются потоком). Алиасы: строка или [текст, язык]. Ядро имеет приоритет: его названия канонические
для ответа. Вся геометрия уже посчитана в assign_districts.py: здесь только слияние по названиям и id.
Скрипт пишет статистику покрытия в reference/coverage.json (идёт в docs/REFERENCE.md).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from jana_address.reference.normalize import fold, keys  # noqa: E402

HERE = Path(__file__).resolve().parent
OUT = ROOT / "reference" / "reference.sqlite"
_PROV_WORDS = re.compile(r"\s*(область|облысы|обл\.?)\s*", re.I)
_DIST_WORDS = re.compile(r"\s*(район|ауданы|р-н)\s*", re.I)


_POSTCODE = re.compile(r"\b\d{6}\b")
# адрес в имени объекта OSM («переулок Кузнечный дом 28 кв.12»): номер дома / квартиры с маркером
_ADDR_PART = re.compile(r"(^|\s)(дом|д|кв|квартира)\.?\s*\d", re.I)

Alias = str | list[str] | tuple[str, ...]
MERGE_LANGS = frozenset({"ru", "kk", "en", "official", "short"})  # языки алиасов, по которым сливаются улицы


def toponym_ok(name: str | None) -> bool:
    """Отсев мусора OSM: целые адреса в addr:street («Gogol St 15, Almaty, Kazakhstan») и т.п.
    Справочник хранит только топонимы, поэтому запятые, индексы и длинные строки не берём."""
    return (
        bool(name)
        and "," not in name  # type: ignore[operator]
        and len(name) <= 60  # type: ignore[arg-type]
        and not _POSTCODE.search(name)  # type: ignore[arg-type]
        and not _ADDR_PART.search(name)  # type: ignore[arg-type]
    )


def province_key(name: str) -> str:
    return fold(_PROV_WORDS.sub(" ", name)).strip()


def district_key(name: str) -> str:
    """Ключ слияния районов ядра, КАТО и OSM: без «район», мягкого знака и окончания прилагательного
    («Аксуатский» = «Ақсуат», «Теренкольский» = «Тереңкөл», «Аккулинский» = «Аққулы»). Сливаются только
    районы одной области / одного города, поэтому такой грубый ключ не склеивает разные районы."""
    k = fold(_DIST_WORDS.sub(" ", name)).strip().replace("ь", "")
    return re.sub(r"(инский|ынский|ский|цкий|ы)$", "", k) or k


def norm_aliases(items: Iterable[Alias] | None, lang: str = "ru") -> list[tuple[str, str]]:
    """Алиас строкой (ядро, КАТО) или парой [текст, язык] (OSM: язык по ключу тега)."""
    out: list[tuple[str, str]] = []
    for a in items or ():
        if isinstance(a, list | tuple):
            if a and a[0]:
                out.append((str(a[0]), str(a[1]) if len(a) > 1 and a[1] else lang))
        elif a:
            out.append((str(a), lang))
    return out


@dataclass
class Builder:
    provinces: list[dict[str, Any]] = field(default_factory=list)
    districts: list[dict[str, Any]] = field(default_factory=list)
    cities: list[dict[str, Any]] = field(default_factory=list)
    areas: list[dict[str, Any]] = field(default_factory=list)
    streets: list[dict[str, Any]] = field(default_factory=list)
    # (street_id, district_id) -> [дома, длина м, доля]
    street_districts: dict[tuple[int, int], list[float]] = field(default_factory=dict)
    street_areas: dict[tuple[int, int], list[float]] = field(default_factory=dict)
    # дома кортежами (street_id, number, key, district_id, living_area_id, source, la_method, la_dist_m):
    # их больше миллиона, dict на каждый не помещается в память сборочной машины
    houses: list[tuple[Any, ...]] = field(default_factory=list)
    pois: list[tuple[Any, ...]] = field(default_factory=list)
    poi_aliases: list[tuple[str, int]] = field(default_factory=list)
    aliases: list[tuple[str, int, str, str, str, str]] = field(default_factory=list)
    _alias_seen: set[tuple[str, int, str]] = field(default_factory=set)
    _by: dict[tuple[str, Any, str], int] = field(default_factory=dict)  # (etype, scope, key) -> id
    _house_seen: set[tuple[int, str]] = field(default_factory=set)

    # ---------- общие ----------
    def alias(self, etype: str, eid: int, text: str | None, lang: str = "ru", source: str = "seed") -> None:
        if not text or not str(text).strip() or not toponym_ok(str(text)):
            return
        text = str(text).strip()
        for k in keys(text):
            if not k or (etype, eid, k) in self._alias_seen:
                continue
            self._alias_seen.add((etype, eid, k))
            self.aliases.append((etype, eid, text, k, lang, source))

    def find(self, etype: str, scope: Any, name: str) -> int | None:
        k = province_key(name) if etype == "province" else district_key(name) if etype == "district" else fold(name)
        return self._by.get((etype, scope, k))

    def _register(self, etype: str, scope: Any, name: str, eid: int) -> None:
        k = province_key(name) if etype == "province" else district_key(name) if etype == "district" else fold(name)
        self._by.setdefault((etype, scope, k), eid)

    # ---------- сущности ----------
    def province(self, name: str, kind: str, source: str, aliases: Iterable[Alias] = (), **kw: Any) -> int:
        pid = self.find("province", None, name)
        if pid is None:
            pid = len(self.provinces) + 1
            self.provinces.append(
                {
                    "id": pid,
                    "name": name,
                    "kind": kind,
                    "source": source,
                    "center_city_id": None,
                    "osm_id": kw.get("osm_id"),
                    "kato": kw.get("kato"),
                }
            )
            self._register("province", None, name, pid)
        else:
            row = self.provinces[pid - 1]
            row["osm_id"] = row["osm_id"] or kw.get("osm_id")
            row["kato"] = row["kato"] or kw.get("kato")
        self.alias("province", pid, name, source=source)
        for a, lang in norm_aliases(aliases, kw.get("lang", "ru")):
            self.alias("province", pid, a, lang=lang, source=source)
            # алиасы регистрируем без снятия «облысы»: «Алматы облысы» не должен совпасть с городом Алматы
            self._by.setdefault(("province", None, fold(a)), pid)
        return pid

    def district(
        self,
        name: str,
        kind: str,
        province_id: int | None,
        city_id: int | None,
        source: str,
        aliases: Iterable[Alias] = (),
        **kw: Any,
    ) -> int:
        scope = ("c", city_id) if city_id else ("p", province_id)
        did = self.find("district", scope, name)
        if did is None:
            did = len(self.districts) + 1
            self.districts.append(
                {
                    "id": did,
                    "name": name,
                    "kind": kind,
                    "province_id": province_id,
                    "city_id": city_id,
                    "source": source,
                    "osm_id": kw.get("osm_id"),
                    "kato": kw.get("kato"),
                }
            )
            self._register("district", scope, name, did)
        else:
            row = self.districts[did - 1]
            row["osm_id"] = row["osm_id"] or kw.get("osm_id")
            row["kato"] = row["kato"] or kw.get("kato")
        for a, lang in [(name, "ru"), *norm_aliases(aliases, kw.get("lang", "ru"))]:
            self.alias("district", did, a, lang=lang, source=source)
            self._register("district", scope, a, did)
        return did

    def city(
        self,
        name: str,
        kind: str,
        province_id: int | None,
        source: str,
        district_id: int | None = None,
        aliases: Iterable[Alias] = (),
        **kw: Any,
    ) -> int:
        cid = self.find("city", province_id, name)
        if cid is not None and district_id and self.cities[cid - 1]["district_id"] not in (None, district_id):
            # одноимённое село в другом районе той же области («Акжар»): отдельная сущность, иначе улицы и
            # район двух сёл сливаются; выбор между ними делают район и улица записи (admin._prefer)
            cid = self._by.get(("city", (province_id, district_id), fold(name)))
        if cid is None:
            cid = len(self.cities) + 1
            self.cities.append(
                {
                    "id": cid,
                    "name": name,
                    "kind": kind,
                    "province_id": province_id,
                    "district_id": district_id,
                    "source": source,
                    "osm_id": kw.get("osm_id"),
                    "kato": kw.get("kato"),
                    "lat": kw.get("lat"),
                    "lon": kw.get("lon"),
                    "population": kw.get("population"),
                    "district_method": kw.get("district_method") if district_id else None,
                }
            )
            self._register("city", province_id, name, cid)
            if district_id:
                self._by.setdefault(("city", (province_id, district_id), fold(name)), cid)
        else:
            row = self.cities[cid - 1]
            for k in ("osm_id", "kato", "lat", "lon", "population"):
                row[k] = row[k] or kw.get(k)
            if not row["district_id"] and district_id:
                row["district_id"] = district_id
                row["district_method"] = kw.get("district_method")
        for a, lang in [(name, "ru"), *norm_aliases(aliases, kw.get("lang", "ru"))]:
            self.alias("city", cid, a, lang=lang, source=source)
            self._register("city", province_id, a, cid)
        return cid

    def area(
        self,
        name: str,
        typ: str,
        city_id: int | None,
        district_id: int | None,
        source: str,
        aliases: Iterable[Alias] = (),
        **kw: Any,
    ) -> int:
        aid = self.find("living_area", city_id, name)
        if aid is None:
            aid = len(self.areas) + 1
            self.areas.append(
                {
                    "id": aid,
                    "name": name,
                    "type": typ,
                    "city_id": city_id,
                    "district_id": district_id,
                    "source": source,
                    "osm_id": kw.get("osm_id"),
                }
            )
            self._register("living_area", city_id, name, aid)
        else:
            row = self.areas[aid - 1]
            row["district_id"] = row["district_id"] or district_id
        for a, lang in [(name, "ru"), *norm_aliases(aliases, kw.get("lang", "ru"))]:
            self.alias("living_area", aid, a, lang=lang, source=source)
            self._register("living_area", city_id, a, aid)
        return aid

    def street(
        self, name: str, typ: str | None, city_id: int | None, source: str, aliases: Iterable[Alias] = (), **kw: Any
    ) -> int:
        scope = (city_id, typ)
        sid = self.find("street", scope, name)
        if sid is None:
            sid = len(self.streets) + 1
            self.streets.append(
                {
                    "id": sid,
                    "name": name,
                    "type": typ,
                    "city_id": city_id,
                    "source": source,
                    "length_m": kw.get("length_m"),
                    "houses": kw.get("houses"),
                    "type_share": kw.get("type_share"),
                    "dom_district_id": None,
                    "dom_district_share": None,
                    "dom_area_id": None,
                    "dom_area_share": None,
                }
            )
            self._register("street", scope, name, sid)
        else:
            row = self.streets[sid - 1]
            for k in ("length_m", "houses"):
                if kw.get(k) is not None:
                    row[k] = (row[k] or 0) + kw[k]
        self.alias("street", sid, name, source=source)
        for a, lang in norm_aliases(aliases, kw.get("lang", "ru")):
            self.alias("street", sid, a, lang=lang, source=source)
            # «Абай даңғылы» и «проспект Абая» одна улица: сливаем по переводам имени, но не по старым и
            # альтернативным именам: старое имя одной улицы бывает текущим у другой («Бердибай», бывшая «Толе би»)
            if lang in MERGE_LANGS:
                self._register("street", scope, a, sid)
        return sid

    def house(
        self,
        street_id: int,
        number: str,
        district_id: int | None,
        area_id: int | None,
        source: str,
        la_method: str | None = None,
        la_dist_m: float | None = None,
    ) -> None:
        key = fold(number).replace(" ", "")
        if (street_id, key) in self._house_seen:
            return
        self._house_seen.add((street_id, key))
        self.houses.append(
            (street_id, number, key, district_id, area_id, source, la_method if area_id else None, la_dist_m)
        )

    def poi(
        self,
        name: str,
        kind: str,
        brand: str | None,
        city_id: int,
        district_id: int | None,
        area_id: int | None,
        source: str,
        aliases: Iterable[Alias] = (),
    ) -> None:
        pid = len(self.pois) + 1
        self.pois.append((pid, name, kind, brand, city_id, district_id, area_id, source))
        seen: set[str] = set()
        for a, _ in [(name, "ru"), *norm_aliases(aliases), *([(brand, "ru")] if brand else [])]:
            if not toponym_ok(a):
                continue
            for k in keys(a):
                if k and k not in seen:
                    seen.add(k)
                    self.poi_aliases.append((k, pid))

    def finalize_streets(self) -> None:
        """Доминирующий район и мкр улицы (лучший кандидат и его доля) для быстрого ответа в рантайме."""
        best_d: dict[int, tuple[float, int]] = {}
        for (sid, did), (_, _, share) in self.street_districts.items():
            if sid not in best_d or share > best_d[sid][0]:
                best_d[sid] = (share, did)
        best_a: dict[int, tuple[float, int]] = {}
        for (sid, aid), (_, _, share) in self.street_areas.items():
            if sid not in best_a or share > best_a[sid][0]:
                best_a[sid] = (share, aid)
        for s in self.streets:
            if s["id"] in best_d:
                s["dom_district_share"], s["dom_district_id"] = best_d[s["id"]]
            if s["id"] in best_a:
                s["dom_area_share"], s["dom_area_id"] = best_a[s["id"]]

    # ---------- вывод ----------
    def write(self, path: Path, meta: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        if tmp.exists():
            tmp.unlink()
        con = sqlite3.connect(tmp)
        con.executescript((HERE / "schema.sql").read_text(encoding="utf-8"))

        def ins(table: str, rows: list[dict[str, Any]]) -> None:
            if not rows:
                return
            cols = list(rows[0].keys())
            con.executemany(
                f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                [tuple(r[c] for c in cols) for r in rows],
            )

        ins("provinces", self.provinces)
        ins("districts", self.districts)
        ins("cities", self.cities)
        ins("living_areas", self.areas)
        ins("streets", self.streets)
        con.executemany(
            "INSERT INTO street_districts VALUES (?,?,?,?,?,?)",
            [(s, d, max(1, round(v[2] * 1000)), int(v[0]), v[1], v[2]) for (s, d), v in self.street_districts.items()],
        )
        con.executemany(
            "INSERT INTO street_areas VALUES (?,?,?,?,?)",
            [(s, a, int(v[0]), v[1], v[2]) for (s, a), v in self.street_areas.items()],
        )
        con.executemany("INSERT INTO houses VALUES (?,?,?,?,?,?,?,?)", self.houses)
        con.executemany("INSERT INTO pois VALUES (?,?,?,?,?,?,?,?)", self.pois)
        con.executemany("INSERT INTO poi_aliases VALUES (?,?)", self.poi_aliases)
        con.executemany("INSERT INTO aliases VALUES (?,?,?,?,?,?)", self.aliases)
        con.executemany(
            "INSERT INTO meta VALUES (?,?)", [(k, json.dumps(v, ensure_ascii=False)) for k, v in meta.items()]
        )
        con.executescript(
            """
            CREATE INDEX ix_alias_key ON aliases(key, etype);
            CREATE INDEX ix_alias_e ON aliases(etype, eid);
            CREATE INDEX ix_house ON houses(street_id, key);
            CREATE INDEX ix_street_city ON streets(city_id);
            CREATE INDEX ix_poi_alias ON poi_aliases(key);
            """
        )
        con.commit()
        con.execute("VACUUM")
        con.close()
        if path.exists():
            path.unlink()
        tmp.rename(path)


def load_seed(b: Builder, seed_dir: Path) -> None:
    data = yaml.safe_load((seed_dir / "admin.yaml").read_text(encoding="utf-8"))
    centers: dict[int, str] = {}
    for p in data["provinces"]:
        kk = p.get("kk", "")
        kk_short = kk.replace(" облысы", "")  # «Ақтөбе» рядом с маркером «облысы»
        pid = b.province(p["name"], "oblast", "seed", [p.get("short", ""), [kk, "kk"], *p.get("aliases", [])])
        # только алиас для поиска рядом с маркером; в слияние не регистрируем («Алматы» != Алматинская обл.)
        b.alias("province", pid, kk_short, lang="kk")
        centers[pid] = p["center"]
    for rc in data["republican_cities"]:
        al = [[rc.get("kk", ""), "kk"], *rc.get("aliases", [])]
        pid = b.province(rc["name"], "city", "seed", al)
        cid = b.city(rc["name"], "republican", pid, "seed", aliases=al)
        b.provinces[pid - 1]["center_city_id"] = cid
        for d in rc.get("districts", []):
            b.district(d["name"], "city", pid, cid, "seed", d.get("aliases", []))
    for prov, dists in (data.get("oblast_districts") or {}).items():
        pid = b.find("province", None, prov)
        assert pid, prov
        for d in dists:
            b.district(d["name"], "oblast", pid, None, "seed", d.get("aliases", []))
    for c in data["cities"]:
        pid = b.find("province", None, c["province"])
        assert pid, c
        did = b.find("district", ("p", pid), c["district"]) if c.get("district") else None
        b.city(c["name"], c.get("kind", "city"), pid, "seed", did, c.get("aliases", []), district_method="seed")
    for pid, center in centers.items():
        b.provinces[pid - 1]["center_city_id"] = b.find("city", pid, center)
    for city, dists in (data.get("city_districts") or {}).items():
        cid = next(c["id"] for c in b.cities if c["name"] == city)
        pid = b.cities[cid - 1]["province_id"]
        for d in dists:
            b.district(d["name"], "city", pid, cid, "seed", d.get("aliases", []))
    for city, by_dist in (data.get("living_areas") or {}).items():
        cid = next(c["id"] for c in b.cities if c["name"] == city)
        pid = b.cities[cid - 1]["province_id"]
        for dname, areas in by_dist.items():
            did = b.find("district", ("c", cid), dname)
            for a in areas:
                b.area(a, "микрорайон", cid, did, "seed", [a.replace("-", " ")])


def _weights(raw: Any) -> Iterator[tuple[str, float, float]]:
    """(имя, дома, длина м) улицы по районам/мкр: формат {имя: {houses, length_m, share}} или старый {имя: вес}.
    Доли пересчитываются после слияния (_recompute_shares)."""
    for name, v in (raw or {}).items():
        if isinstance(v, dict):
            yield name, float(v.get("houses") or 0), float(v.get("length_m") or 0)
        else:
            yield name, float(v), 0.0


def load_external(b: Builder, data: dict[str, Any], source: str, lang: str = "ru") -> None:
    """Слияние выгрузки OSM/КАТО. Сущности ссылаются друг на друга по названиям."""

    def prov_id(name: str | None) -> int | None:
        return b.find("province", None, name) if name else None

    for p in data.get("provinces", []):
        b.province(
            p["name"],
            p.get("kind", "oblast"),
            source,
            p.get("aliases", []),
            osm_id=p.get("osm_id"),
            kato=p.get("kato"),
            lang=lang,
        )
    city_scope: dict[tuple[str | None, str], int] = {}
    by_osm: dict[str, int] = {}  # пункт OSM -> id: одноимённые сёла одной области различаются по osm_id
    # сначала города (нужны для районов городов), районы областей
    for d in data.get("districts", []):
        if d.get("city"):
            continue
        pid = prov_id(d.get("province"))
        if pid:
            b.district(
                d["name"],
                "oblast",
                pid,
                None,
                source,
                d.get("aliases", []),
                osm_id=d.get("osm_id"),
                kato=d.get("kato"),
                lang=lang,
            )
    for c in data.get("cities", []):
        pid = prov_id(c.get("province"))
        if not pid:
            continue
        did = b.find("district", ("p", pid), c["district"]) if c.get("district") else None
        cid = b.city(
            c["name"],
            c.get("kind", "village"),
            pid,
            source,
            did,
            c.get("aliases", []),
            osm_id=c.get("osm_id"),
            kato=c.get("kato"),
            lat=c.get("lat"),
            lon=c.get("lon"),
            population=c.get("population"),
            district_method=c.get("district_method") or source,
            lang=lang,
        )
        city_scope.setdefault((c.get("province"), c["name"]), cid)
        if c.get("osm_id"):
            by_osm[c["osm_id"]] = cid

    def city_id(prov: str | None, name: str | None, osm: str | None = None) -> int | None:
        if osm and osm in by_osm:
            return by_osm[osm]
        if not name:
            return None
        if (prov, name) in city_scope:
            return city_scope[(prov, name)]
        pid = prov_id(prov)
        cid = b.find("city", pid, name)
        if cid is None and pid is None:
            # республиканский город может прийти без области
            cid = next((c["id"] for c in b.cities if fold(c["name"]) == fold(name) and c["kind"] == "republican"), None)
        if cid is not None:
            city_scope[(prov, name)] = cid
        return cid

    for d in data.get("districts", []):
        if not d.get("city"):
            continue
        cid = city_id(d.get("province"), d["city"])
        if cid:
            b.district(
                d["name"],
                "city",
                b.cities[cid - 1]["province_id"],
                cid,
                source,
                d.get("aliases", []),
                osm_id=d.get("osm_id"),
                kato=d.get("kato"),
                lang=lang,
            )

    def dist_id(cid: int | None, prov: str | None, name: str | None) -> int | None:
        if not name:
            return None
        if cid:
            did = b.find("district", ("c", cid), name)
            if did:
                return did
        pid = prov_id(prov) or (b.cities[cid - 1]["province_id"] if cid else None)
        return b.find("district", ("p", pid), name) if pid else None

    for a in data.get("living_areas", []):
        cid = city_id(a.get("province"), a.get("city"), a.get("city_osm"))
        if not cid or not toponym_ok(a["name"]):
            continue
        b.area(
            a["name"],
            a.get("type", "микрорайон"),
            cid,
            dist_id(cid, a.get("province"), a.get("district")),
            source,
            a.get("aliases", []),
            osm_id=a.get("osm_id"),
            lang=lang,
        )

    street_ids: dict[tuple[int, str | None, str], int] = {}
    any_type: dict[tuple[int, str], int] = {}
    for s in data.get("streets", []):
        cid = city_id(s.get("province"), s.get("city"), s.get("city_osm"))
        if not cid or not toponym_ok(s["name"]):
            continue
        sid = b.street(
            s["name"],
            s.get("type"),
            cid,
            source,
            s.get("aliases", []),
            length_m=s.get("length_m"),
            houses=s.get("houses"),
            type_share=s.get("type_share"),
            lang=lang,
        )
        street_ids[(cid, s.get("type"), fold(s["name"]))] = sid
        any_type.setdefault((cid, fold(s["name"])), sid)
        for dname, h, ln in _weights(s.get("districts")):
            did = dist_id(cid, s.get("province"), dname)
            if did:
                cur = b.street_districts.setdefault((sid, did), [0.0, 0.0, 0.0])
                cur[0] += h
                cur[1] += ln
        for aname, h, ln in _weights(s.get("areas")):
            aid = b.find("living_area", cid, aname)
            if aid:
                cur = b.street_areas.setdefault((sid, aid), [0.0, 0.0, 0.0])
                cur[0] += h
                cur[1] += ln
    _recompute_shares(b)
    for h in data.get("houses", []):
        cid = city_id(h.get("province"), h.get("city"), h.get("city_osm"))
        if not cid or not toponym_ok(h["street"]) or len(h["number"]) > 20:
            continue
        key = (cid, h["type"], fold(h["street"])) if "type" in h else None
        sid = street_ids.get(key) if key else any_type.get((cid, fold(h["street"])))
        if not sid:
            continue
        aid = b.find("living_area", cid, h["living_area"]) if h.get("living_area") else None
        b.house(
            sid,
            h["number"],
            dist_id(cid, h.get("province"), h.get("district")),
            aid,
            source,
            h.get("la_method"),
            h.get("la_dist_m"),
        )
    for p in data.get("pois", []):
        cid = city_id(p.get("province"), p.get("city"), p.get("city_osm"))
        if not cid or not toponym_ok(p["name"]):
            continue
        aid = b.find("living_area", cid, p["living_area"]) if p.get("living_area") else None
        b.poi(
            p["name"],
            p["kind"],
            p.get("brand"),
            cid,
            dist_id(cid, p.get("province"), p.get("district")),
            aid,
            source,
            p.get("aliases", []),
        )


def _recompute_shares(b: Builder) -> None:
    """Доли заново по суммам: в одну улицу справочника сливаются несколько записей OSM («Абая» + «Абай»),
    и доля каждой по отдельности уже не верна. Правило то же, что в assign_districts: по домам, если их
    у улицы >= 3, иначе по длине сегментов (старый формат весов: вес лежит в домах)."""
    for table in (b.street_districts, b.street_areas):
        houses: Counter[int] = Counter()
        length: dict[int, float] = defaultdict(float)
        for (sid, _), v in table.items():
            houses[sid] += int(v[0])
            length[sid] += v[1]
        for (sid, _), v in table.items():
            if houses[sid] >= 3 or (houses[sid] and not length[sid]):
                v[2] = round(v[0] / houses[sid], 3)
            elif length[sid]:
                v[2] = round(v[1] / length[sid], 3)


def read_external(path: Path) -> dict[str, Any]:
    """Файл JSON (КАТО, старая выгрузка OSM) или каталог assign_districts.py (meta.json + *.jsonl потоком)."""
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]
    data: dict[str, Any] = json.loads((path / "meta.json").read_text(encoding="utf-8"))

    def stream(name: str) -> Iterator[dict[str, Any]]:
        f = path / name
        if f.exists():
            with f.open(encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        yield json.loads(line)

    data["streets"] = list(stream("streets.jsonl"))  # улицы нужны до домов: по ним ищется street_id
    data["houses"] = stream("houses.jsonl")
    data["pois"] = stream("pois.jsonl")
    return data


def coverage(b: Builder, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    streets_per_city: Counter[int] = Counter(s["city_id"] for s in b.streets)
    sid2city = {s["id"]: s["city_id"] for s in b.streets}
    houses_per_city: Counter[int] = Counter()
    with_district: Counter[int] = Counter()
    with_area: Counter[int] = Counter()
    by_point: Counter[int] = Counter()
    for h in b.houses:
        c = sid2city[h[0]]
        houses_per_city[c] += 1
        with_district[c] += h[3] is not None
        with_area[c] += h[4] is not None
        by_point[c] += h[6] == "point"
    districts_per_city: Counter[int] = Counter(d["city_id"] for d in b.districts if d["city_id"])
    areas_per_city: Counter[int] = Counter(a["city_id"] for a in b.areas)
    pois_per_city: Counter[int] = Counter(p[4] for p in b.pois)
    streets_with_d: Counter[int] = Counter(s["city_id"] for s in b.streets if s["dom_district_id"])

    def row(c: dict[str, Any]) -> dict[str, Any]:
        cid = c["id"]
        return {
            "city": c["name"],
            "kind": c["kind"],
            "districts": districts_per_city[cid],
            "living_areas": areas_per_city[cid],
            "streets": streets_per_city[cid],
            "streets_with_district": streets_with_d[cid],
            "houses": houses_per_city[cid],
            "houses_with_district": with_district[cid],
            "houses_with_living_area": with_area[cid],
            "houses_living_area_by_point": by_point[cid],
            "pois": pois_per_city[cid],
        }

    top = sorted(b.cities, key=lambda c: (-(streets_per_city[c["id"]]), c["name"]))[:40]
    centers = [b.cities[p["center_city_id"] - 1] for p in b.provinces if p.get("center_city_id")]
    settlements = [c for c in b.cities if c["kind"] != "republican"]
    return {
        "counts": {
            "provinces": len(b.provinces),
            "districts": len(b.districts),
            "cities": len(b.cities),
            "living_areas": len(b.areas),
            "streets": len(b.streets),
            "houses": len(b.houses),
            "pois": len(b.pois),
            "aliases": len(b.aliases),
        },
        "by_source": {
            t: dict(Counter(r["source"] for r in rows))
            for t, rows in (
                ("cities", b.cities),
                ("districts", b.districts),
                ("living_areas", b.areas),
                ("streets", b.streets),
            )
        }
        | {"houses": dict(Counter(h[5] for h in b.houses)), "pois": dict(Counter(p[7] for p in b.pois))},
        "aliases_by_lang": dict(Counter(a[4] for a in b.aliases)),
        "settlements_with_district": {
            "total": len(settlements),
            "with_district": sum(1 for c in settlements if c["district_id"]),
            "by_method": dict(Counter(c["district_method"] for c in settlements if c["district_id"])),
        },
        "houses": {
            "with_district": sum(1 for h in b.houses if h[3] is not None),
            "with_living_area": sum(1 for h in b.houses if h[4] is not None),
            "living_area_by_point": sum(1 for h in b.houses if h[6] == "point"),
        },
        "streets": {
            "with_district": sum(1 for s in b.streets if s["dom_district_id"]),
            "district_ambiguous": sum(1 for s in b.streets if s["dom_district_id"] and s["dom_district_share"] < 0.8),
            "with_living_area": sum(1 for s in b.streets if s["dom_area_id"]),
            "typed": sum(1 for s in b.streets if s["type"]),
        },
        "centers": [row(c) for c in centers],
        "top_cities": [row(c) for c in top],
        **(extra or {}),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=Path, default=HERE / "seed")
    ap.add_argument("--osm", type=Path, help="выгрузка OSM после assign_districts.py (каталог или старый json)")
    ap.add_argument("--kato", type=Path, help="выгрузка КАТО после kato.py")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

    b = Builder()
    load_seed(b, args.seed)
    sources = ["seed"]
    extra: dict[str, Any] = {}
    # порядок = приоритет канонического написания: ядро -> OSM (русские name:ru, «Весёлая Роща») -> КАТО
    # (в КАТО часть русских названий записана казахскими буквами: «Аққулы»). КАТО дополняет коды и районы
    # пунктов, которых нет у OSM, и добавляет пункты без OSM (source=kato, при выборе одноимённых они последние)
    if args.osm and args.osm.exists():
        osm = read_external(args.osm)
        load_external(b, osm, "osm")
        sources.append("osm")
        extra = {k: osm[k] for k in ("city_units", "levels", "stats") if k in osm}
    if args.kato and args.kato.exists():
        load_external(b, read_external(args.kato), "kato", lang="kk")
        sources.append("kato")
    b.finalize_streets()
    cov = coverage(b, {"osm": extra} if extra else None)
    meta = {
        "built_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "sources": sources,
        "counts": cov["counts"],
    }
    b.write(args.out, meta)
    (args.out.parent / "coverage.json").write_text(json.dumps(cov, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{args.out}: {cov['counts']} sources={sources}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
