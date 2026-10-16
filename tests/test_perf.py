"""ТЗ: не больше 5 минут на 1000 записей, целимся в единицы секунд."""

from __future__ import annotations

import time

import pytest
from scripts.benchmark import synthetic_records

from jana_address import engine


@pytest.mark.perf
def test_1000_records_fast() -> None:
    records = synthetic_records(1000, seed=1)
    engine.get_pipeline()  # загрузка справочника не входит в замер
    t0 = time.perf_counter()
    out = engine.parse_many(records)
    dt = time.perf_counter() - t0
    assert len(out) == 1000
    print(f"\n1000 записей: {dt:.2f} с")
    assert dt < 30, f"1000 записей за {dt:.1f} с"
