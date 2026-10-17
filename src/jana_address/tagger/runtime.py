"""Инференс теггера: ONNX (эмиссии BiLSTM) + CRF на numpy. Без torch, без сети.

Батчами: строки сортируются по длине, паддинг внутри батча до самой длинной, батч до 256 строк.
Модель видит первые max_len символов исходной строки; дальше всё считается O.
Кэшей по строке нет (tests/test_no_memorization.py): каждая строка размечается заново.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from .crf import marginals, viterbi
from .features import FEATURES_VERSION, LABELS, TAGS, encode_batch, spans_of

log = logging.getLogger(__name__)
FloatArray = npt.NDArray[np.float32]
IntArray = npt.NDArray[np.int64]
BATCH = 256
WARMUP = ("г. Алматы, ул. Абая 150/2, кв 5", "Нурсити 2 микрорайон 11дом", "Astana, Mangilik El 55, flat 191", "")


@dataclass(frozen=True)
class Span:
    label: str
    start: int  # [start, end) в символах raw
    end: int
    p_mean: float  # средняя маргинальная вероятность тегов спана
    p_cal: float  # откалиброванная на val вероятность «спан верен целиком»


@dataclass
class Prediction:
    n: int  # сколько символов raw размечено
    tags: IntArray
    class_probs: FloatArray  # [n, 1 + len(LABELS)]: P(O), P(класс) = P(B-) + P(I-)
    spans: list[Span] = field(default_factory=list)

    def label_prob(self, start: int, end: int, label: str) -> float:
        """Средняя по символам [start, end) вероятность класса label (O = «не поле»)."""
        s, e = max(0, start), min(end, self.n)
        if s >= e:
            return 0.0
        k = 0 if label == "O" else 1 + LABELS.index(label)
        return float(self.class_probs[s:e, k].mean())

    def of(self, label: str) -> list[Span]:
        return [sp for sp in self.spans if sp.label == label]

    def to_json(self) -> list[dict[str, Any]]:
        return [
            {"label": s.label, "start": s.start, "end": s.end, "p": round(s.p_mean, 3), "p_cal": round(s.p_cal, 3)}
            for s in self.spans
        ]


class Tagger:
    def __init__(self, model_path: Path, meta_path: Path, threads: int | None = None) -> None:
        import onnxruntime as ort  # ленивый импорт: без onnxruntime сервис работает на правилах

        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("features_version") != FEATURES_VERSION or tuple(meta.get("tags", ())) != TAGS:
            raise ValueError(
                f"tagger_meta несовместим: features {meta.get('features_version')}, теги {meta.get('tags')}"
            )
        self.meta = meta
        self.version: str = str(meta.get("version", "?"))
        self.max_len = int(meta["max_len"])
        self.vocab = {c: i + 2 for i, c in enumerate(meta["chars"])}
        self.trans = np.asarray(meta["crf"]["trans"], dtype=np.float32)
        self.start = np.asarray(meta["crf"]["start"], dtype=np.float32)
        self.end = np.asarray(meta["crf"]["end"], dtype=np.float32)
        self.calib: dict[str, tuple[FloatArray, FloatArray]] = {
            lab: (np.asarray(k["x"], dtype=np.float32), np.asarray(k["y"], dtype=np.float32))
            for lab, k in meta.get("calibration", {}).items()
        }
        so = ort.SessionOptions()
        so.intra_op_num_threads = (
            threads or int(os.environ.get("JANA_TAGGER_THREADS", "0")) or min(4, os.cpu_count() or 1)
        )
        so.inter_op_num_threads = 1
        so.log_severity_level = 3
        self.session = ort.InferenceSession(str(model_path), so, providers=["CPUExecutionProvider"])
        t0 = time.perf_counter()
        self.predict(WARMUP)
        self.warmup_ms = round((time.perf_counter() - t0) * 1000, 1)

    # ---------- инференс ----------
    def emissions(self, chars: IntArray, case: IntArray, cls: IntArray, lengths: IntArray) -> FloatArray:
        out = self.session.run(["emissions"], {"chars": chars, "case": case, "cls": cls, "lengths": lengths})
        return np.asarray(out[0], dtype=np.float32)

    def calibrate(self, label: str, p: float) -> float:
        k = self.calib.get(label)
        return float(np.interp(p, k[0], k[1])) if k is not None and len(k[0]) else p

    def predict(self, raws: Sequence[str]) -> list[Prediction]:
        out: list[Prediction | None] = [None] * len(raws)
        order = sorted(range(len(raws)), key=lambda i: len(raws[i]))
        for b0 in range(0, len(order), BATCH):
            idx = order[b0 : b0 + BATCH]
            chars, case, cls, lengths = encode_batch([raws[i] for i in idx], self.vocab, self.max_len)
            em = self.emissions(chars, case, cls, lengths)
            paths = viterbi(em, lengths, self.trans, self.start, self.end)
            marg = marginals(em, lengths, self.trans, self.start, self.end)
            for j, i in enumerate(idx):
                n = min(len(raws[i]), self.max_len)
                out[i] = self._build(paths[j][:n], marg[j, :n])
        return [p for p in out if p is not None]

    def _build(self, path: IntArray, marg: FloatArray) -> Prediction:
        n = len(path)
        cp = np.zeros((n, 1 + len(LABELS)), dtype=np.float32)
        cp[:, 0] = marg[:, 0]
        cp[:, 1:] = marg[:, 1::2] + marg[:, 2::2]
        spans = []
        for s, e, lab in spans_of(path):
            p = float(marg[np.arange(s, e), path[s:e]].mean())
            spans.append(Span(lab, s, e, p, self.calibrate(lab, p)))
        return Prediction(n=n, tags=path, class_probs=cp, spans=spans)

    def info(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "max_len": self.max_len,
            "warmup_ms": self.warmup_ms,
            "metrics": self.meta.get("metrics", {}),
        }


def load(model_path: Path, meta_path: Path) -> Tagger | None:
    """Модель или None: нет файлов, нет onnxruntime, несовместимая meta. Сервис тогда работает на правилах."""
    if not model_path.exists() or not meta_path.exists():
        log.error("теггер не найден (%s), работаем только на правилах: метрика ниже", model_path)
        return None
    try:
        return Tagger(model_path, meta_path)
    except Exception:
        log.exception("теггер не загрузился, работаем на правилах")
        return None
