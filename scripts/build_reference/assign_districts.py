"""cache/osm_raw.jsonl -> cache/osm_assigned/: вся геометрия и пространственные привязки справочника.

    python scripts/build_reference/assign_districts.py [--raw cache/osm_raw.jsonl] [--out cache/osm_assigned]

Рантайм геометрии не знает: здесь считается всё, что потом лежит готовыми таблицами в reference.sqlite.
* Уровни admin_level определяются по данным (osm_common.detect_levels): области, районы областей, районы
  городов респ. значения и городских администраций («Г.А.»).
* Населённый пункт -> область и район области (точка в полигоне; без попадания ближайший район <= 2 км).
* Дом -> город (полигон города респ. значения -> полигон пункта -> радиус по типу пункта; addr:city уточняет),
  район города (полигон), living_area (самый мелкий полигон мкр/квартала, затем ЖК; иначе ближайшая точка мкр
  в пределах порога, метод и расстояние сохраняются).
* Улица: сегменты одного названия в городе склеиваются; доли по районам и мкр по длине сегментов внутри
  полигонов и по домам; доминирующий тип по длине.
* Мкр/ЖК -> город, район; объект (POI) -> город, район, мкр, вид, бренд.
Выход: meta.json (области, районы, города, мкр, статистика) + streets.jsonl, houses.jsonl, pois.jsonl.
Дома и улицы идут потоком пачками: 1.2 млн домов в памяти целиком не держим. © участники OpenStreetMap, ODbL 1.0.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import shapely
from shapely import STRtree, wkb
from shapely.ops import nearest_points

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))

from osm_common import (  # noqa: E402
    LIVING_PLACES,
    OKRUG_RE,
    Boundary,
    aliases_with_lang,
    detect_levels,
    km_scale,
    prepare,
    ru_name,
    strip_district,
    without_imeni,
)

from jana_address.reference.normalize import fold  # noqa: E402
from jana_address.rules_loader import get_rules  # noqa: E402

CACHE = HERE / "cache"
RADIUS_KM = {"city": 12.0, "town": 5.0, "village": 2.5, "hamlet": 1.5, "isolated_dwelling": 0.5}
NEAR_DISTRICT_KM = 2.0  # село чуть за границей полигона района (неточные границы OSM)
# ближайшая place-точка мкр без полигона: порог по типу точки, км
LA_POINT_KM = {"neighbourhood": 0.5, "quarter": 0.5, "city_block": 0.3, "allotments": 0.5, "suburb": 1.2}
LA_POLY_DUP_KM = 1.0  # точка мкр с тем же названием рядом с полигоном это тот же мкр
ADDR_CITY_KM = 20.0  # addr:city уточняет город, если такой пункт есть в этом радиусе
CHUNK = 50_000
# приоритет вида полигона мкр для дома: мкр/квартал важнее ЖК (ЖК часто внутри мкр)
AREA_PRIORITY = {"микрорайон": 0, "квартал": 0, "жилой массив": 0, "дачный массив": 1, "жилой комплекс": 2}


def split_type(name: str) -> tuple[str | None, str]:
    """«улица Абая» -> («улица», «Абая»), «Абай көшесі» -> («улица», «Абай»), «Абая» -> (None, «Абая»).
    Однобуквенные сокращения («у», «ш») не снимаем: в названиях OSM это чаще часть имени."""
    rules = get_rules()
    words = name.split()
    for n in (3, 2, 1):
        if len(words) > n:
            for phrase, rest in ((words[:n], words[n:]), (words[-n:], words[:-n])):
                text = " ".join(phrase).rstrip(".")
                if len(fold(text)) < 2:
                    continue
                st = rules.street_types.get(text)
                if st:
                    return st.canonical, " ".join(rest)
    return None, name


def proj(xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
    """Локальная проекция в км (масштаб долготы по широте самой точки): для поиска соседей в пределах км."""
    return np.column_stack([xs * 111.32 * np.cos(np.radians(ys)), ys * 110.57])


def lengths_m(geoms: np.ndarray) -> np.ndarray:
    """Длины линий (в т.ч. результатов пересечения) в метрах, векторно."""
    if len(geoms) == 0:
        return np.zeros(0)
    parts, gidx = shapely.get_parts(geoms, return_index=True)
    coords, pidx = shapely.get_coordinates(parts, return_index=True)
    if len(coords) < 2:
        return np.zeros(len(geoms))
    sx = 111_320.0 * np.cos(np.radians(coords[:, 1]))
    d = np.diff(coords, axis=0)
    seg = np.hypot(d[:, 0] * sx[1:], d[:, 1] * 110_570.0)
    same = pidx[1:] == pidx[:-1]
    part_len = np.bincount(pidx[1:][same], weights=seg[same], minlength=len(parts))
    return np.bincount(gidx, weights=part_len, minlength=len(geoms))


@dataclass
class PolyLayer:
    geoms: list[Any] = field(default_factory=list)
    items: list[dict[str, Any]] = field(default_factory=list)
    tree: STRtree | None = None

    def add(self, geom: Any, item: dict[str, Any]) -> None:
        self.geoms.append(geom)
        self.items.append(item)

    def build(self) -> None:
        self.tree = STRtree(self.geoms) if self.geoms else None

    def hits(self, xs: np.ndarray, ys: np.ndarray) -> list[list[dict[str, Any]]]:
        """Для каждой точки список содержащих её полигонов."""
        out: list[list[dict[str, Any]]] = [[] for _ in range(len(xs))]
        if self.tree is None or len(xs) == 0:
            return out
        pi, gi = self.tree.query(shapely.points(xs, ys), predicate="within")
        for p, g in zip(pi.tolist(), gi.tolist(), strict=True):
            out[p].append(self.items[g])
        return out


@dataclass
class PointLayer:
    """Ближайшая точка в пределах радиуса (км) в локальной проекции."""

    items: list[dict[str, Any]] = field(default_factory=list)
    xy: list[tuple[float, float]] = field(default_factory=list)
    tree: STRtree | None = None

    def add(self, x: float, y: float, item: dict[str, Any]) -> None:
        self.xy.append((x, y))
        self.items.append(item)

    def build(self) -> None:
        if self.items:
            arr = np.array(self.xy)
            p = proj(arr[:, 0], arr[:, 1])
            self.tree = STRtree(shapely.points(p[:, 0], p[:, 1]))

    def nearest(self, xs: np.ndarray, ys: np.ndarray, max_km: float) -> list[tuple[dict[str, Any], float] | None]:
        out: list[tuple[dict[str, Any], float] | None] = [None] * len(xs)
        if self.tree is None or len(xs) == 0:
            return out
        p = proj(xs, ys)
        (pi, gi), dist = self.tree.query_nearest(
            shapely.points(p[:, 0], p[:, 1]), max_distance=max_km, return_distance=True, all_matches=False
        )
        for a, g, d in zip(pi.tolist(), gi.tolist(), dist.tolist(), strict=True):
            out[a] = (self.items[g], d)
        return out


def read_raw(path: Path, types: set[str]) -> Iterator[dict[str, Any]]:
    """Поток записей нужных типов; тип проверяем по префиксу строки, не разбирая JSON остальных."""
    prefixes = tuple(f'{{"t": "{t}"' for t in types)
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.startswith(prefixes):
                yield json.loads(line)


def chunks(it: Iterator[dict[str, Any]], n: int = CHUNK) -> Iterator[list[dict[str, Any]]]:
    buf: list[dict[str, Any]] = []
    for r in it:
        buf.append(r)
        if len(buf) >= n:
            yield buf
            buf = []
    if buf:
        yield buf


def alias_list(nm: dict[str, str], main: str, transform: Any = None) -> list[list[str]]:
    out: dict[str, str] = {}
    for text, lang in aliases_with_lang(nm, main):
        t = transform(text) if transform else text
        if t and t != main and t not in out:
            out[t] = lang
    return [[t, lang] for t, lang in sorted(out.items())]


def district_aliases(nm: dict[str, str], name: str) -> list[list[str]]:
    """Алиасы района без «район/ауданы»; «имени Габита Мусрепова» ищется и как «Габита Мусрепова»."""
    out = alias_list(nm, name, strip_district)
    short = without_imeni(name)
    if short != name and short not in {a for a, _ in out}:
        out.append([short, "short"])
    return out


class Assigner:
    def __init__(self, raw: Path) -> None:
        self.raw = raw
        self.rules = get_rules()
        self.stats: Counter[str] = Counter()

    # ---------- полигоны и пункты ----------
    def load_static(self) -> None:
        boundaries: list[Boundary] = []
        self.area_places: list[dict[str, Any]] = []
        self.places: list[dict[str, Any]] = []
        for r in read_raw(self.raw, {"boundary", "area_place", "place"}):
            if r["t"] == "boundary":
                boundaries.append(
                    Boundary(r["osm"], int(r["level"]), r["names"], wkb.loads(r["wkb"], hex=True), r.get("kato"))
                )
            elif r["t"] == "area_place":
                r["geom"] = wkb.loads(r.pop("wkb"), hex=True)
                self.area_places.append(r)
            else:
                self.places.append(r)
        prepare(boundaries)
        self.boundaries = boundaries
        self.levels = detect_levels(boundaries)
        lv = self.levels
        print(
            f"уровни: области {lv.province_level}, районы областей {lv.oblast_district_level}, "
            f"городов с районами {sum(1 for u in lv.city_units if u.districts)}"
        )
        # области
        self.prov_layer = PolyLayer()
        self.provinces: list[dict[str, Any]] = []
        rep_ids = {b.osm for b in lv.republican}
        for b in lv.provinces:
            item = {
                "name": b.name,
                "kind": "city" if b.osm in rep_ids else "oblast",
                "osm_id": b.osm,
                "kato": b.kato,
                "aliases": alias_list(b.names, b.name),
            }
            self.provinces.append(item)
            self.prov_layer.add(b.geom, item)
        self.prov_layer.build()
        # районы областей
        self.oblast_d = PolyLayer()
        self.districts: list[dict[str, Any]] = []
        for b in lv.oblast_districts:
            prov = self.province_at(*b.rp)
            if prov is None:
                continue
            name = strip_district(b.name)
            item = {
                "name": name,
                "province": prov["name"],
                "osm_id": b.osm,
                "kato": b.kato,
                "aliases": district_aliases(b.names, name),
            }
            self.oblast_d.add(b.geom, item)
            self.districts.append(item)
        self.oblast_d.build()
        # районы городов: город респ. значения или городская администрация
        self.city_d = PolyLayer()
        self.city_units: list[dict[str, Any]] = []
        for u in lv.city_units:
            if not u.districts:
                continue
            prov = self.province_at(*u.container.rp)
            if prov is None:
                continue
            city = prov["name"] if u.republican else u.city
            self.city_units.append(
                {"city": city, "province": prov["name"], "level": u.district_level, "n": len(u.districts),
                 "coverage": round(u.coverage, 3)}
            )  # fmt: skip
            for b in u.districts:
                name = strip_district(b.name)
                item = {
                    "name": name,
                    "province": prov["name"],
                    "city": city,
                    "osm_id": b.osm,
                    "kato": b.kato,
                    "aliases": district_aliases(b.names, name),
                }
                self.city_d.add(b.geom, item)
                self.districts.append(item)
        self.city_d.build()
        self._settlements()
        self._living_areas()

    def province_at(self, x: float, y: float) -> dict[str, Any] | None:
        hits = self.prov_layer.hits(np.array([x]), np.array([y]))[0]
        return hits[0] if hits else None

    def _settlements(self) -> None:
        self.cities: list[dict[str, Any]] = []
        self.settle_pts: dict[str, PointLayer] = {k: PointLayer() for k in RADIUS_KM}
        by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
        pts = [p for p in self.places if p["place"] in RADIUS_KM]
        xs = np.array([p["pt"][0] for p in pts])
        ys = np.array([p["pt"][1] for p in pts])
        provs = self.prov_layer.hits(xs, ys)
        dists = self.oblast_d.hits(xs, ys)
        near = self._near_district(xs, ys)
        for i, p in enumerate(pts):
            if not provs[i]:
                continue
            prov = provs[i][0]
            name = ru_name(p["names"])
            if prov["kind"] == "city" and fold(name) == fold(prov["name"]):
                kind = "republican"
            else:
                kind = {"city": "city", "town": "town"}.get(p["place"], "village")
            dist, method = None, None
            if dists[i]:
                dist, method = dists[i][0], "polygon"
            elif near[i] is not None and prov["kind"] != "city":
                dist, method = near[i], "near"
            pop = re.sub(r"\D", "", p["pop"] or "") if p.get("pop") else ""
            item = {
                "name": name,
                "kind": kind,
                "province": prov["name"],
                "district": dist["name"] if dist and dist["province"] == prov["name"] else None,
                "district_method": method if dist and dist["province"] == prov["name"] else None,
                "osm_id": p["osm"],
                "lat": float(ys[i]),
                "lon": float(xs[i]),
                "population": int(pop) if pop else None,
                "kato": p.get("kato"),
                "aliases": alias_list(p["names"], name),
                "_place": p["place"],
            }
            self.stats[f"settlement_district_{item['district_method']}"] += 1
            self.cities.append(item)
            self.settle_pts[p["place"]].add(float(xs[i]), float(ys[i]), item)
            for k in {fold(name), *(fold(a) for a, _ in item["aliases"])}:
                by_name[k].append(item)
        for layer in self.settle_pts.values():
            layer.build()
        self.city_by_name = by_name
        # полигоны пунктов: place=city/town/village/hamlet и admin-границы пунктов (уровни глубже районов)
        self.settle_poly = PolyLayer()
        polys = [(a["geom"], a["names"]) for a in self.area_places if a["place"] in RADIUS_KM]
        # admin-граница глубже района бывает границей пункта (Жезказган), а бывает сельским округом, названным
        # по главному селу («Новостройка»): такой контур забрал бы улицы соседних сёл. Берём её, только если
        # внутри нет других населённых пунктов
        dl = self.levels.oblast_district_level or 0
        sx = np.array([c["lon"] for c in self.cities])
        sy = np.array([c["lat"] for c in self.cities])
        for b in self.boundaries:
            if b.level <= dl or b.is_district or b.any_name(OKRUG_RE):
                continue
            inside = [self.cities[i] for i in np.flatnonzero(shapely.contains_xy(b.geom, sx, sy))]
            if inside and all(fold(c["name"]) == fold(b.name) for c in inside):
                polys.append((b.geom, b.names))
                self.stats["settlement_admin_polygon"] += 1
        for geom, nm in polys:
            rp = geom.representative_point()
            cands = [
                c for c in by_name.get(fold(ru_name(nm)), []) if shapely.contains_xy(geom, c["lon"], c["lat"])
            ] or [c for c in by_name.get(fold(ru_name(nm)), []) if abs(c["lon"] - rp.x) + abs(c["lat"] - rp.y) < 0.1]
            if cands:
                self.settle_poly.add(geom, min(cands, key=lambda c: RADIUS_KM[c["_place"]]))
        self.settle_poly.build()
        self.rep_city = {c["province"]: c for c in self.cities if c["kind"] == "republican"}  # область-город -> пункт

    def _near_district(self, xs: np.ndarray, ys: np.ndarray) -> list[dict[str, Any] | None]:
        out: list[dict[str, Any] | None] = [None] * len(xs)
        if self.oblast_d.tree is None or len(xs) == 0:
            return out
        deg = NEAR_DISTRICT_KM / 80.0  # грубый фильтр в градусах, точная проверка ниже
        (pi, gi), _ = self.oblast_d.tree.query_nearest(
            shapely.points(xs, ys), max_distance=deg, return_distance=True, all_matches=False
        )
        for p, g in zip(pi.tolist(), gi.tolist(), strict=True):
            geom = self.oblast_d.geoms[g]
            sx, sy = km_scale(float(ys[p]))
            nearest = nearest_points(geom, shapely.Point(xs[p], ys[p]))[0]
            d = float(np.hypot((nearest.x - xs[p]) * sx, (nearest.y - ys[p]) * sy))
            if d <= NEAR_DISTRICT_KM:
                out[p] = self.oblast_d.items[g]
        return out

    def cities_at(self, xs: np.ndarray, ys: np.ndarray, addr_city: list[str | None] | None = None) -> list[Any]:
        """Город для каждой точки: полигон города респ. значения -> полигон пункта -> радиус; addr:city уточняет."""
        n = len(xs)
        out: list[dict[str, Any] | None] = [None] * n
        provs = self.prov_layer.hits(xs, ys)
        polys = self.settle_poly.hits(xs, ys)
        for i in range(n):
            if provs[i] and provs[i][0]["kind"] == "city" and provs[i][0]["name"] in self.rep_city:
                out[i] = self.rep_city[provs[i][0]["name"]]
            elif polys[i]:
                out[i] = min(polys[i], key=lambda c: RADIUS_KM[c["_place"]])
        rest = [i for i in range(n) if out[i] is None]
        if rest:
            rx, ry = xs[rest], ys[rest]
            best: dict[int, tuple[float, dict[str, Any]]] = {}
            for place, layer in self.settle_pts.items():
                r = RADIUS_KM[place]
                for j, hit in enumerate(layer.nearest(rx, ry, r)):
                    if hit is not None:
                        ratio = hit[1] / r
                        if ratio < 1 and (rest[j] not in best or ratio < best[rest[j]][0]):
                            best[rest[j]] = (ratio, hit[0])
            for i, (_, c) in best.items():
                out[i] = c
        if addr_city:
            for i, ac in enumerate(addr_city):
                if not ac:
                    continue
                k = fold(ac.replace("г.", " ").strip())
                cur = out[i]
                if cur is not None and (fold(cur["name"]) == k or k in {fold(a) for a, _ in cur["aliases"]}):
                    self.stats["addr_city_agree"] += 1
                    continue
                sx, sy = km_scale(float(ys[i]))
                cands = [
                    (float(np.hypot((c["lon"] - xs[i]) * sx, (c["lat"] - ys[i]) * sy)), j, c)
                    for j, c in enumerate(self.city_by_name.get(k, []))
                ]
                cands = [x for x in cands if x[0] <= ADDR_CITY_KM]
                if cands:
                    out[i] = min(cands)[2]
                    self.stats["addr_city_override"] += 1
        return out

    # ---------- мкр / ЖК ----------
    def _area_type(self, name: str, place: str | None) -> tuple[str, str]:
        st, bare = split_type(name)
        t = self.rules.street_types.get(st) if st else None
        if st and t is not None and t.kind == "area":
            return st, bare
        if place == "residential":
            return "жилой комплекс", name
        if place == "quarter" and re.search(r"квартал", name, re.I):
            return "квартал", name
        return "микрорайон", name

    def _living_areas(self) -> None:
        self.areas: dict[tuple[str, str], dict[str, Any]] = {}
        self.area_layer = PolyLayer()
        self.area_pts = {k: PointLayer() for k in LA_POINT_KM}
        polys: list[tuple[Any, dict[str, str], str, str]] = [
            (a["geom"], a["names"], a["place"], a["osm"])
            for a in self.area_places
            if a["place"] in (*LIVING_PLACES, "residential")
        ]
        # admin_level 10 не берём: по разведке это сельские округа и территории за границей, а не кварталы
        xs = np.array([g.representative_point().x for g, *_ in polys])
        ys = np.array([g.representative_point().y for g, *_ in polys])
        cities = self.cities_at(xs, ys)
        dists = self.city_d.hits(xs, ys)
        poly_keys: dict[str, list[tuple[float, float]]] = defaultdict(list)
        for i, (geom, nm, place, osm) in enumerate(polys):
            name = ru_name(nm)
            city = cities[i]
            if not name or city is None:
                continue
            typ, bare = self._area_type(name, place)
            if not bare:
                continue
            item = self._area_item(bare, typ, city, dists[i], osm, nm)
            sx, sy = km_scale(float(ys[i]))
            # элемент слоя на каждый полигон: у одного мкр бывает несколько полигонов разной площади
            self.area_layer.add(
                geom,
                {"la": item, "name": item["name"], "city": item["city"], "city_osm": item["city_osm"],
                 "area_km2": float(geom.area) * sx * sy,
                 "prio": AREA_PRIORITY.get(item["type"], 1)},
            )  # fmt: skip
            poly_keys[fold(bare)].append((float(xs[i]), float(ys[i])))
            self.stats["la_polygon"] += 1
        self.area_layer.build()
        pts = [p for p in self.places if p["place"] in LA_POINT_KM]
        xs = np.array([p["pt"][0] for p in pts])
        ys = np.array([p["pt"][1] for p in pts])
        cities = self.cities_at(xs, ys)
        dists = self.city_d.hits(xs, ys)
        for i, p in enumerate(pts):
            name = ru_name(p["names"])
            city = cities[i]
            if not name or city is None:
                continue
            typ, bare = self._area_type(name, p["place"])
            if not bare:
                continue
            item = self._area_item(bare, typ, city, dists[i], p["osm"], p["names"])
            sx, sy = km_scale(float(ys[i]))
            dup = any(np.hypot((x - xs[i]) * sx, (y - ys[i]) * sy) < LA_POLY_DUP_KM for x, y in poly_keys[fold(bare)])
            if not dup:
                self.area_pts[p["place"]].add(float(xs[i]), float(ys[i]), item)
                self.stats["la_point"] += 1
        for layer in self.area_pts.values():
            layer.build()

    def _area_item(
        self, bare: str, typ: str, city: dict[str, Any], dists: list[dict[str, Any]], osm: str, nm: dict[str, str]
    ) -> dict[str, Any]:
        dist = next((d for d in dists if d["city"] == city["name"]), None)
        key = (city["osm_id"], fold(bare))
        item = self.areas.setdefault(
            key,
            {
                "name": bare,
                "type": typ,
                "city": city["name"],
                "city_osm": city["osm_id"],
                "province": city["province"],
                "district": dist["name"] if dist else None,
                "osm_id": osm,
                "aliases": [],
            },
        )
        have = {a for a, _ in item["aliases"]}
        for a in alias_list(nm, bare, lambda t: split_type(t)[1]):
            if a[0] not in have and a[0] != item["name"]:
                item["aliases"].append(a)
        return item

    def living_at(self, xs: np.ndarray, ys: np.ndarray, cities: list[Any]) -> list[tuple[Any, str, float] | None]:
        """(мкр, метод, расстояние м): самый мелкий полигон мкр/квартала, затем ЖК; иначе ближайшая точка."""
        out: list[tuple[Any, str, float] | None] = [None] * len(xs)
        for i, hits in enumerate(self.area_layer.hits(xs, ys)):
            hits = [h for h in hits if cities[i] is not None and h["city_osm"] == cities[i]["osm_id"]]
            if hits:
                out[i] = (min(hits, key=lambda h: (h["prio"], h["area_km2"]))["la"], "polygon", 0.0)
        rest = [i for i in range(len(xs)) if out[i] is None and cities[i] is not None]
        if rest:
            rx, ry = xs[rest], ys[rest]
            for place, layer in self.area_pts.items():
                lim = LA_POINT_KM[place]
                for j, hit in enumerate(layer.nearest(rx, ry, lim)):
                    i = rest[j]
                    if hit is None or hit[0]["city_osm"] != cities[i]["osm_id"]:
                        continue
                    cur = out[i]
                    if cur is None or hit[1] * 1000 < cur[2]:
                        out[i] = (hit[0], "point", round(hit[1] * 1000, 1))
        return out

    # ---------- улицы ----------
    def run_streets(self) -> None:
        """Сегменты -> (город, fold(название)) -> по типу: длина, доли длины по районам и мкр, алиасы."""
        self.street_groups: dict[tuple[str, str], dict[str | None, dict[str, Any]]] = defaultdict(dict)
        dist_geoms = np.array(self.city_d.geoms, dtype=object)
        area_geoms = np.array(self.area_layer.geoms, dtype=object)
        for batch in chunks(read_raw(self.raw, {"street"}), 20_000):
            names = [ru_name(s["names"]) for s in batch]
            split = [split_type(n) for n in names]
            xs = np.array([s["pt"][0] for s in batch])
            ys = np.array([s["pt"][1] for s in batch])
            cities = self.cities_at(xs, ys)
            lines = np.array([wkb.loads(s["wkb"], hex=True) for s in batch], dtype=object)
            seg_len = lengths_m(lines)
            d_len = self._overlap(lines, self.city_d, dist_geoms)
            a_len = self._overlap(lines, self.area_layer, area_geoms)
            for i, s in enumerate(batch):
                typ, bare = split[i]
                city = cities[i]
                if not bare or city is None:
                    continue
                st = self._street(city, typ, bare)
                st["length_m"] += float(seg_len[i])
                st["segments"] += 1
                for (c, d), ln in d_len.get(i, {}).items():
                    if c == city["name"]:
                        st["d_len"][d] += ln
                for (c, la), ln in a_len.get(i, {}).items():
                    if c == city["name"]:
                        st["a_len"][la] += ln
                for text, lang in aliases_with_lang(s["names"], names[i]):
                    b = split_type(text)[1]
                    if b and fold(b) != fold(bare):
                        st["aliases"][b] = lang
            self.stats["street_segments"] += len(batch)
            print(f"  улиц: {self.stats['street_segments']}", flush=True)

    def _overlap(
        self, lines: np.ndarray, layer: PolyLayer, geoms: np.ndarray
    ) -> dict[int, dict[tuple[str, str], float]]:
        """Длина каждой линии внутри полигонов слоя (м): {индекс линии: {(город, название): длина}}."""
        out: dict[int, dict[tuple[str, str], float]] = defaultdict(dict)
        if layer.tree is None or len(lines) == 0:
            return out
        li, gi = layer.tree.query(lines, predicate="intersects")
        if len(li) == 0:
            return out
        inter = shapely.intersection(lines[li], geoms[gi])
        lens = lengths_m(inter)
        for a, g, ln in zip(li.tolist(), gi.tolist(), lens.tolist(), strict=True):
            if ln > 0:
                key = (layer.items[g]["city"], layer.items[g]["name"])
                out[a][key] = out[a].get(key, 0.0) + ln
        return out

    def _street(self, city: dict[str, Any], typ: str | None, bare: str) -> dict[str, Any]:
        group = self.street_groups[(city["osm_id"], fold(bare))]
        if typ not in group:
            group[typ] = {
                "name": bare,
                "type": typ,
                "city": city["name"],
                "city_osm": city["osm_id"],
                "province": city["province"],
                "length_m": 0.0,
                "segments": 0,
                "houses": 0,
                "d_len": Counter(),
                "a_len": Counter(),
                "d_houses": Counter(),
                "a_houses": Counter(),
                "aliases": {},
            }
        return group[typ]

    def resolve_street(self, city: dict[str, Any], typ: str | None, bare: str) -> dict[str, Any]:
        """Улица дома: тип из addr:street; без типа (или тип не встречался) -> доминирующий тип сегментов."""
        group = self.street_groups.get((city["osm_id"], fold(bare)))
        if group:
            if typ in group:
                return group[typ]
            typed = [s for t, s in group.items() if t is not None]
            if typ is None and typed:
                return max(typed, key=lambda s: s["length_m"])
            if typ is not None and None in group and len(group) == 1:
                # сегменты без типа + дом с типом: одна улица, тип берём из адреса
                st = group.pop(None)
                st["type"] = typ
                group[typ] = st
                return st
        return self._street(city, typ, bare)

    # ---------- дома ----------
    def run_houses(self, out_path: Path) -> None:
        with out_path.open("w", encoding="utf-8") as fh:
            for batch in chunks(read_raw(self.raw, {"house"})):
                batch = [h for h in batch if h.get("num") and (h.get("street") or h.get("place"))]
                if not batch:
                    continue
                xs = np.array([h["pt"][0] for h in batch])
                ys = np.array([h["pt"][1] for h in batch])
                cities = self.cities_at(xs, ys, [h.get("city") for h in batch])
                dists = self.city_d.hits(xs, ys)
                las = self.living_at(xs, ys, cities)
                for i, h in enumerate(batch):
                    city = cities[i]
                    if city is None:
                        self.stats["house_no_city"] += 1
                        continue
                    typ, bare = split_type((h.get("street") or h.get("place")).strip())
                    if not bare:
                        continue
                    if not h.get("street") and fold(bare) == fold(city["name"]):
                        # addr:place = само село («Боралдай, 12»): улицы нет, псевдо-улица с именем пункта
                        # мешала бы узнавать город без маркера
                        self.stats["house_place_is_city"] += 1
                        continue
                    st = self.resolve_street(city, typ, bare)
                    dist = next((d for d in dists[i] if d["city"] == city["name"]), None)
                    la = las[i]
                    st["houses"] += 1
                    if dist:
                        st["d_houses"][dist["name"]] += 1
                    if la:
                        st["a_houses"][la[0]["name"]] += 1
                    rec = {
                        "street": st["name"],
                        "type": st["type"],
                        "city": city["name"],
                        "city_osm": city["osm_id"],
                        "province": city["province"],
                        "number": h["num"].strip(),
                        "district": dist["name"] if dist else None,
                        "living_area": la[0]["name"] if la else None,
                        "la_method": la[1] if la else None,
                        "la_dist_m": la[2] if la else None,
                        "postcode": h.get("postcode"),
                    }
                    self.stats["houses"] += 1
                    self.stats["house_district"] += bool(dist)
                    self.stats[f"house_la_{la[1] if la else 'none'}"] += 1
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                print(f"  домов: {self.stats['houses']}", flush=True)

    def write_streets(self, out_path: Path) -> None:
        with out_path.open("w", encoding="utf-8") as fh:
            for group in self.street_groups.values():
                _merge_untyped(group)
                typed_len = sum(s["length_m"] for t, s in group.items() if t is not None)
                for typ, s in group.items():
                    rec = {
                        "name": s["name"],
                        "type": typ,
                        "city": s["city"],
                        "city_osm": s["city_osm"],
                        "province": s["province"],
                        "length_m": round(s["length_m"], 1),
                        "houses": s["houses"],
                        "type_share": round(s["length_m"] / typed_len, 3) if typ is not None and typed_len else None,
                        "districts": _shares(s["d_houses"], s["d_len"]),
                        "areas": _shares(s["a_houses"], s["a_len"]),
                        "aliases": [[a, lang] for a, lang in sorted(s["aliases"].items())],
                    }
                    self.stats["streets"] += 1
                    self.stats["street_with_district"] += bool(rec["districts"])
                    self.stats["street_with_area"] += bool(rec["areas"])
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # ---------- объекты ----------
    def run_pois(self, out_path: Path) -> None:
        pois = list(read_raw(self.raw, {"poi"}))
        with out_path.open("w", encoding="utf-8") as fh:
            for batch in chunks(iter(pois)):
                xs = np.array([p["pt"][0] for p in batch])
                ys = np.array([p["pt"][1] for p in batch])
                cities = self.cities_at(xs, ys)
                dists = self.city_d.hits(xs, ys)
                las = self.living_at(xs, ys, cities)
                for i, p in enumerate(batch):
                    city = cities[i]
                    name = ru_name(p["names"]) or (p.get("brand") or "").strip()
                    if city is None or not name:
                        continue
                    dist = next((d for d in dists[i] if d["city"] == city["name"]), None)
                    rec = {
                        "name": name,
                        "kind": p["kind"],
                        "brand": p.get("brand"),
                        "city": city["name"],
                        "city_osm": city["osm_id"],
                        "province": city["province"],
                        "district": dist["name"] if dist else None,
                        "living_area": las[i][0]["name"] if las[i] and las[i][1] == "polygon" else None,
                        "aliases": alias_list(p["names"], name),
                    }
                    self.stats["pois"] += 1
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _merge_untyped(group: dict[str | None, dict[str, Any]]) -> None:
    """Сегменты без типа («Абая») при наличии типизированных («улица Абая») это та же улица доминирующего типа."""
    if None not in group or len(group) == 1:
        return
    raw = group.pop(None)
    dom = max(group.values(), key=lambda s: s["length_m"])
    for k in ("length_m", "segments", "houses"):
        dom[k] += raw[k]
    for k in ("d_len", "a_len", "d_houses", "a_houses"):
        dom[k].update(raw[k])
    for a, lang in raw["aliases"].items():
        dom["aliases"].setdefault(a, lang)


def _shares(houses: Counter[str], length: Counter[str]) -> dict[str, dict[str, float]]:
    """{название: {houses, length_m, share}}; доля по домам, если домов >= 3, иначе по длине."""
    total_h = sum(houses.values())
    total_l = sum(length.values())
    out: dict[str, dict[str, float]] = {}
    for name in set(houses) | set(length):
        if total_h >= 3:
            share = houses[name] / total_h
        elif total_l > 0:
            share = length[name] / total_l
        else:
            share = houses[name] / total_h if total_h else 0.0
        out[name] = {"houses": houses[name], "length_m": round(length[name], 1), "share": round(share, 3)}
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", type=Path, default=CACHE / "osm_raw.jsonl")
    ap.add_argument("--out", type=Path, default=CACHE / "osm_assigned")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    args.out.mkdir(parents=True, exist_ok=True)
    a = Assigner(args.raw)
    a.load_static()
    print(f"области {len(a.provinces)}, районов {len(a.districts)}, пунктов {len(a.cities)}, мкр {len(a.areas)}")
    a.run_streets()
    a.run_houses(args.out / "houses.jsonl")
    a.write_streets(args.out / "streets.jsonl")
    a.run_pois(args.out / "pois.jsonl")
    meta = {
        "provinces": a.provinces,
        "districts": a.districts,
        "cities": [{k: v for k, v in c.items() if not k.startswith("_")} for c in a.cities],
        "living_areas": [
            {k: v for k, v in x.items() if not k.startswith("_") and k != "area_km2"} for x in a.areas.values()
        ],
        "city_units": a.city_units,
        "levels": {
            "province": a.levels.province_level,
            "oblast_district": a.levels.oblast_district_level,
            "counts": a.levels.counts,
        },
        "stats": dict(a.stats),
    }
    (args.out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    print(f"{args.out}: {dict(a.stats)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
