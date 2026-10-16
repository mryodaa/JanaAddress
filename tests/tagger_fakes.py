"""Поддельный теггер для тестов: разметка задаётся спанами, без onnx и обученной модели."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np

from jana_address.pipeline.runner import Pipeline
from jana_address.pipeline.tagger import ModelTag
from jana_address.tagger.features import LABELS, bio
from jana_address.tagger.runtime import Prediction, Span

FakeSpan = tuple[int, int, str, float]


def fake_prediction(raw: str, spans: Sequence[FakeSpan]) -> Prediction:
    n = len(raw)
    cp = np.zeros((n, 1 + len(LABELS)), dtype=np.float32)
    cp[:, 0] = 1.0
    for s, e, lab, p in spans:
        cp[s:e] = 0.0
        cp[s:e, 0] = 1 - p
        cp[s:e, 1 + LABELS.index(lab)] = p
    tags = bio([(s, e, lab) for s, e, lab, _ in spans], n)
    return Prediction(n=n, tags=tags, class_probs=cp, spans=[Span(lab, s, e, p, p) for s, e, lab, p in spans])


def find(raw: str, text: str, label: str, p: float = 0.97) -> FakeSpan:
    s = raw.index(text)
    return (s, s + len(text), label, p)


class FakeTagger:
    def __init__(self, table: dict[str, list[FakeSpan]] | None = None, fail: bool = False) -> None:
        self.table = table or {}
        self.fail = fail
        self.calls = 0

    def predict(self, raws: Sequence[str]) -> list[Prediction]:
        self.calls += 1
        if self.fail:
            raise RuntimeError("модель упала")
        return [fake_prediction(r, self.table.get(r, [])) for r in raws]

    def info(self) -> dict[str, Any]:
        return {"version": "fake"}


def pipeline_with(fake: FakeTagger | None, mode: str) -> Pipeline:
    p = Pipeline(tagger_mode=mode)
    for s in p.steps:
        if isinstance(s, ModelTag):
            s.tagger = fake  # type: ignore[assignment]
    return p
