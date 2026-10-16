"""Серебряная разметка: только в data/, спаны из разбора правил совпадают со значениями полей."""

from __future__ import annotations

from pathlib import Path

import pytest
from training.silver import ROOT, check_out_path, spans_from_state

from jana_address.pipeline.runner import Pipeline
from jana_address.pipeline.util import tidy_value


def test_out_path_only_inside_data(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        check_out_path(tmp_path / "silver.jsonl")
    with pytest.raises(SystemExit):
        check_out_path(ROOT / "tests" / "fixtures" / "silver.jsonl")
    assert check_out_path(ROOT / "data" / "tagger" / "silver.jsonl")


def test_spans_from_rules_state() -> None:
    raw = "г. Алматы, ул. Абая 150, кв 5, тел. 87011234567"
    state = Pipeline(tagger_mode="off").run(raw)
    spans = spans_from_state(state)
    assert spans is not None
    by = {lab: tidy_value(raw[s:e]) for s, e, lab in spans}
    assert by["STREET_NAME"] == "Абая" and by["HOUSE"] == "150" and by["APARTMENT"] == "5"
    assert "87011234567" in by["NOISE"]
