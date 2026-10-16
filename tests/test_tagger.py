"""Теггер: признаки, CRF на numpy, рантайм и поведение пайплайна, когда модели нет или она падает."""

from __future__ import annotations

import itertools
from pathlib import Path

import numpy as np
import pytest
from tests.tagger_fakes import FakeTagger, find, pipeline_with

from jana_address import config
from jana_address.pipeline.runner import Pipeline, parse_records
from jana_address.tagger import runtime
from jana_address.tagger.crf import marginals, viterbi
from jana_address.tagger.features import (
    CLS_DIGIT,
    CLS_INVIS,
    CLS_KAZ,
    CLS_LAT,
    TAGS,
    allowed_transitions,
    bio,
    char_class,
    encode_batch,
    spans_of,
)

RAW = "г. Алматы, ул. Абая 150, кв 5"


def test_bio_roundtrip() -> None:
    spans = [(3, 9, "CITY"), (15, 19, "STREET_NAME"), (20, 23, "HOUSE"), (28, 29, "APARTMENT")]
    assert spans_of(bio(spans, len(RAW))) == spans


def test_char_classes() -> None:
    assert char_class("қ") == CLS_KAZ and char_class("k") == CLS_LAT and char_class("7") == CLS_DIGIT
    assert char_class("\u200b") == CLS_INVIS and char_class("\u00ad") == CLS_INVIS


def test_encode_batch_padding_and_empty() -> None:
    chars, _, _, lengths = encode_batch(["Абая 1", ""], {"а": 2}, 256)
    assert chars.shape == (2, 6) and lengths.tolist() == [6, 1]
    assert chars[1].tolist() == [0] * 6  # пустая строка: один PAD, длина 1


def _brute(em: np.ndarray, trans: np.ndarray, start: np.ndarray, end: np.ndarray) -> tuple[list[int], np.ndarray]:
    n, nlab = em.shape
    scores = {}
    for path in itertools.product(range(nlab), repeat=n):
        s = start[path[0]] + em[0, path[0]] + end[path[-1]]
        s += sum(trans[path[t - 1], path[t]] + em[t, path[t]] for t in range(1, n))
        scores[path] = s
    best = max(scores, key=lambda k: scores[k])
    z = np.logaddexp.reduce(np.array(list(scores.values())))
    marg = np.zeros((n, nlab))
    for path, s in scores.items():
        for t, y in enumerate(path):
            marg[t, y] += np.exp(s - z)
    return list(best), marg


def test_crf_matches_brute_force() -> None:
    rng = np.random.default_rng(3)
    nlab = 4
    trans = rng.normal(size=(nlab, nlab)).astype(np.float32)
    start, end = rng.normal(size=nlab).astype(np.float32), rng.normal(size=nlab).astype(np.float32)
    em = rng.normal(size=(2, 5, nlab)).astype(np.float32)
    lengths = np.array([5, 3])
    paths = viterbi(em, lengths, trans, start, end)
    marg = marginals(em, lengths, trans, start, end)
    for b in range(2):
        n = int(lengths[b])
        best, bm = _brute(em[b, :n], trans, start, end)
        assert paths[b].tolist() == best
        assert np.allclose(marg[b, :n], bm, atol=1e-4)
        assert np.all(marg[b, n:] == 0)


def test_bio_mask() -> None:
    allowed, start_ok = allowed_transitions()
    i_city, b_city, b_house = TAGS.index("I-CITY"), TAGS.index("B-CITY"), TAGS.index("B-HOUSE")
    assert allowed[b_city, i_city] and allowed[i_city, i_city]
    assert not allowed[b_house, i_city] and not allowed[0, i_city] and not start_ok[i_city]


def test_runtime_load_missing_returns_none(tmp_path: Path) -> None:
    assert runtime.load(tmp_path / "nope.onnx", tmp_path / "nope.json") is None


def test_runtime_rejects_incompatible_meta(tmp_path: Path) -> None:
    model, meta = tmp_path / "m.onnx", tmp_path / "m.json"
    model.write_bytes(b"not onnx")
    meta.write_text('{"features_version": 999, "tags": []}', encoding="utf-8")
    assert runtime.load(model, meta) is None


@pytest.mark.skipif(not config.TAGGER_MODEL.exists(), reason="models/tagger.onnx не собран")
def test_real_model_edge_inputs() -> None:
    t = runtime.load(config.TAGGER_MODEL, config.TAGGER_META)
    assert t is not None
    preds = t.predict(["", "\u200b\u200b", "Абая " * 2000, RAW])
    assert preds[0].n == 0 and preds[1].n == 2 and preds[2].n == t.max_len
    assert all(0 <= s.start < s.end <= len(RAW) for s in preds[3].spans)


def _fields(out: dict[str, object]) -> dict[str, object]:
    return {k: v for k, v in out.items() if k not in ("trace", "fields", "unparsed", "model")}


def test_failing_model_falls_back_to_rules() -> None:
    recs = [{"id": i, "raw_address": RAW} for i in range(3)]
    base = parse_records(Pipeline(tagger_mode="off"), recs)
    fake = FakeTagger(fail=True)
    out = parse_records(pipeline_with(fake, "on"), recs)
    assert [_fields(o) for o in out] == [_fields(b) for b in base]
    assert fake.calls >= 1


def test_batch_predicted_once() -> None:
    fake = FakeTagger()
    recs = [{"id": i, "raw_address": f"ул. Абая {i}"} for i in range(5)] + [{"id": "x", "raw_address": None}]
    out = parse_records(pipeline_with(fake, "shadow"), recs)
    assert fake.calls == 1 and len(out) == 6 and out[-1]["street_name"] is None


def test_shadow_never_changes_fields() -> None:
    raw = "Бесагаш Айтеке би, 68 кв14"
    fake = FakeTagger(
        {raw: [find(raw, "Бесагаш", "CITY"), find(raw, "Айтеке би", "STREET_NAME"), find(raw, "68", "HOUSE")]}
    )
    recs = [{"id": 1, "raw_address": raw}]
    base = parse_records(Pipeline(tagger_mode="off"), recs)
    shadow = parse_records(pipeline_with(fake, "shadow"), recs, explain=True)
    assert _fields(shadow[0]) | {"confidence": None} == _fields(base[0]) | {"confidence": None}
    assert shadow[0]["model"]["fields"]["street_name"]["decision"] == "model"  # type: ignore[index]
