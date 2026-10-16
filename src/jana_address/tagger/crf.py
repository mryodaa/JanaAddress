"""Линейный CRF на numpy: Витерби и маргиналы (forward-backward в log-space), батчем с разными длинами.

Счёт пути y: start[y0] + Σ em[t, y_t] + Σ trans[y_{t-1}, y_t] + end[y_last]. Запрещённые переходы BIO
уже лежат в trans/start как большие отрицательные числа (обучение их не меняет, см. training/model.py).
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float32]
IntArray = npt.NDArray[np.int64]


def _logsumexp(x: FloatArray, axis: int) -> FloatArray:
    m = x.max(axis=axis, keepdims=True)
    out = np.log(np.exp(x - m).sum(axis=axis, keepdims=True)) + m
    return np.squeeze(out, axis=axis)


def viterbi(em: FloatArray, lengths: IntArray, trans: FloatArray, start: FloatArray, end: FloatArray) -> list[IntArray]:
    """em [B, T, L] -> лучший путь тегов для каждой строки (длины lengths[b])."""
    bsz, width, _ = em.shape
    score = start[None, :] + em[:, 0]
    back = np.zeros(em.shape, dtype=np.int64)
    for t in range(1, width):
        cand = score[:, :, None] + trans[None]
        back[:, t] = cand.argmax(axis=1)
        nxt = cand.max(axis=1) + em[:, t]
        score = np.where((lengths > t)[:, None], nxt, score)
    last = (score + end[None, :]).argmax(axis=1)
    paths: list[IntArray] = []
    for b in range(bsz):
        n = int(lengths[b])
        path = np.empty(n, dtype=np.int64)
        path[n - 1] = last[b]
        for t in range(n - 1, 0, -1):
            path[t - 1] = back[b, t, path[t]]
        paths.append(path)
    return paths


def marginals(em: FloatArray, lengths: IntArray, trans: FloatArray, start: FloatArray, end: FloatArray) -> FloatArray:
    """P(y_t = j | x) для каждой позиции, [B, T, L]; за пределами длины нули."""
    bsz, width, nlab = em.shape
    alpha = np.empty_like(em)
    alpha[:, 0] = start[None, :] + em[:, 0]
    for t in range(1, width):
        alpha[:, t] = _logsumexp(alpha[:, t - 1][:, :, None] + trans[None], axis=1) + em[:, t]
    beta = np.zeros_like(em)
    nxt = np.zeros((bsz, nlab), dtype=em.dtype)
    for t in range(width - 1, -1, -1):
        if t + 1 < width:
            step = _logsumexp(trans[None] + (em[:, t + 1] + nxt)[:, None, :], axis=2)
        else:
            step = np.zeros((bsz, nlab), dtype=em.dtype)
        cur = np.where((lengths - 1 == t)[:, None], end[None, :], np.where((lengths - 1 > t)[:, None], step, 0.0))
        beta[:, t] = cur
        nxt = cur
    last = alpha[np.arange(bsz), lengths - 1]
    log_z = _logsumexp(last + end[None, :], axis=1)
    # за пределами длины alpha копится без маски: там exp переполнился бы, поэтому -inf до exp
    mask = np.arange(width)[None, :] < lengths[:, None]
    logp = np.where(mask[:, :, None], alpha + beta - log_z[:, None, None], -np.inf)
    return np.exp(logp).astype(np.float32)
