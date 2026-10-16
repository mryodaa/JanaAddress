"""Шаг 3. Токены с позициями. Слитное написание разделяется регуляркой («66квартал» -> 66 | квартал,
«Назарбаева8» -> Назарбаева | 8), дроби и литеры дома остаются одним номером (1/2, 12а, 12-а, 12 А).
"""

from __future__ import annotations

import re

from ..reference.normalize import norm
from .base import ParseState, StepTrace, Token

_L = r"[^\W\d_]"
TOKEN_RE = re.compile(
    rf"""
    (?P<num>\d+(?:-?{_L}(?!{_L}))?(?:\s?/\s?\d+(?:-?{_L}(?!{_L}))?)*)
  | (?P<abbr>{_L}{{1,2}}/{_L}{{1,2}}(?!{_L}))
  | (?P<word>{_L}+(?:['\-]{_L}+)*)
  | (?P<sep>[,;|])
  | (?P<punct>\S)
    """,
    re.VERBOSE | re.UNICODE,
)
# литера через пробел: «12 А», «5 б»
HOUSE_LETTERS = frozenset("абвгabc")


def tokenize(text: str) -> list[Token]:
    toks: list[Token] = []
    for m in TOKEN_RE.finditer(text):
        kind = m.lastgroup or "punct"
        if kind == "abbr":
            kind = "word"
        s, e = m.span()
        t = Token(text=m.group(), norm=norm(m.group()), start=s, end=e, kind=kind)
        t.glued_left = bool(toks) and toks[-1].end == s
        toks.append(t)
    return _merge_spaced_letters(text, toks)


def _merge_spaced_letters(text: str, toks: list[Token]) -> list[Token]:
    out: list[Token] = []
    i = 0
    while i < len(toks):
        t = toks[i]
        if (
            t.kind == "num"
            and not t.text[-1].isalpha()
            and i + 1 < len(toks)
            and toks[i + 1].kind == "word"
            and len(toks[i + 1].text) == 1
            and toks[i + 1].text.lower() in HOUSE_LETTERS
            and not toks[i + 1].glued_left
            # «12 а.» / «12 а Абая»: буква с точкой или перед словом это не литера
            and (i + 2 >= len(toks) or (toks[i + 2].kind != "word" and toks[i + 2].text != "."))
        ):
            nxt = toks[i + 1]
            merged = Token(
                text=text[t.start : nxt.end],
                norm=norm(text[t.start : nxt.end]),
                start=t.start,
                end=nxt.end,
                kind="num",
                glued_left=t.glued_left,
            )
            merged.tags.add("spaced_letter")
            out.append(merged)
            i += 2
            continue
        out.append(t)
        i += 1
    return out


class Tokenize:
    name = "tokenize"

    def __call__(self, state: ParseState) -> ParseState:
        state.tokens = tokenize(state.text)
        tr = StepTrace(step=self.name)
        tr.notes.append(" | ".join(f"{t.text}:{t.kind[0]}" for t in state.tokens))
        state.trace.append(tr)
        return state
