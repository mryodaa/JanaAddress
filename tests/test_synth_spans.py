"""Синтетика с посимвольной разметкой: метки едут вместе с мутациями строки, dev-наборы воспроизводятся."""

from __future__ import annotations

import json
import random
import re
from pathlib import Path

import pytest
from scripts.synth.builder import HOLDOUT_CITY_PCT, HOLDOUT_STREET_PCT, STRING_FIELDS, Builder, Ref, held_out
from scripts.synth.labeled import LText, fmt

from jana_address import config
from jana_address.pipeline.util import tidy_value

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(
    not config.SYNTH_DB.exists(),
    reason=f"нет {config.SYNTH_DB.name} (снапшот справочника для синтетики, не в git): "
    "скопировать reference/reference.sqlite той версии, на которой строились dev-наборы",
)


def test_ltext_ops() -> None:
    t = LText.of("ул. ") + LText.of("Айтеке би", "STREET_NAME") + " " + fmt("д.{}", "5", "HOUSE")
    assert t.spans() == [(4, 13, "STREET_NAME"), (16, 17, "HOUSE")]
    # пробел внутри названия остаётся в нём, на границе получает O
    t2 = t.sub(r" ", lambda _: "  ")
    assert [t2.text[s:e] for s, e, _ in t2.spans()] == ["Айтеке  би", "5"]
    # невидимый символ внутри слова наследует метку, на границе нет
    t.insert(6, "\u200b")
    assert t.text[4:14] == "Ай\u200bтеке би" and t.spans()[0] == (4, 14, "STREET_NAME")
    up = t.upper()
    assert up.text.startswith("УЛ. АЙ") and up.spans() == t.spans()


def test_adjacent_same_label_not_merged() -> None:
    t = LText.of("Алматы", "CITY") + LText.of("Алматы", "CITY")
    assert t.spans() == [(0, 6, "CITY"), (6, 12, "CITY")]


def _check_spans(rec: dict[str, object], raw_key: str = "raw_address", spans_key: str = "_spans") -> list[str]:
    raw = str(rec[raw_key])
    by: dict[str, list[str]] = {}
    for s, e, lab in rec[spans_key]:  # type: ignore[attr-defined]
        assert 0 <= s < e <= len(raw)
        by.setdefault(lab, []).append(re.sub(r"\s+", " ", tidy_value(raw[s:e])))
    bad = []
    for f in STRING_FIELDS:
        v = rec[f]
        if v is None or f in rec["_from_reference"]:  # type: ignore[operator]
            continue
        # tidy_value срезает краевую точку («Байтурсынов А.»): метрика пунктуацию всё равно не сравнивает
        v = re.sub(r"\s+", " ", str(v)).rstrip(".-")
        if v not in by.get(f.upper(), []):
            bad.append(f"{f}={v!r} нет среди {by.get(f.upper())} в {raw!r}")
    return bad


@pytest.mark.parametrize(("chaos", "strong"), [(False, False), (True, False), (True, True), (False, True)])
def test_spans_match_gold(chaos: bool, strong: bool) -> None:
    b = Builder(Ref(config.SYNTH_DB), random.Random(5), chaos=chaos, strong=strong)
    bad = [p for i in range(400) for p in _check_spans(b.record(i))]
    assert bad == []


@pytest.mark.parametrize(
    ("name", "seed", "n", "chaos"),
    [("dev_synth", 1, 150, False), ("dev_synth_s2", 2, 150, False), ("dev_chaos", 11, 150, True),
     ("dev_chaos_holdout", 99, 150, True)],
)  # fmt: skip
def test_dev_sets_reproducible(name: str, seed: int, n: int, chaos: bool) -> None:
    """Перенос генератора в scripts/synth не сдвинул RNG: отложенные наборы те же байт в байт."""
    path = ROOT / "data" / f"{name}.json"
    if not path.exists():
        pytest.skip(f"нет {path.name}")
    old = json.loads(path.read_text(encoding="utf-8"))[:n]
    b = Builder(Ref(config.SYNTH_DB), random.Random(seed), chaos=chaos)
    new = [b.record(i + 1) for i in range(n)]
    for o, r in zip(old, new, strict=True):
        r.pop("_spans")
        o.pop("_spans", None)
        assert r == o


def test_split_disjoint() -> None:
    train, unseen = Ref(config.SYNTH_DB, "train"), Ref(config.SYNTH_DB, "unseen")
    for c in train.cities.values():
        assert not (c.streets and c.kind != "republican" and held_out("city", c.id, HOLDOUT_CITY_PCT))
        assert not any(held_out("street", s[0], HOLDOUT_STREET_PCT) for s in c.streets)
    train_ids = {s[0] for c in train.cities.values() for s in c.streets}
    unseen_ids = {s[0] for c in unseen.cities.values() for s in c.streets}
    assert unseen_ids and not train_ids & unseen_ids
