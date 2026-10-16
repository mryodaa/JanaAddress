"""Бенчмарк скорости: python scripts/benchmark.py [--n 1000] [--file data/train.json] [--api http://localhost:8000]

Без --file генерирует синтетические адреса из шаблонов (строки train.json сюда не попадают).
С --api гоняет батч через HTTP, как жюри.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

CITIES = ["г. Алматы", "Алматы", "город Астана/Астана қаласы", "г.Шымкент", "Караганда", "г. Актобе", ""]
STREETS = [
    "ул. Абая",
    "пр. Достык",
    "Толе би",
    "мкр Аксай 3а",
    "Назарбаева",
    "ул.Курильская",
    "Абай көшесі",
    "мкр. Самал-2, ул. Жолдасбекова",
    "Рыбинский переулок",
    "ул Казыбек би",
    "Туран",
]
TAILS = [
    "{h}",
    "{h}, кв {a}",
    "{h} кв{a}",
    "д. {h}, кв. {a}, подъезд {e}, этаж {f}",
    "{h}дом {e}подьезд {a}кв",
    "{h}/{e}",
    "{h}а, {a}",
    "дом {h} flat {a}",
    "{h}-{a}",
    "{h} магазин береке",
]


def synthetic_records(n: int, seed: int = 0) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    out = []
    for i in range(n):
        tail = rng.choice(TAILS).format(
            h=rng.randint(1, 300), a=rng.randint(1, 400), e=rng.randint(1, 9), f=rng.randint(1, 16)
        )
        parts = [p for p in (rng.choice(CITIES), rng.choice(STREETS)) if p]
        raw = ", ".join(parts) + " " + tail
        if rng.random() < 0.1:
            raw = raw.replace(" ", "\u00a0", 1) + "\u200b"
        out.append({"id": f"bench_{i:05d}", "raw_address": raw})
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=1000)
    ap.add_argument("--file", type=Path)
    ap.add_argument("--api", help="URL сервиса, например http://localhost:8000")
    args = ap.parse_args(argv)

    if args.file:
        from jana_address import io_format

        records = io_format.loads(args.file.read_bytes())[0][: args.n]
    else:
        records = synthetic_records(args.n)

    if args.api:
        body = json.dumps(records, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            f"{args.api.rstrip('/')}/api/v1/parse/batch", data=body, headers={"content-type": "application/json"}
        )
        t0 = time.perf_counter()
        with urllib.request.urlopen(req, timeout=600) as resp:
            out = json.loads(resp.read())
        dt = time.perf_counter() - t0
    else:
        from jana_address import engine

        t0 = time.perf_counter()
        engine.get_pipeline()
        load = time.perf_counter() - t0
        print(f"загрузка справочника и правил: {load:.2f} с")
        t0 = time.perf_counter()
        out = engine.parse_many(records)
        dt = time.perf_counter() - t0
    assert len(out) == len(records)
    print(f"{len(records)} записей: {dt:.2f} с ({dt / max(1, len(records)) * 1000:.2f} мс/запись)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
