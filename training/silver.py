"""Серебряная разметка для теггера из живых строк: data/train.json (когда выдадут) и data/dev_gold.json.

    .venv/Scripts/python -m training.silver [--train data/train.json] [--gold data/dev_gold.json] \
        [--min-conf 0.85] [--out data/tagger/silver.jsonl]

train.json: берутся только записи, где правила уверены (confidence >= --min-conf) и разбор подтверждён
справочником (улица или дом найдены). Спаны полей из разбора (state.fields[*].span, координаты raw), KZ_DUP и
NOISE из токенов. Поле из строки без спана (город/область из admin без позиции) -> запись пропускается.
dev_gold.json: спаны ищутся однозначным вхождением эталонного значения в raw; неоднозначное -> пропуск.

Строки живых данных пишутся только в data/ (в .gitignore и .dockerignore): не в репозиторий, тесты, фикстуры.
Дальше: python -m training.train ... --extra data/tagger/silver.jsonl
"""

from __future__ import annotations

import argparse
import itertools
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
sys.path.insert(0, str(ROOT / "src"))

from jana_address import io_format  # noqa: E402
from jana_address.models import PARSED_FIELDS  # noqa: E402
from jana_address.pipeline.base import SOURCE_STRING, ParseState  # noqa: E402
from jana_address.pipeline.runner import Pipeline  # noqa: E402
from jana_address.pipeline.util import trim_span  # noqa: E402

CANONICAL = ("province", "city", "district")
CONFIRMED = ("street_in_reference", "house_in_reference")


def check_out_path(path: Path) -> Path:
    """Живые строки только внутри data/."""
    p = path.resolve()
    if not p.is_relative_to(DATA.resolve()):
        raise SystemExit(f"{path}: серебряная разметка пишется только в data/ (там живые строки)")
    return p


def spans_from_state(state: ParseState) -> list[list[Any]] | None:
    out: list[list[Any]] = []
    for f, fv in state.fields.items():
        if fv.source != SOURCE_STRING:
            continue
        if fv.span is None:
            return None
        s, e = trim_span(state.raw, *fv.span)
        if s < e:
            out.append([s, e, f.upper()])
    for t in state.tokens:
        label = "KZ_DUP" if t.used_by == "kz_dup" else "NOISE" if (t.used_by or "").startswith("noise") else None
        if label:
            s, e = state.orig_span(t.start, t.end)
            if out and out[-1][2] == label and not state.raw[out[-1][1] : s].strip(" ,"):
                out[-1][1] = e  # соседние токены одного класса: один спан
            else:
                out.append([s, e, label])
    out.sort()
    if any(a[1] > b[0] for a, b in itertools.pairwise(out)):
        return None  # пересечение полей: разбор сомнительный
    return out


def from_train(path: Path, min_conf: float) -> list[dict[str, Any]]:
    records, _ = io_format.loads(path.read_bytes())
    pipe = Pipeline(tagger_mode="off")
    rows = []
    for r in records:
        raw = r.get("raw_address")
        if not isinstance(raw, str) or not raw.strip():
            continue
        state = pipe.run(raw)
        if state.confidence < min_conf or not any(f in state.flags for f in CONFIRMED):
            continue
        spans = spans_from_state(state)
        if spans:
            rows.append({"raw": raw, "spans": spans, "source": "silver"})
    return rows


def from_gold(path: Path) -> list[dict[str, Any]]:
    records, _ = io_format.loads(path.read_bytes())
    rows = []
    for g in records:
        raw = g.get("raw_address")
        if not isinstance(raw, str):
            continue
        spans, ok = [], True
        for f in PARSED_FIELDS:
            v = g.get(f)
            if not v or f in (g.get("_from_reference") or []):
                continue
            hits = [m.start() for m in re.finditer(re.escape(str(v)), raw, flags=re.I)]
            if len(hits) != 1:
                ok = f in CANONICAL and not hits  # canonical-поле может быть записано иначе: просто без спана
                if not ok:
                    break
                continue
            spans.append([hits[0], hits[0] + len(str(v)), f.upper()])
        spans.sort()
        if ok and not any(a[1] > b[0] for a, b in itertools.pairwise(spans)):
            rows.append({"raw": raw, "spans": spans, "source": "gold"})
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--train", type=Path, default=DATA / "train.json")
    ap.add_argument("--gold", type=Path, default=DATA / "dev_gold.json")
    ap.add_argument("--min-conf", type=float, default=0.85)
    ap.add_argument("--out", type=Path, default=DATA / "tagger" / "silver.jsonl")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    out = check_out_path(args.out)
    rows: list[dict[str, Any]] = []
    if args.train.exists():
        rows += from_train(args.train, args.min_conf)
    if args.gold.exists():
        rows += from_gold(args.gold)
    if not rows:
        print("нет живых данных (data/train.json, data/dev_gold.json): серебряная разметка пуста")
        return 0
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"{len(rows)} строк -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
