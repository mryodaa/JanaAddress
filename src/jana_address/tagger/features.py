"""Признаки символов и схема меток теггера. Один модуль на обучение и рантайм: признаки не могут разойтись.

Символ кодируется тремя числами: id символа (нижний регистр, все цифры -> «0»; словарь из обучающих данных,
0 = PAD, 1 = UNK), регистр и класс символа (кириллица / казахские буквы / латиница / цифра / пробел /
пунктуация / невидимый / прочее). Модель видит исходную строку raw как есть, до clean.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence

import numpy as np
import numpy.typing as npt

FEATURES_VERSION = 1
LABELS: tuple[str, ...] = (
    "PROVINCE",
    "CITY",
    "DISTRICT",
    "LIVING_AREA",
    "STREET_TYPE",
    "STREET_NAME",
    "HOUSE",
    "APARTMENT",
    "ENTRANCE",
    "FLOOR",
    "LANDMARK",
    "KZ_DUP",
    "NOISE",
)
TAGS: tuple[str, ...] = ("O", *(f"{p}-{lab}" for lab in LABELS for p in ("B", "I")))
TAG_ID = {t: i for i, t in enumerate(TAGS)}
PAD, UNK = 0, 1

CASE_PAD, CASE_NONE, CASE_LOWER, CASE_UPPER = 0, 1, 2, 3
N_CASE = 4
CLS_PAD, CLS_CYR, CLS_KAZ, CLS_LAT, CLS_DIGIT, CLS_SPACE, CLS_PUNCT, CLS_INVIS, CLS_OTHER = range(9)
N_CLS = 9
KAZ = frozenset("әғқңөұүһіӘҒҚҢӨҰҮҺІ")
INVISIBLE = frozenset("\u200b\u200c\u200d\u2060\ufeff\u00ad‎‏᠎")

IntArray = npt.NDArray[np.int64]


def norm_char(ch: str) -> str:
    """Ключ словаря: нижний регистр, любая цифра -> «0» (номер дома важен позицией, а не значением)."""
    if ch.isdigit():
        return "0"
    low = ch.lower()
    return low if len(low) == 1 else ch


def char_case(ch: str) -> int:
    if ch.isupper():
        return CASE_UPPER
    if ch.islower():
        return CASE_LOWER
    return CASE_NONE


def char_class(ch: str) -> int:
    if ch in INVISIBLE:
        return CLS_INVIS
    if ch in KAZ:
        return CLS_KAZ
    if ch.isdigit():
        return CLS_DIGIT
    if ch.isspace():
        return CLS_SPACE
    if ch.isalpha():
        if "Ѐ" <= ch <= "ӿ":
            return CLS_CYR
        if ch.isascii():
            return CLS_LAT
        return CLS_OTHER
    cat = unicodedata.category(ch)
    if cat.startswith("P") or cat.startswith("S"):
        return CLS_PUNCT
    if cat in ("Cf", "Mn"):
        return CLS_INVIS
    return CLS_OTHER


def encode(text: str, vocab: dict[str, int], max_len: int) -> tuple[IntArray, IntArray, IntArray]:
    """Признаки первых max_len символов строки."""
    t = text[:max_len]
    chars = np.fromiter((vocab.get(norm_char(c), UNK) for c in t), dtype=np.int64, count=len(t))
    case = np.fromiter((char_case(c) for c in t), dtype=np.int64, count=len(t))
    cls = np.fromiter((char_class(c) for c in t), dtype=np.int64, count=len(t))
    return chars, case, cls


def encode_batch(
    texts: Sequence[str], vocab: dict[str, int], max_len: int
) -> tuple[IntArray, IntArray, IntArray, IntArray]:
    """[B, T] с паддингом нулями справа + длины. Пустая строка получает длину 1 (один PAD), чтобы LSTM не падал."""
    enc = [encode(t, vocab, max_len) for t in texts]
    lengths = np.array([max(1, len(e[0])) for e in enc], dtype=np.int64)
    width = int(lengths.max()) if len(enc) else 1
    out = [np.zeros((len(enc), width), dtype=np.int64) for _ in range(3)]
    for b, e in enumerate(enc):
        for k in range(3):
            out[k][b, : len(e[k])] = e[k]
    return out[0], out[1], out[2], lengths


def bio(spans: Sequence[Sequence[object]], n: int) -> IntArray:
    """Спаны [(start, end, LABEL)] -> id тегов BIO для строки длины n (спаны за пределами обрезаются)."""
    tags = np.zeros(n, dtype=np.int64)
    for s, e, lab in spans:
        s, e = int(s), min(int(e), n)  # type: ignore[call-overload]
        if s >= e:
            continue
        tags[s] = TAG_ID[f"B-{lab}"]
        tags[s + 1 : e] = TAG_ID[f"I-{lab}"]
    return tags


def spans_of(tag_ids: Sequence[int] | IntArray) -> list[tuple[int, int, str]]:
    """Id тегов -> спаны. I без B открывает новую сущность (CRF такое запрещает, но декодер терпим)."""
    out: list[tuple[int, int, str]] = []
    start, cur = -1, ""
    for i, tid in enumerate(tag_ids):
        tag = TAGS[int(tid)]
        if tag == "O" or tag.startswith("B-") or tag[2:] != cur:
            if start >= 0:
                out.append((start, i, cur))
                start, cur = -1, ""
            if tag != "O":
                start, cur = i, tag[2:]
    if start >= 0:
        out.append((start, len(tag_ids), cur))
    return out


def allowed_transitions() -> tuple[npt.NDArray[np.bool_], npt.NDArray[np.bool_]]:
    """BIO: I-X только после B-X/I-X и не в начале строки. (переходы [from, to], допустимые старты)."""
    n = len(TAGS)
    trans = np.ones((n, n), dtype=bool)
    start = np.ones(n, dtype=bool)
    for j, t in enumerate(TAGS):
        if t.startswith("I-"):
            start[j] = False
            for i, f in enumerate(TAGS):
                trans[i, j] = f in (f"B-{t[2:]}", t)
    return trans, start
