"""Шаг 1. Очищенная копия строки для разбора + карта смещений к оригиналу.

Оригинал (state.raw) не меняется никогда. state.offsets[i] = индекс в raw символа state.text[i].
"""

from __future__ import annotations

import unicodedata

from .base import ParseState, StepTrace

# невидимые и служебные символы: удаляются
INVISIBLE = frozenset(
    "\u200b\u200c\u200d\u2060\ufeff\u00ad\u200e\u200f\u180e\u034f"
    "\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069\ufe0f"
)
# пробелоподобные: превращаются в обычный пробел
SPACES = frozenset(
    "\u00a0\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u202f\u205f\u3000\t\x0b\x0c"
)
# переводы строк считаем разделителем сегментов
NEWLINES = frozenset("\n\r\u2028\u2029\x85")
TRANSLATE = {
    **{c: "-" for c in "‐‑‒–—―−"},
    **{c: '"' for c in "«»“”„‟"},
    **{c: "'" for c in "‘’‚‛ʼ`´"},
    "\\": "/",
    "⁄": "/",
}


def clean_text(raw: str) -> tuple[str, list[int]]:
    chars: list[str] = []
    offs: list[int] = []
    for i, ch in enumerate(raw):
        if ch in INVISIBLE:
            continue
        if ch in NEWLINES:
            ch = ","
        elif ch in SPACES:
            ch = " "
        elif unicodedata.category(ch) in ("Cc", "Cf", "Cs", "Co"):
            continue
        ch = TRANSLATE.get(ch, ch)
        if unicodedata.combining(ch) and chars:
            composed = unicodedata.normalize("NFC", chars[-1] + ch)
            if len(composed) == 1:
                chars[-1] = composed
            continue  # одиночные комбинирующие знаки (ударения и т.п.) для разбора не нужны
        nfc = unicodedata.normalize("NFC", ch)
        for c in nfc:
            chars.append(c)
            offs.append(i)

    # схлопнуть пробелы, убрать пробел перед .,; и по краям
    out_c: list[str] = []
    out_o: list[int] = []
    n = len(chars)
    for j, c in enumerate(chars):
        if c == " ":
            if not out_c or out_c[-1] == " ":
                continue
            nxt = chars[j + 1] if j + 1 < n else ""
            if nxt in ("", " ", ",", ";", "."):
                continue
        out_c.append(c)
        out_o.append(offs[j])
    while out_c and out_c[-1] == " ":
        out_c.pop()
        out_o.pop()
    out_o.append(len(raw))
    return "".join(out_c), out_o


class Clean:
    name = "clean"

    def __call__(self, state: ParseState) -> ParseState:
        state.text, state.offsets = clean_text(state.raw)
        tr = StepTrace(step=self.name)
        if state.text != state.raw:
            tr.notes.append(f"clean: {state.text!r}")
        removed = len(state.raw) - len(state.text)
        if removed:
            tr.changes["removed_chars"] = removed
        state.trace.append(tr)
        return state
