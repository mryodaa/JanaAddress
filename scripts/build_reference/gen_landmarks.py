"""Бренды ориентиров из объектов OSM -> src/jana_address/rules/landmarks_osm.yaml (генерируется, руками не править).

    python scripts/build_reference/gen_landmarks.py [--db reference/reference.sqlite] [--min-cities 3]

Бренд берётся, если он сетевой (встречается в нескольких городах или много раз), не короче четырёх букв,
не автосалон и не совпадает с топонимом справочника (город, улица, мкр, район, область) или маркером: иначе
«Береке» или «Астана» открывали бы ориентир посреди адреса. Ручной список остаётся в landmarks.yaml,
rules_loader сливает оба. Вывод детерминирован (сортировка). © участники OpenStreetMap, ODbL 1.0.
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from jana_address.reference.normalize import fold, keys  # noqa: E402
from jana_address.rules_loader import load_rules  # noqa: E402

OUT = ROOT / "src" / "jana_address" / "rules" / "landmarks_osm.yaml"
_LETTERS = re.compile(r"[^\W\d_]")
# автосалоны и автозапчасти: марки машин в адресе почти не бывают ориентиром, а ложных срабатываний дают много
SKIP_KINDS = ("shop:car", "shop:tyres", "shop:motorcycle")


def candidates(con: sqlite3.Connection) -> dict[str, tuple[int, int]]:
    """Бренд -> (объектов, городов). «Jaecoo;Omoda» делится на два."""
    objects: Counter[str] = Counter()
    cities: dict[str, set[int]] = defaultdict(set)
    for brand, city_id, kind in con.execute("SELECT brand, city_id, kind FROM pois WHERE brand IS NOT NULL"):
        if str(kind).startswith(SKIP_KINDS):
            continue
        for b in str(brand).split(";"):
            b = b.strip()
            if b:
                objects[b] += 1
                cities[b].add(city_id)
    return {b: (n, len(cities[b])) for b, n in objects.items()}


def toponym_keys(con: sqlite3.Connection) -> set[str]:
    return {k for (k,) in con.execute("SELECT DISTINCT key FROM aliases")}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=ROOT / "reference" / "reference.sqlite")
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--min-cities", type=int, default=3)
    ap.add_argument("--min-objects", type=int, default=10)
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

    con = sqlite3.connect(f"file:{args.db.as_posix()}?mode=ro", uri=True)
    rules = load_rules()
    topo = toponym_keys(con)
    have = {k for b in yaml.safe_load((OUT.parent / "landmarks.yaml").read_text(encoding="utf-8"))["brands"]
            for k in keys(str(b))}  # fmt: skip
    markers = (
        rules.street_types,
        rules.details,
        rules.noise,
        rules.lm_objects,
        rules.lm_prepositions,
        rules.province_markers,
        rules.district_markers,
        rules.city_prefix,
        rules.settlement_prefix,
    )
    brands: list[str] = []
    skipped: Counter[str] = Counter()
    for b, (n, nc) in sorted(candidates(con).items()):
        k = set(keys(b))
        if nc < args.min_cities and n < args.min_objects:
            skipped["редкий"] += 1
        elif len(_LETTERS.findall(b)) < 4 or len(b) > 40:
            skipped["короткий/длинный"] += 1
        elif k & have:
            skipped["уже в landmarks.yaml"] += 1
        elif k & topo:
            skipped["совпадает с топонимом"] += 1
        elif any(b in m for m in markers) or fold(b) in rules.needs_dot:
            skipped["совпадает с маркером"] += 1
        else:
            brands.append(b)
    head = (
        "# Сгенерировано scripts/build_reference/gen_landmarks.py из объектов OSM (reference.sqlite), не править.\n"
        f"# Сетевые бренды: >= {args.min_cities} городов или >= {args.min_objects} объектов, без совпадений с\n"
        "# топонимами и маркерами. Ручной список в landmarks.yaml. © участники OpenStreetMap, ODbL 1.0.\n"
    )
    body = yaml.safe_dump({"brands": sorted(brands, key=lambda s: (fold(s), s))}, allow_unicode=True, width=110)
    args.out.write_text(head + body, encoding="utf-8")
    print(f"{args.out}: брендов {len(brands)}, отсеяно {dict(skipped)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
