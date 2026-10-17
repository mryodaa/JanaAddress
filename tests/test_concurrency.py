"""Один Pipeline на процесс обслуживает параллельные запросы (to_thread в API, потоки сессий): шаги не должны
держать состояние записи в атрибутах, иначе запись проверяется по чужой строке."""

from __future__ import annotations

import json
import random
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from jana_address import engine

FIX = Path(__file__).parent / "fixtures"

EXTRA = [
    "г. Алматы, ул. Абая 150, кв 23",
    "Астана Кенесары 40 кв 12",
    "город Актобе/Ақтөбе қаласы, мкр Батыс-2, 15/1",
    "Шымкент, Тауке хана 7",
    "Караганда Бухар жырау 52 подъезд 3 этаж 4",
    "Боралдай, ул. Ленина 1/2",
    "Илийский район, Отеген батыра, Гагарина 10",
    "66квартал 12дом 69квартира",
    "Туран 55/6 магазин береке 4подьезд 9этаж",
    "Нурсити 2 микрорайон 11дом 5 подьезд 239 кв",
]


def _records() -> list[dict[str, Any]]:
    recs: list[dict[str, Any]] = json.loads((FIX / "sample_input.json").read_text(encoding="utf-8"))
    recs += [{"id": f"x{i}", "raw_address": s} for i, s in enumerate(EXTRA)]
    return recs


def test_parallel_parse_matches_serial() -> None:
    recs = _records()
    serial = {r["id"]: engine.parse_one(r, explain=False) for r in recs}
    jobs = recs * 6
    random.Random(7).shuffle(jobs)
    with ThreadPoolExecutor(max_workers=8) as pool:
        got = list(pool.map(lambda r: (r["id"], engine.parse_one(r, explain=False)), jobs))
    for rid, out in got:
        assert out == serial[rid], rid
