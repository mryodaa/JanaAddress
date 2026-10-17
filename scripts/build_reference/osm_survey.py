"""Разведка дампа OSM -> docs/OSM_SURVEY.md: что и на каких уровнях есть в данных Казахстана.

    python scripts/build_reference/osm_survey.py [cache/kazakhstan-latest.osm.pbf] [--out docs/OSM_SURVEY.md]

Один проход тем же отбором, что и osm_extract.py (общий Extractor), но без записи на диск: полигоны границ и
мест в shapely, дома/улицы/объекты точками в массивах. Уровни admin_level определяются по данным
(osm_common.detect_levels), а не хардкодом. © участники OpenStreetMap, ODbL 1.0.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from array import array
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import shapely
import yaml
from shapely import wkb

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))

from osm_common import (  # noqa: E402
    LIVING_PLACES,
    NAME_KEYS,
    Boundary,
    detect_levels,
    prepare,
    ru_name,
    strip_district,
)
from osm_extract import CACHE, run  # noqa: E402

from jana_address.reference.normalize import fold, keys  # noqa: E402

CENTER_RADIUS_KM = 8.0  # город без полигона: круг вокруг place-точки


class Survey:
    def __init__(self) -> None:
        self.boundaries: list[Boundary] = []
        self.areas: list[dict[str, Any]] = []
        self.places: list[dict[str, Any]] = []
        self.hx, self.hy = array("d"), array("d")
        self.house_tags: Counter[str] = Counter()
        self.sx, self.sy = array("d"), array("d")
        self.street_hw: Counter[str] = Counter()
        self.px, self.py = array("d"), array("d")
        self.poi_kind: Counter[str] = Counter()
        self.brands: Counter[str] = Counter()
        self.name_keys: dict[str, Counter[str]] = defaultdict(Counter)
        self.totals: Counter[str] = Counter()

    def __call__(self, rec: dict[str, Any]) -> None:
        t = rec["t"]
        self.totals[t] += 1
        for k in rec.get("names") or {}:
            self.name_keys[t][k] += 1
        if t == "boundary":
            g = wkb.loads(rec["wkb"], hex=True)
            self.boundaries.append(Boundary(rec["osm"], int(rec["level"]), rec["names"], g, rec.get("kato")))
        elif t == "area_place":
            self.areas.append({"osm": rec["osm"], "place": rec["place"], "names": rec["names"],
                               "geom": wkb.loads(rec["wkb"], hex=True)})  # fmt: skip
        elif t == "place":
            self.places.append(rec)
        elif t == "street":
            self.sx.append(rec["pt"][0])
            self.sy.append(rec["pt"][1])
            self.street_hw[rec["hw"]] += 1
        elif t == "house":
            self.hx.append(rec["pt"][0])
            self.hy.append(rec["pt"][1])
            for k in ("street", "place", "city", "district", "suburb", "postcode"):
                if rec.get(k):
                    self.house_tags[k] += 1
            if rec.get("street") or rec.get("place"):
                self.house_tags["usable"] += 1
            if rec.get("bld"):
                self.house_tags["building"] += 1
        elif t == "poi":
            self.px.append(rec["pt"][0])
            self.py.append(rec["pt"][1])
            self.poi_kind[rec["kind"]] += 1
            if rec.get("brand"):
                self.brands[rec["brand"]] += 1


def pct(a: int, b: int) -> str:
    return f"{100.0 * a / b:.1f}%" if b else "—"


def seed_data() -> dict[str, Any]:
    return yaml.safe_load((HERE / "seed" / "admin.yaml").read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def seed_district_keys(seed: dict[str, Any]) -> dict[str, set[str]]:
    """Город/область -> fold-ключи районов ядра (с алиасами)."""
    out: dict[str, set[str]] = defaultdict(set)
    for rc in seed["republican_cities"]:
        for d in rc.get("districts", []):
            for a in (d["name"], *d.get("aliases", [])):
                out[rc["name"]].update(keys(strip_district(a)))
    for city, dists in (seed.get("city_districts") or {}).items():
        for d in dists:
            for a in (d["name"], *d.get("aliases", [])):
                out[city].update(keys(strip_district(a)))
    for prov, dists in (seed.get("oblast_districts") or {}).items():
        for d in dists:
            for a in (d["name"], *d.get("aliases", [])):
                out[prov].update(keys(strip_district(a)))
    return out


def report(sv: Survey, src: str) -> str:
    prepare(sv.boundaries)
    lv = detect_levels(sv.boundaries)
    seed = seed_data()
    sdk = seed_district_keys(seed)
    L: list[str] = []
    w = L.append
    w("# Разведка OSM: Казахстан\n")
    w(f"Источник: `{src}`, отчёт {dt.date.today().isoformat()} (`scripts/build_reference/osm_survey.py`). "
      "© участники OpenStreetMap, ODbL 1.0.\n")  # fmt: skip
    w("Отбор тот же, что в `osm_extract.py`. Уровни ниже определены по данным (`osm_common.detect_levels`).\n")

    w("## Объём выборки\n")
    w("| Тип записи | Количество |\n|---|---:|")
    for t, n in sorted(sv.totals.items()):
        w(f"| {t} | {n} |")
    w("")

    w("## boundary=administrative по admin_level\n")
    by_lv: dict[int, list[Boundary]] = defaultdict(list)
    for b in sv.boundaries:
        by_lv[b.level].append(b)
    w("| admin_level | полигонов | с name:ru | с name:kk | с маркером района | примеры |")
    w("|---:|---:|---:|---:|---:|---|")
    for level in sorted(by_lv):
        items = by_lv[level]
        ex = ", ".join(b.name for b in sorted(items, key=lambda b: -b.area)[:8])
        ru = pct(sum("name:ru" in b.names for b in items), len(items))
        kk = pct(sum("name:kk" in b.names for b in items), len(items))
        w(f"| {level} | {len(items)} | {ru} | {kk} | {sum(b.is_district for b in items)} | {ex} |")
    w("")
    w("**Определённые уровни:**\n")
    w(f"* области и города респ. значения: admin_level **{lv.province_level}** ({len(lv.provinces)} полигонов);")
    w(f"* города респ. значения (полигон уровня области < 5000 км²): {', '.join(b.name for b in lv.republican)};")
    w(f"* районы областей: admin_level **{lv.oblast_district_level}** ({len(lv.oblast_districts)} районов);")
    n_with = sum(1 for u in lv.city_units if u.districts)
    w(f"* городские контейнеры (города респ. значения и «Г.А.»/«қ.ә.»): {len(lv.city_units)}, с районами: {n_with}.\n")

    w("### Районы городов\n")
    w("Для каждого города выбран уровень, где внутри контейнера больше всего полигонов «... район/ауданы» "
      "(не меньше двух). Остальные контейнеры районов в OSM не имеют.\n")  # fmt: skip
    w("| Город | уровень контейнера | уровень районов | районов | покрытие площади | районы | нет в ядре |\n"
      "|---|---:|---:|---:|---:|---|---|")  # fmt: skip
    for u in sorted(lv.city_units, key=lambda u: (-len(u.districts), u.city)):
        if not u.districts:
            continue
        names_ = [strip_district(b.name) for b in u.districts]
        miss = [n for n in names_ if not (set(keys(n)) & sdk.get(u.city, set()))]
        w(
            f"| {u.city} | {u.container.level} | {u.district_level} | {len(u.districts)} | {u.coverage:.0%} | "
            f"{', '.join(sorted(names_))} | {', '.join(miss) if sdk.get(u.city) else 'районов нет в ядре'} |"
        )
    w("")
    no = sorted(u.city for u in lv.city_units if not u.districts)
    w(f"Без районов в OSM ({len(no)}): {', '.join(no)}.\n")

    # районы областей против ядра
    prov_of: dict[str, str] = {}
    for d in lv.oblast_districts:
        hit = next((p for p in lv.provinces if shapely.contains_xy(p.geom, *d.rp)), None)
        prov_of[d.osm] = hit.name if hit else "?"
    per_prov: dict[str, list[str]] = defaultdict(list)
    for d in lv.oblast_districts:
        per_prov[prov_of[d.osm]].append(strip_district(d.name))
    w("### Районы областей и сверка с ядром\n")
    w("| Область | районов в OSM | в ядре | OSM без пары в ядре |\n|---|---:|---:|---|")
    for p in sorted(per_prov):
        seed_keys = sdk.get(p, set())
        miss = [n for n in per_prov[p] if seed_keys and not (set(keys(n)) & seed_keys)]
        n_seed = len((seed.get("oblast_districts") or {}).get(p, []))
        miss_s = ", ".join(sorted(miss)) or ("—" if n_seed else "ядра нет")
        w(f"| {p} | {len(per_prov[p])} | {n_seed or '—'} | {miss_s} |")
    w("")

    w("## Населённые пункты, микрорайоны, ЖК\n")
    pts = Counter(p["place"] for p in sv.places)
    polys = Counter(a["place"] for a in sv.areas)
    w("| place / landuse | точек | полигонов |\n|---|---:|---:|")
    for k in sorted(set(pts) | set(polys), key=lambda k: -(pts[k] + polys[k])):
        w(f"| {k} | {pts[k]} | {polys[k]} |")
    w("")

    w("## Дома\n")
    nh = len(sv.hx)
    w(f"Объектов с `addr:housenumber`: **{nh}**, из них зданий {pct(sv.house_tags['building'], nh)}.\n")
    w("| тег | доля |\n|---|---:|")
    for k, label in (("street", "addr:street"), ("place", "addr:place"), ("usable", "addr:street или addr:place"),
                     ("city", "addr:city"), ("district", "addr:district"), ("suburb", "addr:suburb"),
                     ("postcode", "addr:postcode")):  # fmt: skip
        w(f"| {label} | {pct(sv.house_tags[k], nh)} ({sv.house_tags[k]}) |")
    w("")

    w("## Алиасы: доля объектов с ключом имени\n")
    cols = ["name:ru", "name:kk", "name:en", "old_name", "alt_name", "official_name", "short_name", "loc_name"]
    w("| тип | всего | " + " | ".join(cols) + " |\n|---|---:|" + "---:|" * len(cols))
    for t in ("boundary", "place", "area_place", "street", "poi"):
        tot = sv.totals[t]
        cells = [pct(sv.name_keys[t][c], tot) for c in cols]
        w(f"| {t} | {tot} | " + " | ".join(cells) + " |")
    w(f"\nКлючи имён, которые берутся: {', '.join(f'`{k}`' for k in NAME_KEYS)}.\n")

    w("## Объекты-ориентиры (POI)\n")
    w("| вид | количество |\n|---|---:|")
    for k, n in sv.poi_kind.most_common(25):
        w(f"| {k} | {n} |")
    w("\n**Топ брендов:** " + ", ".join(f"{b} ({n})" for b, n in sv.brands.most_common(40)) + "\n")

    w("## Улицы\n")
    w(f"Линий `highway` с name: **{len(sv.sx)}**. По классам: "
      + ", ".join(f"{k} {n}" for k, n in sv.street_hw.most_common()) + ".\n")  # fmt: skip

    w("## Покрытие по областным центрам и городам респ. значения\n")
    w(coverage_table(sv, lv, seed))
    return "\n".join(L) + "\n"


def coverage_table(sv: Survey, lv: Any, seed: dict[str, Any]) -> str:
    centers = [rc["name"] for rc in seed["republican_cities"]] + [p["center"] for p in seed["provinces"]]
    hx, hy = np.frombuffer(sv.hx), np.frombuffer(sv.hy)
    sx, sy = np.frombuffer(sv.sx), np.frombuffer(sv.sy)
    px, py = np.frombuffer(sv.px), np.frombuffer(sv.py)
    unit_by = {fold(u.city): u for u in lv.city_units}
    place_poly = {fold(ru_name(a["names"])): a["geom"] for a in sv.areas if a["place"] in ("city", "town")}
    place_pt = {fold(ru_name(p["names"])): p["pt"] for p in sv.places if p["place"] in ("city", "town")}
    rows = ["| Город | контур | районов | мкр/ЖК полигонов | мкр точек | улиц (сегментов) | домов | POI |",
            "|---|---|---:|---:|---:|---:|---:|---:|"]  # fmt: skip
    for c in centers:
        k = fold(c)
        unit = unit_by.get(k)
        if unit is not None:
            geom, how = unit.container.geom, f"admin {unit.container.level}"
        elif k in place_poly:
            geom, how = place_poly[k], "place-полигон"
        elif k in place_pt:
            x, y = place_pt[k]
            geom = shapely.Point(x, y).buffer(CENTER_RADIUS_KM / 111.0 / max(np.cos(np.radians(y)), 0.3))
            how = f"круг {CENTER_RADIUS_KM:.0f} км"
        else:
            rows.append(f"| {c} | не найден | | | | | | |")
            continue
        shapely.prepare(geom)
        n_la_poly = sum(
            1 for a in sv.areas if a["place"] in (*LIVING_PLACES, "residential")
            and shapely.contains_xy(geom, *_rp(a["geom"]))
        )  # fmt: skip
        n_la_pt = sum(
            1 for p in sv.places if p["place"] in LIVING_PLACES and shapely.contains_xy(geom, p["pt"][0], p["pt"][1])
        )
        rows.append(
            f"| {c} | {how} | {len(unit.districts) if unit else 0} | {n_la_poly} | {n_la_pt} | "
            f"{int(shapely.contains_xy(geom, sx, sy).sum())} | {int(shapely.contains_xy(geom, hx, hy).sum())} | "
            f"{int(shapely.contains_xy(geom, px, py).sum())} |"
        )
    return "\n".join(rows) + "\n"


def _rp(g: Any) -> tuple[float, float]:
    p = g.representative_point()
    return p.x, p.y


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pbf", nargs="?", type=Path, default=CACHE / "kazakhstan-latest.osm.pbf")
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "OSM_SURVEY.md")
    ap.add_argument("--idx-dir", type=Path, default=CACHE, help="где держать индекс координат узлов")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    sv = Survey()
    run(args.pbf, sv, args.idx_dir)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report(sv, args.pbf.name), encoding="utf-8")
    print(f"{args.out}: {dict(sv.totals)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
