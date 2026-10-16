"""Запасной путь для жюри: python -m jana_address.cli data/sample_input.json out.json"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from . import engine, io_format


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m jana_address.cli", description=__doc__)
    ap.add_argument("input", type=Path, help="файл в формате sample_input.json")
    ap.add_argument("output", type=Path, help="куда записать ответ (формат sample_output.json)")
    ap.add_argument("--explain", action="store_true", help="добавить источники полей и trace")
    ap.add_argument("--indent", type=int, default=2)
    args = ap.parse_args(argv)
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

    records, container = io_format.loads(args.input.read_bytes())
    t0 = time.perf_counter()
    results = engine.parse_many(records, explain=args.explain)
    dt = time.perf_counter() - t0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(io_format.dumps(results, container, indent=args.indent), encoding="utf-8")
    print(f"{len(results)} записей за {dt:.2f} с -> {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
