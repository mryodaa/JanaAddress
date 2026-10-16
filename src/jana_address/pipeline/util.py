"""Общие операции над токенами: сегменты, фразы, извлечение значения из ОРИГИНАЛЬНОЙ строки."""

from __future__ import annotations

import re

from ..reference.normalize import fold
from ..rules_loader import PhraseIndex, Rules
from .base import ParseState, Token

_EDGE = re.compile(r"^[\s.,;:\-–—_/\\|'\"«»()\[\]{}#№*+=!?]+|[\s.,;:\-–—_/\\|'\"«»()\[\]{}#№*+=!?]+$")
_INVIS = re.compile("[\u200b\u200c\u200d\u2060\ufeff\u00ad\u200e\u200f\u180e]")
_WS = re.compile(r"\s+")


def segments(tokens: list[Token]) -> list[list[int]]:
    """Индексы токенов (кроме разделителей), сгруппированные по сегментам между запятыми."""
    segs: list[list[int]] = [[]]
    for i, t in enumerate(tokens):
        if t.kind == "sep":
            if segs[-1]:
                segs.append([])
            continue
        segs[-1].append(i)
    return [s for s in segs if s]


def segment_of(tokens: list[Token]) -> list[int]:
    out: list[int] = []
    seg = 0
    for t in tokens:
        if t.kind == "sep":
            seg += 1
        out.append(seg)
    return out


def tidy_value(text: str) -> str:
    """Минимальная правка значения: невидимые символы, края, пробелы. Регистр/опечатки не трогаем."""
    text = _INVIS.sub("", text).replace("\u00a0", " ")
    text = _EDGE.sub("", text)
    return _WS.sub(" ", text).strip()


def value_from(state: ParseState, toks: list[Token]) -> tuple[str, tuple[int, int]] | None:
    toks = [t for t in toks if t.kind in ("word", "num")] or toks
    if not toks:
        return None
    start, end = min(t.start for t in toks), max(t.end for t in toks)
    s, e = state.orig_span(start, end)
    val = tidy_value(state.raw[s:e])
    return (val, (s, e)) if val else None


def house_value(state: ParseState, tok: Token) -> tuple[str, tuple[int, int]]:
    """Номер дома как есть, только без пробелов вокруг дроби: «1 / 2» -> «1/2»."""
    s, e = state.orig_span(tok.start, tok.end)
    v = tidy_value(state.raw[s:e])
    v = re.sub(r"\s*/\s*", "/", v)
    return v, (s, e)


def followed_by_dot(state: ParseState, i: int) -> bool:
    toks = state.tokens
    return i + 1 < len(toks) and toks[i + 1].text == "." and toks[i + 1].glued_left


def marker_ok(state: ParseState, rules: Rules, idx: list[int], k: int, n: int) -> bool:
    """Однобуквенные сокращения («у», «ш», «г»...) считаются маркером только с точкой после."""
    if n == 1:
        f = fold(state.tokens[idx[k]].text)
        if f in rules.needs_dot and not followed_by_dot(state, idx[k]):
            return False
    return True


def match_phrase(state: ParseState, index: PhraseIndex[object], idx: list[int], k: int) -> tuple[object, int] | None:
    """Совпадение фразы из словаря, начиная с токена idx[k] (только свободные слова подряд)."""
    folds: list[str] = []
    for j in idx[k:]:
        t = state.tokens[j]
        if t.kind != "word" or not t.free:
            break
        folds.append(fold(t.text))
        if len(folds) >= 4:
            break
    if not folds:
        return None
    return index.match(folds, 0)


def free_words(state: ParseState, seg: list[int]) -> list[int]:
    return [i for i in seg if state.tokens[i].free and state.tokens[i].kind in ("word", "num")]


def mark(state: ParseState, idx: list[int], label: str) -> None:
    for i in idx:
        state.tokens[i].used_by = label
    # точка сразу после помеченного сокращения тоже «съедена»
    for i in idx:
        if i + 1 < len(state.tokens) and state.tokens[i + 1].text == "." and state.tokens[i + 1].free:
            state.tokens[i + 1].used_by = label


def has_kazakh(text: str) -> bool:
    return any(ch in "әғқңөұүһіӘҒҚҢӨҰҮҺІ" for ch in text)


def is_cyrillic(text: str) -> bool:
    return bool(re.search(r"[а-яА-ЯёЁ]", text)) and not re.search(r"[A-Za-z]", text)
