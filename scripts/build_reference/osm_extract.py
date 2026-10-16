"""OSM .pbf -> cache/osm_raw.jsonl: административные границы, населённые пункты, микрорайоны, улицы, дома.

    python scripts/build_reference/osm_extract.py [cache/kazakhstan-latest.osm.pbf]

Пишет по одной JSON-записи на объект: {"t": "boundary"|"place"|"street"|"house", ...}.
Геометрия: границы и площадные place в WKB hex, остальное точкой (lon, lat).
Нужен pyosmium (pip install osmium). © участники OpenStreetMap, ODbL 1.0.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, TextIO

import osmium

HERE = Path(__file__).resolve().parent
CACHE = HERE / "cache"

ADMIN_LEVELS = {"4", "5", "6", "7", "8", "9", "10"}
PLACE_POINTS = {
    "city",
    "town",
    "village",
    "hamlet",
    "suburb",
    "neighbourhood",
    "quarter",
    "isolated_dwelling",
    "locality",
    "allotments",
}
AREA_PLACES = {"suburb", "neighbourhood", "quarter", "city", "town", "village", "allotments"}
HIGHWAYS = {
    "motorway",
    "trunk",
    "primary",
    "secondary",
    "tertiary",
    "unclassified",
    "residential",
    "living_street",
    "pedestrian",
    "service",
    "road",
    "track",
    "footway",
    "primary_link",
    "secondary_link",
    "tertiary_link",
}
NAME_KEYS = (
    "name",
    "name:ru",
    "name:kk",
    "name:en",
    "old_name",
    "old_name:ru",
    "alt_name",
    "alt_name:ru",
    "official_name",
    "official_name:ru",
    "short_name",
)


def names(tags: Any) -> dict[str, str]:
    return {k: tags.get(k) for k in NAME_KEYS if tags.get(k)}


class Extractor(osmium.SimpleHandler):  # type: ignore[misc]
    def __init__(self, out: TextIO) -> None:
        super().__init__()
        self.out = out
        self.wkb = osmium.geom.WKBFactory()
        self.counts: dict[str, int] = {}

    def emit(self, rec: dict[str, Any]) -> None:
        self.counts[rec["t"]] = self.counts.get(rec["t"], 0) + 1
        self.out.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def node(self, n: Any) -> None:
        tags = n.tags
        if "place" in tags and tags["place"] in PLACE_POINTS and "name" in tags:
            self.emit(
                {
                    "t": "place",
                    "osm": f"n{n.id}",
                    "place": tags["place"],
                    "names": names(tags),
                    "pop": tags.get("population"),
                    "kato": tags.get("kato") or tags.get("ref:kato"),
                    "pt": [n.location.lon, n.location.lat],
                }
            )
        if "addr:housenumber" in tags and ("addr:street" in tags or "addr:place" in tags):
            self.emit(self._house(tags, [n.location.lon, n.location.lat], f"n{n.id}"))

    def way(self, w: Any) -> None:
        tags = w.tags
        hw = tags.get("highway")
        if (hw in HIGHWAYS and "name" in tags) or (
            "addr:housenumber" in tags and ("addr:street" in tags or "addr:place" in tags)
        ):
            try:
                locs = [(nd.location.lon, nd.location.lat) for nd in w.nodes if nd.location.valid()]
            except osmium.InvalidLocationError:
                return
            if not locs:
                return
            if hw in HIGHWAYS and "name" in tags:
                mid = locs[len(locs) // 2]
                self.emit(
                    {
                        "t": "street",
                        "osm": f"w{w.id}",
                        "hw": hw,
                        "names": names(tags),
                        "pt": list(mid),
                        "pts": [list(locs[0]), list(mid), list(locs[-1])],
                    }
                )
            if "addr:housenumber" in tags:
                cx = sum(x for x, _ in locs) / len(locs)
                cy = sum(y for _, y in locs) / len(locs)
                self.emit(self._house(tags, [cx, cy], f"w{w.id}"))

    def area(self, a: Any) -> None:
        tags = a.tags
        kind = None
        if tags.get("boundary") == "administrative" and tags.get("admin_level") in ADMIN_LEVELS and "name" in tags:
            kind = "boundary"
        elif (tags.get("place") in AREA_PLACES and "name" in tags) or (
            tags.get("landuse") == "residential" and "name" in tags
        ):
            kind = "area_place"
        if not kind:
            return
        try:
            geom = self.wkb.create_multipolygon(a)
        except Exception:
            return
        rec = {
            "t": kind,
            "osm": f"{'w' if a.from_way() else 'r'}{a.orig_id()}",
            "names": names(tags),
            "level": tags.get("admin_level"),
            "place": tags.get("place") or tags.get("landuse"),
            "kato": tags.get("kato") or tags.get("ref:kato") or tags.get("ref"),
            "wkb": geom,
        }
        self.emit(rec)

    @staticmethod
    def _house(tags: Any, pt: list[float], osm: str) -> dict[str, Any]:
        return {
            "t": "house",
            "osm": osm,
            "num": tags.get("addr:housenumber"),
            "street": tags.get("addr:street"),
            "place": tags.get("addr:place"),
            "city": tags.get("addr:city"),
            "district": tags.get("addr:district") or tags.get("addr:suburb"),
            "pt": pt,
        }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pbf", nargs="?", type=Path, default=CACHE / "kazakhstan-latest.osm.pbf")
    ap.add_argument("--out", type=Path, default=CACHE / "osm_raw.jsonl")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        h = Extractor(fh)
        # индекс координат узлов на диске: не держим весь Казахстан в памяти
        idx = f"sparse_file_array,{(CACHE / 'nodes.idx').as_posix()}"
        h.apply_file(str(args.pbf), locations=True, idx=idx)
    print(f"{args.out}: {h.counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
