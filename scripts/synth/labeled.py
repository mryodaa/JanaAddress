"""Строка с меткой у каждого символа: генератор мутирует строку (вставки, замены, регистр), метки едут вместе.

Метка класса без BIO (PROVINCE, CITY, ... или O) плюс флаг «начало сущности»: две соседние сущности одного
класса («Алматы Алматы» без разделителя) не сливаются. BIO строится из этого при обучении.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

OUTSIDE = "O"
LABELS = (
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


@dataclass
class LText:
    text: str = ""
    lab: list[str] = field(default_factory=list)
    beg: list[bool] = field(default_factory=list)

    @classmethod
    def of(cls, text: str, label: str = OUTSIDE) -> LText:
        assert label == OUTSIDE or label in LABELS, label
        return cls(text, [label] * len(text), [label != OUTSIDE and i == 0 for i in range(len(text))])

    @classmethod
    def cont(cls, text: str, label: str) -> LText:
        """Продолжение предыдущей сущности того же класса («5» + « корп 2» -> один спан HOUSE)."""
        assert label in LABELS, label
        return cls(text, [label] * len(text), [False] * len(text))

    def __len__(self) -> int:
        return len(self.text)

    def __str__(self) -> str:
        return self.text

    def __add__(self, other: LText | str) -> LText:
        o = LText.of(other) if isinstance(other, str) else other
        return LText(self.text + o.text, self.lab + o.lab, self.beg + o.beg)

    def __radd__(self, other: str) -> LText:
        return LText.of(other) + self

    @staticmethod
    def join(sep: str, parts: Iterable[LText | str]) -> LText:
        out = LText()
        for i, p in enumerate(parts):
            if i:
                out = out + sep
            out = out + p
        return out

    def _label_at(self, i: int) -> tuple[str, bool]:
        """Метка для символа, вставленного перед позицией i: внутри сущности её класс, на границе OUTSIDE."""
        if 0 < i < len(self) and self.lab[i - 1] == self.lab[i] and not self.beg[i]:
            return self.lab[i - 1], False
        return OUTSIDE, False

    def insert(self, i: int, ch: str) -> None:
        lab, beg = self._label_at(i)
        self.text = self.text[:i] + ch + self.text[i:]
        self.lab[i:i] = [lab] * len(ch)
        self.beg[i:i] = [beg] * len(ch)

    def set_char(self, i: int, ch: str) -> None:
        """Замена одного символа (NBSP вместо пробела): метка сохраняется."""
        assert len(ch) == 1
        self.text = self.text[:i] + ch + self.text[i + 1 :]

    def sub(self, pattern: str, repl: Callable[[re.Match[str]], str]) -> LText:
        """re.sub с метками: замена внутри одной сущности остаётся в ней, иначе получает OUTSIDE.
        repl вызывается по совпадениям в том же порядке, что и re.sub (важно для воспроизводимости RNG)."""
        text, lab, beg = [], [], []
        pos = 0
        for m in re.finditer(pattern, self.text):
            s, e = m.span()
            text.append(self.text[pos:s])
            lab += self.lab[pos:s]
            beg += self.beg[pos:s]
            r = repl(m)
            inner = set(self.lab[s:e])
            keep = len(inner) == 1 and OUTSIDE not in inner and s > 0 and e < len(self) and not any(self.beg[s:e])
            # пробел внутри «Айтеке би» остаётся частью названия, на границе сущностей это OUTSIDE
            label = self.lab[s] if keep else OUTSIDE
            text.append(r)
            lab += [label] * len(r)
            beg += [False] * len(r)
            pos = e
        text.append(self.text[pos:])
        lab += self.lab[pos:]
        beg += self.beg[pos:]
        return LText("".join(text), lab, beg)

    def strip(self) -> LText:
        s, e = 0, len(self)
        while s < e and self.text[s].isspace():
            s += 1
        while e > s and self.text[e - 1].isspace():
            e -= 1
        return LText(self.text[s:e], self.lab[s:e], self.beg[s:e])

    def _case(self, f: Callable[[str], str]) -> LText:
        # посимвольно: upper() может удлинить символ («ß» -> «SS»), тогда оставляем как есть
        chars = [f(c) if len(f(c)) == 1 else c for c in self.text]
        return LText("".join(chars), list(self.lab), list(self.beg))

    def upper(self) -> LText:
        return self._case(str.upper)

    def lower(self) -> LText:
        return self._case(str.lower)

    def spans(self) -> list[tuple[int, int, str]]:
        """[(start, end, LABEL)] по непрерывным участкам одной сущности."""
        out: list[tuple[int, int, str]] = []
        start = -1
        for i, lab in enumerate(self.lab):
            new = lab != OUTSIDE and (self.beg[i] or i == 0 or self.lab[i - 1] != lab)
            if start >= 0 and (lab == OUTSIDE or new):
                out.append((start, i, self.lab[start]))
                start = -1
            if new:
                start = i
        if start >= 0:
            out.append((start, len(self), self.lab[start]))
        return out


def fmt(template: str, value: str, label: str) -> LText:
    """«д. {}» + «12» -> «д. » (OUTSIDE) + «12» (label). Ровно одно «{}» в шаблоне."""
    pre, post = template.split("{}")
    return LText.of(pre) + LText.of(value, label) + LText.of(post)
