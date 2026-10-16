"""Сборка reference/reference.sqlite из ядра (seed/*.yaml) и, если есть, выгрузок OSM и КАТО.

    python scripts/build_reference/build_sqlite.py                       # только ядро
    python scripts/build_reference/build_sqlite.py --osm cache/osm_assigned.json --kato cache/kato.json

Промежуточный формат OSM/КАТО (готовят osm_extract.py + assign_districts.py, kato.py) ссылается на
сущности по названиям: {"provinces": [...], "districts": [...], "cities": [...], "living_areas": [...],
"streets": [...], "houses": [...]}. Ядро имеет приоритет: его названия канонические для ответа.
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


def toponym_ok(name: str | None) -> bool:
    """Отсев мусора OSM: целые адреса в addr:street («Gogol St 15, Almaty, Kazakhstan») и т.п.
    Справочник хранит только топонимы, поэтому запятые, индексы и длинные строки не берём."""
    return bool(name) and "," not in name and len(name) <= 60 and not _POSTCODE.search(name)  # type: ignore[arg-type]


def province_key(name: str) -> str:
    return fold(_PROV_WORDS.sub(" ", name)).strip()


def district_key(name: str) -> str:
    return fold(_DIST_WORDS.sub(" ", name)).strip()


@dataclass
class Builder:
    provinces: list[dict[str, Any]] = field(default_factory=list)
    districts: list[dict[str, Any]] = field(default_factory=list)
    cities: list[dict[str, Any]] = field(default_factory=list)
    areas: list[dict[str, Any]] = field(default_factory=list)
    streets: list[dict[str, Any]] = field(default_factory=list)
    street_districts: Counter[tuple[int, int]] = field(default_factory=Counter)
    houses: list[dict[str, Any]] = field(default_factory=list)
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
    def province(self, name: str, kind: str, source: str, aliases: list[str] = (), **kw: Any) -> int:  # type: ignore[assignment]
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
        for a in aliases:
            self.alias("province", pid, a, source=source)
            # алиасы регистрируем без снятия «облысы»: «Алматы облысы» не должен совпасть с городом Алматы
            if a:
                self._by.setdefault(("province", None, fold(a)), pid)
        return pid

    def district(
        self,
        name: str,
        kind: str,
        province_id: int | None,
        city_id: int | None,
        source: str,
        aliases: list[str] = (),
        **kw: Any,
    ) -> int:  # type: ignore[assignment]
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
        for a in (name, *aliases):
            self.alias("district", did, a, source=source)
            self._register("district", scope, a, did)
        return did

    def city(
        self,
        name: str,
        kind: str,
        province_id: int | None,
        source: str,
        district_id: int | None = None,
        aliases: list[str] = (),
        **kw: Any,
    ) -> int:  # type: ignore[assignment]
        cid = self.find("city", province_id, name)
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
                }
            )
            self._register("city", province_id, name, cid)
        else:
            row = self.cities[cid - 1]
            for k in ("osm_id", "kato", "lat", "lon", "population"):
                row[k] = row[k] or kw.get(k)
            row["district_id"] = row["district_id"] or district_id
        for a in (name, *aliases):
            self.alias("city", cid, a, source=source)
            self._register("city", province_id, a, cid)
        return cid

    def area(
        self,
        name: str,
        typ: str,
        city_id: int | None,
        district_id: int | None,
        source: str,
        aliases: list[str] = (),
        **kw: Any,
    ) -> int:  # type: ignore[assignment]
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
        for a in (name, *aliases):
            self.alias("living_area", aid, a, source=source)
            self._register("living_area", city_id, a, aid)
        return aid

    def street(self, name: str, typ: str | None, city_id: int | None, source: str, aliases: list[str] = ()) -> int:  # type: ignore[assignment]
        scope = (city_id, typ)
        sid = self.find("street", scope, name)
        if sid is None:
            sid = len(self.streets) + 1
            self.streets.append({"id": sid, "name": name, "type": typ, "city_id": city_id, "source": source})
            self._register("street", scope, name, sid)
        for a in (name, *aliases):
            self.alias("street", sid, a, source=source)
            self._register("street", scope, a, sid)
        return sid

    def house(self, street_id: int, number: str, district_id: int | None, area_id: int | None, source: str) -> None:
        key = fold(number).replace(" ", "")
        if (street_id, key) in self._house_seen:
            return
        self._house_seen.add((street_id, key))
        self.houses.append(
            {
                "street_id": street_id,
                "number": number,
                "key": key,
                "district_id": district_id,
                "living_area_id": area_id,
                "source": source,
            }
        )
        if district_id:
            self.street_districts[(street_id, district_id)] += 1

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
            "INSERT INTO street_districts VALUES (?,?,?)", [(s, d, w) for (s, d), w in self.street_districts.items()]
        )
        ins("houses", self.houses)
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
        pid = b.province(p["name"], "oblast", "seed", [p.get("short", ""), kk, *p.get("aliases", [])])
        # только алиас для поиска рядом с маркером; в слияние не регистрируем («Алматы» != Алматинская обл.)
        b.alias("province", pid, kk_short, lang="kk")
        centers[pid] = p["center"]
    for rc in data["republican_cities"]:
        pid = b.province(rc["name"], "city", "seed", [rc.get("kk", ""), *rc.get("aliases", [])])
        cid = b.city(rc["name"], "republican", pid, "seed", aliases=[rc.get("kk", ""), *rc.get("aliases", [])])
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
        b.city(c["name"], c.get("kind", "city"), pid, "seed", did, c.get("aliases", []))
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


def load_external(b: Builder, data: dict[str, Any], source: str) -> None:
    """Слияние выгрузки OSM/КАТО. Сущности ссылаются друг на друга по названиям."""

    def prov_id(name: str | None) -> int | None:
        return b.find("province", None, name) if name else None

    for p in data.get("provinces", []):
        b.province(
            p["name"], p.get("kind", "oblast"), source, p.get("aliases", []), osm_id=p.get("osm_id"), kato=p.get("kato")
        )
    city_scope: dict[tuple[str | None, str], int] = {}
    # сначала города (нужны для районов городов), районы областей
    for d in data.get("districts", []):
        if d.get("city"):
            continue
        pid = prov_id(d.get("province"))
        if pid:
            b.district(
                d["name"], "oblast", pid, None, source, d.get("aliases", []), osm_id=d.get("osm_id"), kato=d.get("kato")
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
        )
        city_scope[(c.get("province"), c["name"])] = cid

    def city_id(prov: str | None, name: str | None) -> int | None:
        if not name:
            return None
        if (prov, name) in city_scope:
            return city_scope[(prov, name)]
        pid = prov_id(prov)
        cid = b.find("city", pid, name)
        if cid is None and pid is None:
            # республиканский город может прийти без области
            cid = next((c["id"] for c in b.cities if fold(c["name"]) == fold(name) and c["kind"] == "republican"), None)
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
        cid = city_id(a.get("province"), a.get("city"))
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
        )

    street_ids: dict[tuple[int, str], int] = {}
    for s in data.get("streets", []):
        cid = city_id(s.get("province"), s.get("city"))
        if not cid or not toponym_ok(s["name"]):
            continue
        sid = b.street(s["name"], s.get("type"), cid, source, s.get("aliases", []))
        street_ids[(cid, fold(s["name"]))] = sid
        for dname, w in (s.get("districts") or {}).items():
            did = dist_id(cid, s.get("province"), dname)
            if did:
                b.street_districts[(sid, did)] += int(w)
    for h in data.get("houses", []):
        cid = city_id(h.get("province"), h.get("city"))
        if not cid or not toponym_ok(h["street"]) or len(h["number"]) > 20:
            continue
        sid = street_ids.get((cid, fold(h["street"])))
        if not sid:
            continue
        aid = b.find("living_area", cid, h["living_area"]) if h.get("living_area") else None
        b.house(sid, h["number"], dist_id(cid, h.get("province"), h.get("district")), aid, source)


def coverage(b: Builder) -> dict[str, Any]:
    streets_per_city: Counter[int] = Counter(s["city_id"] for s in b.streets)
    houses_per_city: Counter[int] = Counter()
    sid2city = {s["id"]: s["city_id"] for s in b.streets}
    for h in b.houses:
        houses_per_city[sid2city[h["street_id"]]] += 1
    with_district = defaultdict(int)
    for h in b.houses:
        if h["district_id"]:
            with_district[sid2city[h["street_id"]]] += 1
    top = sorted(b.cities, key=lambda c: (-(streets_per_city[c["id"]]), c["name"]))[:40]
    return {
        "counts": {
            "provinces": len(b.provinces),
            "districts": len(b.districts),
            "cities": len(b.cities),
            "living_areas": len(b.areas),
            "streets": len(b.streets),
            "houses": len(b.houses),
            "aliases": len(b.aliases),
        },
        "by_source": {
            t: dict(Counter(r["source"] for r in rows))
            for t, rows in (
                ("cities", b.cities),
                ("districts", b.districts),
                ("living_areas", b.areas),
                ("streets", b.streets),
                ("houses", b.houses),
            )
        },
        "top_cities": [
            {
                "city": c["name"],
                "kind": c["kind"],
                "streets": streets_per_city[c["id"]],
                "houses": houses_per_city[c["id"]],
                "houses_with_district": with_district[c["id"]],
            }
            for c in top
        ],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=Path, default=HERE / "seed")
    ap.add_argument("--osm", type=Path, help="выгрузка OSM после assign_districts.py")
    ap.add_argument("--kato", type=Path, help="выгрузка КАТО после kato.py")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

    b = Builder()
    load_seed(b, args.seed)
    sources = ["seed"]
    if args.kato and args.kato.exists():
        load_external(b, json.loads(args.kato.read_text(encoding="utf-8")), "kato")
        sources.append("kato")
    if args.osm and args.osm.exists():
        load_external(b, json.loads(args.osm.read_text(encoding="utf-8")), "osm")
        sources.append("osm")
    cov = coverage(b)
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
