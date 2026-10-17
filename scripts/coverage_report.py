"""Покрытие восстановления по справочнику: какая доля записей получила district, living_area, street_type, city,
province и из какого источника (строка, reference:osm:house, reference:osm:street, ...).

    python scripts/coverage_report.py IN.json [IN2.json ...] [--db reference/reference.sqlite] [--md OUT.md]
    python scripts/coverage_report.py data/dev_chaos.json --db reference/reference.synth_v1.sqlite   # «до»

Эталон не нужен: считается только, заполнено ли поле и кем. Качество восстановленных значений меряет eval.py
(справочные поля входят в метрику, только если написаны в строке). Строки входа в отчёт не попадают.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

FIELDS = ("province", "city", "district", "living_area", "street_type")


def coverage(out: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """Поле -> {"filled": n, "string": n, "<источник>": n}."""
    res: dict[str, Counter[str]] = {f: Counter() for f in FIELDS}
    for rec in out:
        fields = rec.get("fields") or {}
        for f in FIELDS:
            if rec.get(f) is None:
                continue
            src = (fields.get(f) or {}).get("source") or "string"
            res[f]["filled"] += 1
            res[f][src] += 1
    return {f: dict(c) for f, c in res.items()}


def table(name: str, n: int, cov: dict[str, dict[str, int]]) -> str:
    lines = [
        f"**{name}** ({n} записей)\n",
        "| поле | заполнено | из строки | из справочника | по источникам справочника |",
        "|---|---:|---:|---:|---|",
    ]
    for f in FIELDS:
        c = cov[f]
        filled, string = c.get("filled", 0), c.get("string", 0)
        refs = {k: v for k, v in c.items() if k.startswith("reference:")}
        by = ", ".join(f"{k.removeprefix('reference:')} {100 * v / n:.1f}%" for k, v in sorted(refs.items()))
        lines.append(
            f"| {f} | {100 * filled / n:.1f}% | {100 * string / n:.1f}% | {100 * sum(refs.values()) / n:.1f}% | {by} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", type=Path)
    ap.add_argument("--db", type=Path, help="справочник (по умолчанию JANA_REFERENCE_DB / reference/reference.sqlite)")
    ap.add_argument("--md", type=Path, help="дописать таблицы в markdown-файл")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    if args.db:
        os.environ["JANA_REFERENCE_DB"] = str(args.db)  # до импорта пакета: config читает окружение при импорте
    from jana_address import engine, io_format

    parts = []
    for path in args.inputs:
        records, _ = io_format.loads(path.read_bytes())
        out = engine.parse_many([{"id": r.get("id"), "raw_address": r.get("raw_address")} for r in records], True)
        parts.append(table(path.name, len(out), coverage(out)))
        print(parts[-1])
    if args.md:
        with args.md.open("a", encoding="utf-8") as fh:
            fh.write("\n".join(parts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
