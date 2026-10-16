"""Формальные требования жюри: ровно один ответ на запись, порядок, id/raw_address байт в байт, null вместо пустых."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from jana_address import engine, io_format
from jana_address.models import OUTPUT_KEYS

FIX = Path(__file__).parent / "fixtures"

TRICKY = [
    {"id": "a", "raw_address": "ул.\u00a0Абая\u200b 150, кв\u200b 23\ufeff"},
    {"id": "b", "raw_address": ""},
    {"id": "c", "raw_address": "   "},
    {"id": "d", "raw_address": None},
    {"id": 42, "raw_address": "\x00\x01 мусор \u2060\u200d"},
    {"id": "e", "raw_address": "/" * 500},
    {"id": "f", "raw_address": "1/2/3/4 кв кв кв дом дом этаж"},
    {"raw_address": "без id"},
    {"id": "g"},
    {"id": "h", "raw_address": "😀 Алматы \U0001f3e0 Абая 1"},
]


def check_results(inputs: list[dict[str, Any]], results: list[dict[str, Any]]) -> None:
    assert len(results) == len(inputs)
    for rec, out in zip(inputs, results, strict=True):
        assert tuple(out.keys()) == OUTPUT_KEYS
        assert out["id"] == rec.get("id")
        assert out["raw_address"] == rec.get("raw_address")
        if isinstance(rec.get("raw_address"), str):
            assert out["raw_address"].encode("utf-8") == rec["raw_address"].encode("utf-8")
        for k in OUTPUT_KEYS[2:-1]:
            assert out[k] is None or (isinstance(out[k], str) and out[k].strip() != "")
        assert isinstance(out["confidence"], float | int)
        assert 0.0 <= out["confidence"] <= 1.0


def test_sample_fixture_contract() -> None:
    records, _ = io_format.loads((FIX / "sample_input.json").read_bytes())
    check_results(records, engine.parse_many(records))


def test_tricky_inputs_never_crash() -> None:
    check_results(TRICKY, engine.parse_many(TRICKY))


def test_exception_in_step_gives_null_record(monkeypatch: pytest.MonkeyPatch) -> None:
    pipe = engine.get_pipeline()

    def boom(_: str) -> Any:
        raise RuntimeError("boom")

    monkeypatch.setattr(pipe, "run", boom)
    res = engine.parse_many([{"id": "x", "raw_address": "Абая 1"}])
    check_results([{"id": "x", "raw_address": "Абая 1"}], res)
    assert all(res[0][k] is None for k in OUTPUT_KEYS[2:-1])
    assert res[0]["confidence"] < 0.2


@pytest.mark.parametrize(
    "payload,kind",
    [
        ('[{"id":"1","raw_address":"Абая 1"}]', "list"),
        ('{"records":[{"id":"1","raw_address":"Абая 1"}]}', "object"),
        ('{"meta":{"v":1},"whatever":[{"id":"1","raw_address":"Абая 1"}]}', "object"),
        ('{"id":"1","raw_address":"Абая 1"}', "single"),
        ('{"id":"1","raw_address":"Абая 1"}\n{"id":"2","raw_address":"Абая 2"}\n', "jsonl"),
        ('\ufeff[{"id":"1","raw_address":"Абая 1"}]', "list"),
    ],
)
def test_container_roundtrip(payload: str, kind: str) -> None:
    records, cont = io_format.loads(payload.encode("utf-8"))
    assert cont.kind == kind
    results = engine.parse_many(records)
    dumped = io_format.dumps(results, cont)
    if kind == "jsonl":
        back = [json.loads(x) for x in dumped.splitlines()]
    else:
        obj = json.loads(dumped)
        back = io_format.from_obj(obj)[0]
    assert [r["id"] for r in back] == [r["id"] for r in records]
    if kind == "object":
        src = json.loads(payload)
        assert set(json.loads(dumped).keys()) == set(src.keys())
