"""cache/osm_raw.jsonl -> cache/osm_assigned.json: геометрическая привязка к области, району, городу.

    python scripts/build_reference/assign_districts.py

* Области и города респ. значения: admin_level=4.
* Районы: admin_level=6 «... район/ауданы» (район области) или внутри города респ. значения (район города).
  admin_level 7-9 «... район» внутри городской администрации -> район города (Караганда и т.п.).
* Город для улицы/дома: полигон города респ. значения -> полигон place=city/town/village ->
  ближайший населённый пункт в радиусе (city 12 км, town 5 км, village 2.5 км).
* Район улицы считаем по трём точкам (начало, середина, конец); дома точкой (shapely STRtree).
  Улица в нескольких районах получает веса, неоднозначность разрешает номер дома (reference_step).
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from shapely import STRtree, wkb
from shapely.geometry import Point
from shapely.prepared import prep

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from jana_address.reference.normalize import fold  # noqa: E402
from jana_address.rules_loader import get_rules  # noqa: E402

HERE = Path(__file__).resolve().parent
CACHE = HERE / "cache"
RADIUS_KM = {"city": 12.0, "town": 5.0, "village": 2.5, "hamlet": 1.5, "isolated_dwelling": 0.5}
REP_CITIES = {"алматы", "астана", "шымкент"}
_DIST_RE = re.compile(r"\s*(район|ауданы|р-н)\s*", re.I)
_PROV_RE = re.compile(r"\s*(область|облысы)\s*", re.I)
_CITY_ADMIN_RE = re.compile(r"(городская администрация|г\.\s*а\.|қалалық әкімдігі|қ\.\s*ә\.|город|қаласы)", re.I)


def ru_name(names: dict[str, str]) -> str:
    return (names.get("name:ru") or names.get("name") or "").strip()


def alt_names(names: dict[str, str]) -> list[str]:
    main = ru_name(names)
    return sorted({v.strip() for v in names.values() if v and v.strip() and v.strip() != main})


def km(a: tuple[float, float], b: tuple[float, float]) -> float:
    dx = (a[0] - b[0]) * 111.32 * math.cos(math.radians((a[1] + b[1]) / 2))
    dy = (a[1] - b[1]) * 110.57
    return math.hypot(dx, dy)


def split_type(name: str) -> tuple[str | None, str]:
    """«улица Абая» -> («улица», «Абая»), «Абай көшесі» -> («улица», «Абай»), «Абая» -> (None, «Абая»)."""
    rules = get_rules()
    words = name.split()
    for n in (3, 2, 1):
        if len(words) > n:
            head = rules.street_types.get(" ".join(words[:n]).rstrip("."))
            if head:
                return head.canonical, " ".join(words[n:])
            tail = rules.street_types.get(" ".join(words[-n:]).rstrip("."))
            if tail:
                return tail.canonical, " ".join(words[:-n])
    return None, name


@dataclass
class Layer:
    geoms: list[Any] = field(default_factory=list)
    items: list[dict[str, Any]] = field(default_factory=list)
    tree: STRtree | None = None
    prepared: list[Any] = field(default_factory=list)

    def add(self, geom: Any, item: dict[str, Any]) -> None:
        self.geoms.append(geom)
        self.items.append(item)

    def build(self) -> None:
        self.tree = STRtree(self.geoms) if self.geoms else None
        self.prepared = [prep(g) for g in self.geoms]

    def at(self, pt: tuple[float, float]) -> list[dict[str, Any]]:
        if self.tree is None:
            return []
        p = Point(pt)
        return [self.items[i] for i in self.tree.query(p) if self.prepared[i].contains(p)]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", type=Path, default=CACHE / "osm_raw.jsonl")
    ap.add_argument("--out", type=Path, default=CACHE / "osm_assigned.json")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

    boundaries, area_places, places, streets_raw, houses_raw = [], [], [], [], []
    with args.raw.open(encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            {
                "boundary": boundaries,
                "area_place": area_places,
                "place": places,
                "street": streets_raw,
                "house": houses_raw,
            }[r["t"]].append(r)
    print(
        f"границ {len(boundaries)}, площадных мест {len(area_places)}, точек {len(places)}, "
        f"улиц {len(streets_raw)}, домов {len(houses_raw)}"
    )

    # ---------- области ----------
    prov_layer = Layer()
    provinces = []
    for b in boundaries:
        if b["level"] != "4":
            continue
        name = ru_name(b["names"])
        geom = wkb.loads(b["wkb"], hex=True)
        kind = "city" if fold(name) in REP_CITIES else "oblast"
        item = {"name": name, "kind": kind, "osm_id": b["osm"], "aliases": alt_names(b["names"])}
        provinces.append(item)
        prov_layer.add(geom, item)
    prov_layer.build()

    def province_at(pt: tuple[float, float]) -> dict[str, Any] | None:
        hits = prov_layer.at(pt)
        return hits[0] if hits else None

    # ---------- районы и городские администрации ----------
    oblast_d, city_d, city_admin = Layer(), Layer(), Layer()
    districts = []
    for b in boundaries:
        if b["level"] in ("4", None):
            continue
        name = ru_name(b["names"])
        geom = wkb.loads(b["wkb"], hex=True)
        rp = geom.representative_point()
        prov = province_at((rp.x, rp.y))
        if prov is None:
            continue
        is_district = bool(_DIST_RE.search(name)) or name.lower().startswith("район")
        bare = _DIST_RE.sub(" ", name).strip()
        aliases = [_DIST_RE.sub(" ", a).strip() for a in alt_names(b["names"])]
        if prov["kind"] == "city" and b["level"] in ("6", "7", "8", "9") and is_district:
            item = {
                "name": bare,
                "province": prov["name"],
                "city": prov["name"],
                "osm_id": b["osm"],
                "aliases": aliases,
            }
            city_d.add(geom, item)
            districts.append(item)
        elif b["level"] == "6" and is_district:
            item = {"name": bare, "province": prov["name"], "osm_id": b["osm"], "aliases": aliases}
            oblast_d.add(geom, item)
            districts.append(item)
        elif b["level"] == "6":
            city_admin.add(geom, {"name": _CITY_ADMIN_RE.sub(" ", name).strip(), "province": prov["name"]})
    oblast_d.build()
    city_admin.build()
    # районы внутри городских администраций (Караганда: район имени Казыбек би)
    for b in boundaries:
        if b["level"] not in ("7", "8", "9"):
            continue
        name = ru_name(b["names"])
        if not _DIST_RE.search(name) and not name.lower().startswith("район"):
            continue
        geom = wkb.loads(b["wkb"], hex=True)
        rp = geom.representative_point()
        adm = city_admin.at((rp.x, rp.y))
        prov = province_at((rp.x, rp.y))
        if adm and prov and prov["kind"] != "city":
            item = {
                "name": _DIST_RE.sub(" ", name).replace("имени", "").strip(),
                "province": prov["name"],
                "city": adm[0]["name"],
                "osm_id": b["osm"],
                "aliases": [name],
            }
            city_d.add(geom, item)
            districts.append(item)
    city_d.build()

    # ---------- населённые пункты ----------
    cities = []
    settle_pts: list[tuple[tuple[float, float], dict[str, Any]]] = []
    for p in places:
        if p["place"] not in RADIUS_KM:
            continue
        pt = (p["pt"][0], p["pt"][1])
        prov = province_at(pt)
        if prov is None:
            continue
        name = ru_name(p["names"])
        if prov["kind"] == "city" and fold(name) == fold(prov["name"]):
            kind = "republican"
        else:
            kind = {"city": "city", "town": "town"}.get(p["place"], "village")
        dist = oblast_d.at(pt)
        pop = int(re.sub(r"\D", "", p["pop"]) or 0) if p.get("pop") else None
        item = {
            "name": name,
            "kind": kind,
            "province": prov["name"],
            "district": dist[0]["name"] if dist else None,
            "osm_id": p["osm"],
            "lat": pt[1],
            "lon": pt[0],
            "population": pop,
            "kato": p.get("kato"),
            "aliases": alt_names(p["names"]),
            "_place": p["place"],
        }
        cities.append(item)
        settle_pts.append((pt, item))
    by_name = defaultdict(list)
    for _, c in settle_pts:
        by_name[fold(c["name"])].append(c)
    # полигоны населённых пунктов
    settle_poly = Layer()
    for a in area_places:
        if a["place"] not in ("city", "town", "village"):
            continue
        name = ru_name(a["names"])
        geom = wkb.loads(a["wkb"], hex=True)
        rp = geom.representative_point()
        cands = [c for c in by_name.get(fold(name), []) if km((c["lon"], c["lat"]), (rp.x, rp.y)) < 30]
        if cands:
            settle_poly.add(geom, cands[0])
    settle_poly.build()
    grid: dict[tuple[int, int], list[tuple[tuple[float, float], dict[str, Any]]]] = defaultdict(list)
    for pt, c in settle_pts:
        grid[(int(pt[0] * 10), int(pt[1] * 10))].append((pt, c))

    def city_at(pt: tuple[float, float]) -> dict[str, Any] | None:
        prov = province_at(pt)
        if prov and prov["kind"] == "city":
            rep = [c for c in by_name.get(fold(prov["name"]), []) if c["kind"] == "republican"]
            if rep:
                return rep[0]
        poly = settle_poly.at(pt)
        if poly:
            return min(poly, key=lambda c: RADIUS_KM[c["_place"]])
        best, best_r = None, 1.0
        gx, gy = int(pt[0] * 10), int(pt[1] * 10)
        for dx in (-2, -1, 0, 1, 2):
            for dy in (-2, -1, 0, 1, 2):
                for cpt, c in grid.get((gx + dx, gy + dy), ()):
                    r = km(pt, cpt) / RADIUS_KM[c["_place"]]
                    if r < best_r:
                        best, best_r = c, r
        return best

    def city_district_at(pt: tuple[float, float]) -> str | None:
        hits = city_d.at(pt)
        return hits[0]["name"] if hits else None

    # ---------- микрорайоны / ЖК ----------
    rules = get_rules()
    areas: dict[tuple[str, str], dict[str, Any]] = {}
    area_layer = Layer()

    def area_type(name: str, place: str | None) -> tuple[str, str]:
        st, bare = split_type(name)
        if st and rules.street_types.get(st) and rules.street_types.get(st).kind == "area":  # type: ignore[union-attr]
            return st, bare
        if place == "residential":
            return "жилой комплекс", name
        return "микрорайон", name

    for p in [*places, *area_places]:
        if p["place"] not in ("suburb", "neighbourhood", "quarter", "residential", "allotments"):
            continue
        name = ru_name(p["names"])
        if not name:
            continue
        if "wkb" in p:
            geom = wkb.loads(p["wkb"], hex=True)
            rp = geom.representative_point()
            pt = (rp.x, rp.y)
        else:
            geom, pt = None, (p["pt"][0], p["pt"][1])
        city = city_at(pt)
        if city is None:
            continue
        typ, bare = area_type(name, p["place"])
        key = (city["name"], fold(bare))
        item = areas.setdefault(
            key,
            {
                "name": bare,
                "type": typ,
                "city": city["name"],
                "province": city["province"],
                "district": city_district_at(pt),
                "osm_id": p["osm"],
                "aliases": [split_type(a)[1] for a in alt_names(p["names"])],
            },
        )
        if geom is not None:
            area_layer.add(geom, item)
    area_layer.build()

    # ---------- улицы ----------
    streets: dict[tuple[str, str | None, str], dict[str, Any]] = {}
    for s in streets_raw:
        name = ru_name(s["names"])
        typ, bare = split_type(name)
        if not bare:
            continue
        city = city_at((s["pt"][0], s["pt"][1]))
        if city is None:
            continue
        key = (city["name"], typ, fold(bare))
        item = streets.setdefault(
            key,
            {
                "name": bare,
                "type": typ,
                "city": city["name"],
                "province": city["province"],
                "districts": Counter(),
                "aliases": set(),
            },
        )
        for a in alt_names(s["names"]):
            item["aliases"].add(split_type(a)[1])
        for pt in s["pts"]:
            d = city_district_at((pt[0], pt[1]))
            if d:
                item["districts"][d] += 1

    # ---------- дома ----------
    houses = []
    for h in houses_raw:
        if not h.get("num") or not (h.get("street") or h.get("place")):
            continue
        pt = (h["pt"][0], h["pt"][1])
        city = city_at(pt)
        if city is None:
            continue
        typ, bare = split_type((h.get("street") or h.get("place")).strip())
        key = (city["name"], typ, fold(bare))
        if key not in streets:
            streets[key] = {
                "name": bare,
                "type": typ,
                "city": city["name"],
                "province": city["province"],
                "districts": Counter(),
                "aliases": set(),
            }
        d = city_district_at(pt)
        if d:
            streets[key]["districts"][d] += 1
        la = area_layer.at(pt)
        houses.append(
            {
                "street": bare,
                "city": city["name"],
                "province": city["province"],
                "number": h["num"].strip(),
                "district": d,
                "living_area": la[0]["name"] if la else None,
            }
        )

    out = {
        "provinces": provinces,
        "districts": districts,
        "cities": [{k: v for k, v in c.items() if not k.startswith("_")} for c in cities],
        "living_areas": list(areas.values()),
        "streets": [
            {**s, "districts": dict(s["districts"]), "aliases": sorted(s["aliases"] - {s["name"]})}
            for s in streets.values()
        ],
        "houses": houses,
    }
    args.out.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"{args.out}: " + ", ".join(f"{k}={len(v)}" for k, v in out.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
