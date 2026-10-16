"""Шаг 2. Двуязычные склейки «рус/каз»: «город Актобе/Ақтөбе қаласы».

Слэш между словами означает склейку: казахская половина помечается kz_dup и дальше не разбирается.
Слэш между цифрами это дробь дома, его токенизатор уже держит внутри числа («55/6»).
Шаг работает по токенам, поэтому стоит после tokenize (см. docs/ARCHITECTURE.md).
"""

from __future__ import annotations

from ..reference.normalize import is_latin
from .base import ParseState, StepTrace, Token

KAZ_LETTERS = frozenset("әғқңөұүһі")
KZ_MARKERS = frozenset(
    {
        "қаласы",
        "облысы",
        "ауданы",
        "ауылы",
        "кенті",
        "көшесі",
        "даңғылы",
        "шағын",
        "ықшам",
        "ауылдық",
        "округі",
        "кешені",
        "тұйығы",
        "алаңы",
        "үй",
        "пәтер",
        "қабат",
        "кіреберіс",
        "тұрғын",
        "алабы",
        "жолы",
    }
)


def kz_score(toks: list[Token]) -> int:
    score = 0
    for t in toks:
        low = t.text.lower()
        score += sum(ch in KAZ_LETTERS for ch in low)
        if low in KZ_MARKERS:
            score += 3
    return score


def _collect(tokens: list[Token], i: int, step: int) -> list[Token]:
    out: list[Token] = []
    j = i
    while 0 <= j < len(tokens):
        t = tokens[j]
        if t.kind == "word" and t.free:
            out.append(t)
        elif t.kind == "punct" and t.text in ".-":
            pass
        else:
            break
        j += step
    return out if step > 0 else out[::-1]


def _cut_right(toks: list[Token]) -> list[Token]:
    """Справа отбрасываем до первого казахского маркера включительно («Алматы қаласы Мкр Аксай»)."""
    for k, t in enumerate(toks):
        if t.text.lower() in KZ_MARKERS:
            return toks[: k + 1]
    return toks


class SplitBilingual:
    name = "split_bilingual"

    def __call__(self, state: ParseState) -> ParseState:
        tr = StepTrace(step=self.name)
        toks = state.tokens
        for i, t in enumerate(toks):
            if t.kind != "punct" or t.text != "/" or t.used_by:
                continue
            left = _collect(toks, i - 1, -1)
            right = _collect(toks, i + 1, +1)
            if not left or not right:
                continue
            sl, sr = kz_score(left), kz_score(right)
            if sr > sl:
                drop, keep = _cut_right(right), left
            elif sl > sr:
                drop, keep = left, right
            elif is_latin(" ".join(x.text for x in right)) and not is_latin(" ".join(x.text for x in left)):
                drop, keep = right, left
            elif is_latin(" ".join(x.text for x in left)) and not is_latin(" ".join(x.text for x in right)):
                drop, keep = left, right
            else:
                drop, keep = _cut_right(right), left
                state.flags.add("bilingual_unresolved")
            # отбрасываемая половина не длиннее оставленной + 1 слово (ближайшие к слэшу)
            limit = len(keep) + 1
            drop = drop[:limit] if drop and drop[0].start > t.start else drop[-limit:]
            for d in drop:
                d.used_by = "kz_dup"
            t.used_by = "bilingual"
            tr.notes.append(
                f"оставлено {' '.join(x.text for x in keep)!r}, отброшено {' '.join(x.text for x in drop)!r}"
            )
        state.trace.append(tr)
        return state
