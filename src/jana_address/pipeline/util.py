"""Общие операции над токенами: сегменты, фразы, извлечение значения из ОРИГИНАЛЬНОЙ строки."""

from __future__ import annotations

import re
import unicodedata

from ..reference.normalize import fold
from ..rules_loader import PhraseIndex, Rules
from .base import ParseState, Token
from .clean import INVISIBLE

_EDGE = re.compile(r"^[\s.,;:\-–—_/\\|'\"«»()\[\]{}#№*+=!?]+|[\s.,;:\-–—_/\\|'\"«»()\[\]{}#№*+=!?]+$")
_DROP_CATS = frozenset({"Cc", "Cf", "Cs", "Co"})
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


def strip_invisible(text: str) -> str:
    """Без невидимых и служебных символов: тот же набор, что выбрасывает clean (bidi, Cf, мусорные Cc), иначе
    они протекали бы в значение, вырезанное из оригинала. Пробельные Cc (таб, перевод строки) оставляем _WS."""
    return "".join(c for c in text if c not in INVISIBLE and (unicodedata.category(c) not in _DROP_CATS or c.isspace()))


def tidy_value(text: str) -> str:
    """Минимальная правка значения: невидимые символы, края, пробелы. Регистр/опечатки не трогаем."""
    text = strip_invisible(text).replace("\u00a0", " ")
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


def house_text(text: str) -> str:
    """Номер дома как есть, только без пробелов вокруг дроби: «1 / 2» -> «1/2». Кавычки вокруг литеры («85 "А"»)
    убираются: жюри пунктуацию не сравнивает, а обрезанная по краю кавычка («85 "А») выглядит ошибкой."""
    return re.sub(r"\s*/\s*", "/", tidy_value(_HOUSE_QUOTES.sub("", text)))


_HOUSE_QUOTES = re.compile(r'["«»“”„]+(?=\s*[^\W\d_])|(?<=[^\W\d_])["«»“”„]+')  # только вокруг литеры


def house_value(state: ParseState, tok: Token) -> tuple[str, tuple[int, int]]:
    s, e = state.orig_span(tok.start, tok.end)
    return house_text(state.raw[s:e]), (s, e)


_EDGE_CHARS = frozenset(" \t\n\r.,;:-–—_/\\|'\"«»()[]{}#№*+=!?\u00a0\u200b\u200c\u200d\u2060\ufeff\u00ad")


def trim_span(raw: str, s: int, e: int) -> tuple[int, int]:
    """Спан без краевых пробелов, пунктуации и невидимых символов: так сравниваются спаны правил и модели."""
    while s < e and raw[s] in _EDGE_CHARS:
        s += 1
    while e > s and raw[e - 1] in _EDGE_CHARS:
        e -= 1
    return s, e


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
    pos: list[int] = []  # позиция каждого слова в idx: точка внутри сокращения («ш.а.», «ж.м.») пропускается
    for p in range(k, len(idx)):
        t = state.tokens[idx[p]]
        if t.kind == "punct" and t.text == "." and folds and len(folds[-1]) <= 2 and t.free:
            continue
        if t.kind != "word" or not t.free:
            break
        folds.append(fold(t.text))
        pos.append(p)
        if len(folds) >= 4:
            break
    if not folds:
        return None
    m = index.match(folds, 0)
    if m is None:
        return None
    return m[0], pos[m[1] - 1] - k + 1


def free_words(state: ParseState, seg: list[int]) -> list[int]:
    return [i for i in seg if state.tokens[i].free and state.tokens[i].kind in ("word", "num")]


def mark(state: ParseState, idx: list[int], label: str) -> None:
    for i in idx:
        state.tokens[i].used_by = label
    # точка сразу после помеченного сокращения тоже «съедена»
    for i in idx:
        if i + 1 < len(state.tokens) and state.tokens[i + 1].text == "." and state.tokens[i + 1].free:
            state.tokens[i + 1].used_by = label


# служебное слово пункта/района, попавшее в спан через алиас справочника («АЛМАТЫ - Г», «Алматы г», «Іле ауданы»)
_ADMIN_EDGE = re.compile(
    r"^(?:г|гор|город|с|пос|п|село|посёлок|поселок|аул|ауыл|р-н|район)\.?\s*[-–]?\s+"
    r"|(?:\s*[-–]\s*|\s+)(?:г|гор|город|қ|қаласы|каласы|ауылы|ауыл|кенті|кент|р-н|район|ауданы|ауд|г\.а|қ\.ә)\.?$",
    re.I,
)


def as_written(written: str | None, canonical: str) -> str:
    """Q22: город и район как в строке, без перевода и нормализации (казахская форма, латиница, регистр, опечатки
    остаются), только без служебного слова. Справочник нужен для привязки и для полей, которых в строке нет."""
    w = _ADMIN_EDGE.sub("", (written or "").strip()).strip()
    return w or canonical


def has_kazakh(text: str) -> bool:
    return any(ch in "әғқңөұүһіӘҒҚҢӨҰҮҺІ" for ch in text)


def is_cyrillic(text: str) -> bool:
    return bool(re.search(r"[а-яА-ЯёЁ]", text)) and not re.search(r"[A-Za-z]", text)
