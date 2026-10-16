"""Короткий фаззинг на каждом прогоне тестов (полный: scripts/fuzz.py --n 20000)."""

from __future__ import annotations

import json
import random

import pytest
from scripts.fuzz import JUNK, check, gen

from jana_address import io_format


# id по номеру: длинные строки в имени теста упираются в лимит переменной окружения Windows
@pytest.mark.parametrize("raw", JUNK, ids=[f"junk{i}" for i in range(len(JUNK))])
def test_junk_never_breaks(raw: str) -> None:
    assert check(raw, max_ms=500) == []


def test_random_inputs_keep_invariants() -> None:
    bad = [(raw, p) for raw in gen(random.Random(7), 600) if (p := check(raw, max_ms=500))]
    assert bad == []


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "utf-16", "cp1251"])
def test_input_encodings(encoding: str) -> None:
    body = json.dumps([{"id": "1", "raw_address": "ул Абая 1"}], ensure_ascii=False).encode(encoding)
    records, _ = io_format.loads(body)
    assert records[0]["raw_address"] == "ул Абая 1"
