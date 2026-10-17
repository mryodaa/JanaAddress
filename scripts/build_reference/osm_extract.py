"""OSM .pbf -> cache/osm_raw.jsonl: границы, населённые пункты, микрорайоны и ЖК, улицы, дома, объекты-ориентиры.

    python scripts/build_reference/osm_extract.py [cache/kazakhstan-latest.osm.pbf]

По одной JSON-записи на объект: {"t": "boundary"|"area_place"|"place"|"street"|"house"|"poi", ...}.
Геометрия: полигоны и линии улиц в WKB hex, дома и объекты точкой (lon, lat) по центроиду.
Только топонимы и теги, целых адресных строк нет. Нужен pyosmium. © участники OpenStreetMap, ODbL 1.0.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import osmium

sys.path.insert(0, str(Path(__file__).resolve().parent))

from osm_common import (
    ADMIN_LEVELS,
    AREA_PLACES,
    HIGHWAYS,
    PLACE_POINTS,
    names,
    poi_kind,
)

HERE = Path(__file__).resolve().parent
CACHE = HERE / "cache"

Sink = Callable[[dict[str, Any]], None]


class Extractor(osmium.SimpleHandler):  # type: ignore[misc]
    """Отбор объектов; запись делает sink (файл JSONL или агрегатор разведки)."""

    def __init__(self, sink: Sink) -> None:
        super().__init__()
        self.sink = sink
        self.wkb = osmium.geom.WKBFactory()
        self.counts: dict[str, int] = {}

    def emit(self, rec: dict[str, Any]) -> None:
        self.counts[rec["t"]] = self.counts.get(rec["t"], 0) + 1
        self.sink(rec)

    def node(self, n: Any) -> None:
        tags = n.tags
        if not len(tags):
            return
        pt = [n.location.lon, n.location.lat]
        if tags.get("place") in PLACE_POINTS and "name" in tags:
            self.emit(
                {
                    "t": "place",
                    "osm": f"n{n.id}",
                    "place": tags["place"],
                    "names": names(tags),
                    "pop": tags.get("population"),
                    "kato": tags.get("kato") or tags.get("ref:kato"),
                    "pt": pt,
                }
            )
        if "addr:housenumber" in tags:
            self.emit(self._house(tags, pt, f"n{n.id}", building=False))
        self._poi(tags, pt, f"n{n.id}")

    def way(self, w: Any) -> None:
        tags = w.tags
        if not len(tags):
            return
        hw = tags.get("highway")
        is_street = hw in HIGHWAYS and "name" in tags
        is_house = "addr:housenumber" in tags
        kind = poi_kind(tags)
        is_poi = kind is not None and ("name" in tags or "brand" in tags)
        if not (is_street or is_house or is_poi):
            return
        try:
            locs = [(nd.location.lon, nd.location.lat) for nd in w.nodes if nd.location.valid()]
        except osmium.InvalidLocationError:
            return
        if not locs:
            return
        if is_street and len(locs) >= 2:
            line = self.wkb.create_linestring(w)
            mid = locs[len(locs) // 2]
            self.emit({"t": "street", "osm": f"w{w.id}", "hw": hw, "names": names(tags), "pt": list(mid), "wkb": line})
        if is_house or is_poi:
            ring = locs[:-1] if len(locs) > 1 and locs[0] == locs[-1] else locs
            cx = sum(x for x, _ in ring) / len(ring)
            cy = sum(y for _, y in ring) / len(ring)
            if is_house:
                self.emit(self._house(tags, [cx, cy], f"w{w.id}", building="building" in tags))
            self._poi(tags, [cx, cy], f"w{w.id}")

    def area(self, a: Any) -> None:
        tags = a.tags
        kind = None
        if tags.get("boundary") == "administrative" and tags.get("admin_level") in ADMIN_LEVELS and "name" in tags:
            kind = "boundary"
        elif (tags.get("place") in AREA_PLACES and "name" in tags) or (
            tags.get("landuse") == "residential" and "name" in tags
        ):
            kind = "area_place"
        poi_rel = not a.from_way() and poi_kind(tags) is not None and ("name" in tags or "brand" in tags)
        if not kind and not poi_rel:
            return
        try:
            geom = self.wkb.create_multipolygon(a)
        except Exception:
            return
        if kind:
            self.emit(
                {
                    "t": kind,
                    "osm": f"{'w' if a.from_way() else 'r'}{a.orig_id()}",
                    "names": names(tags),
                    "level": tags.get("admin_level"),
                    "place": tags.get("place") or tags.get("landuse"),
                    "kato": tags.get("kato") or tags.get("ref:kato") or tags.get("ref"),
                    "wkb": geom,
                }
            )
        if poi_rel:
            from shapely import wkb as swkb

            c = swkb.loads(geom, hex=True).centroid
            self._poi(tags, [c.x, c.y], f"r{a.orig_id()}")

    def _poi(self, tags: Any, pt: list[float], osm: str) -> None:
        kind = poi_kind(tags)
        if kind is None or not ("name" in tags or "brand" in tags):
            return
        self.emit(
            {
                "t": "poi",
                "osm": osm,
                "kind": kind,
                "names": names(tags),
                "brand": tags.get("brand") or tags.get("brand:ru"),
                "brand_wd": tags.get("brand:wikidata"),
                "pt": pt,
            }
        )

    @staticmethod
    def _house(tags: Any, pt: list[float], osm: str, building: bool) -> dict[str, Any]:
        return {
            "t": "house",
            "osm": osm,
            "num": tags.get("addr:housenumber"),
            "street": tags.get("addr:street"),
            "place": tags.get("addr:place"),
            "city": tags.get("addr:city"),
            "district": tags.get("addr:district"),
            "suburb": tags.get("addr:suburb"),
            "postcode": tags.get("addr:postcode"),
            "bld": building,
            "pt": pt,
        }


def run(pbf: Path, sink: Sink, idx_dir: Path = CACHE) -> dict[str, int]:
    h = Extractor(sink)
    # индекс координат узлов на диске: не держим весь Казахстан в памяти
    idx_dir.mkdir(parents=True, exist_ok=True)
    idx = f"sparse_file_array,{(idx_dir / 'nodes.idx').as_posix()}"
    h.apply_file(str(pbf), locations=True, idx=idx)
    return h.counts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pbf", nargs="?", type=Path, default=CACHE / "kazakhstan-latest.osm.pbf")
    ap.add_argument("--out", type=Path, default=CACHE / "osm_raw.jsonl")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        counts = run(args.pbf, lambda rec: fh.write(json.dumps(rec, ensure_ascii=False) + "\n"), args.out.parent)
    print(f"{args.out}: {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
