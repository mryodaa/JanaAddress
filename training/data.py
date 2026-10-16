"""Данные теггера: JSONL {raw, spans} -> признаки (src/jana_address/tagger/features.py) и BIO-теги."""

from __future__ import annotations

import hashlib
import json
import random
import sys
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jana_address.tagger.features import bio, encode, norm_char, spans_of  # noqa: E402

MAX_LEN = 256


@dataclass
class Example:
    raw: str  # пусто для train (keep_raw=False): экономия памяти
    chars: np.ndarray  # uint8: словарь символов меньше 255
    case: np.ndarray
    cls: np.ndarray
    tags: np.ndarray


def read_jsonl(path: Path) -> list[dict[str, object]]:
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def iter_jsonl(paths: list[Path], limit: int = 0) -> Iterator[dict[str, object]]:
    n = 0
    for path in paths:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                yield json.loads(line)
                n += 1
                if limit and n >= limit:
                    return


def sha256_files(paths: list[Path]) -> str:
    h = hashlib.sha256()
    for p in paths:
        with p.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    return h.hexdigest()


def build_vocab(rows: Iterable[dict[str, object]], min_count: int = 3) -> list[str]:
    cnt: Counter[str] = Counter()
    for r in rows:
        cnt.update(norm_char(c) for c in str(r["raw"])[:MAX_LEN])
    chars = [c for c, n in cnt.most_common() if n >= min_count]
    assert len(chars) + 2 <= 255, "словарь не влезает в uint8"
    return chars


def to_examples(rows: Iterable[dict[str, object]], chars: list[str], keep_raw: bool = True) -> list[Example]:
    vocab = {c: i + 2 for i, c in enumerate(chars)}
    out = []
    for r in rows:
        raw = str(r["raw"])
        spans = [(int(s), int(e), str(lab)) for s, e, lab in r["spans"]]  # type: ignore[attr-defined]
        ch, ca, cl = encode(raw, vocab, MAX_LEN)
        if not len(ch):
            continue
        u8 = np.uint8
        out.append(
            Example(
                raw if keep_raw else "", ch.astype(u8), ca.astype(u8), cl.astype(u8), bio(spans, len(ch)).astype(u8)
            )
        )
    return out


def batches(
    exs: list[Example], size: int, rnd: random.Random | None, max_tokens: int = 8192
) -> Iterator[list[Example]]:
    """Батчи из примеров близкой длины (меньше паддинга), не больше size строк и max_tokens символов с паддингом:
    на ноутбучной GPU драйвер даёт выделить около 1.3 ГБ. При rnd порядок батчей случайный."""
    order = sorted(range(len(exs)), key=lambda i: (len(exs[i].chars), rnd.random() if rnd else 0))
    groups: list[list[int]] = [[]]
    for i in order:
        g = groups[-1]
        if g and (len(g) >= size or (len(g) + 1) * len(exs[i].chars) > max_tokens):
            groups.append([])
        groups[-1].append(i)
    groups = [g for g in groups if g]
    if rnd:
        rnd.shuffle(groups)
    for g in groups:
        yield [exs[i] for i in g]


def pad(exs: list[Example]) -> tuple[np.ndarray, ...]:
    width = max(len(e.chars) for e in exs)
    arr = [np.zeros((len(exs), width), dtype=np.int64) for _ in range(4)]
    for b, e in enumerate(exs):
        n = len(e.chars)
        arr[0][b, :n], arr[1][b, :n], arr[2][b, :n], arr[3][b, :n] = e.chars, e.case, e.cls, e.tags
    lengths = np.array([len(e.chars) for e in exs], dtype=np.int64)
    return arr[0], arr[1], arr[2], arr[3], lengths


def span_f1(gold: list[list[tuple[int, int, str]]], pred: list[list[tuple[int, int, str]]]) -> dict[str, object]:
    """Точное совпадение спана и метки; micro F1 и по меткам."""
    tp: Counter[str] = Counter()
    fp: Counter[str] = Counter()
    fn: Counter[str] = Counter()
    for g, p in zip(gold, pred, strict=True):
        gs, ps = set(g), set(p)
        for s in ps & gs:
            tp[s[2]] += 1
        for s in ps - gs:
            fp[s[2]] += 1
        for s in gs - ps:
            fn[s[2]] += 1

    def f1(t: int, f_p: int, f_n: int) -> float:
        return 2 * t / (2 * t + f_p + f_n) if t + f_p + f_n else 1.0

    labels = sorted(set(tp) | set(fp) | set(fn))
    return {
        "f1": f1(sum(tp.values()), sum(fp.values()), sum(fn.values())),
        "by_label": {lab: round(f1(tp[lab], fp[lab], fn[lab]), 4) for lab in labels},
    }


def decode(tags: np.ndarray) -> list[tuple[int, int, str]]:
    return spans_of(tags)
