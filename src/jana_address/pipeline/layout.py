"""Шаг layout: строка, набранная в английской раскладке вместо русской («Fkvfns? ek/ f,fz 10» = «Алматы, ул. Абая 10»).

Перекодировка посимвольная (клавиша QWERTY -> ЙЦУКЕН), длина строки та же, поэтому все спаны и смещения остаются
верными. Берётся, только если в строке нет кириллицы и после перекодировки узнаётся хотя бы два слова (маркеры
или топонимы справочника), а до неё заметно меньше: латинский адрес «Almaty, ul. Abaya 10» узнаётся и так (транслит)
и не трогается. Это единственное место, где значения режутся не из raw как есть, а из перекодированной строки
той же длины (docs/QUESTIONS.md, Q19): иначе street_name был бы «f,fz». id и raw_address в ответе прежние.
"""

from __future__ import annotations

import re

from ..reference.normalize import fold
from ..reference.store import Store, get_store
from ..rules_loader import Rules, all_marker_words, get_rules
from .base import ParseState, StepTrace

_EN = "qwertyuiop[]asdfghjkl;'zxcvbnm,./`QWERTYUIOP{}ASDFGHJKL:\"ZXCVBNM<>?~@#$^&"
_RU = 'йцукенгшщзхъфывапролджэячсмитьбю.ёЙЦУКЕНГШЩЗХЪФЫВАПРОЛДЖЭЯЧСМИТЬБЮ,Ё"№;:?'
TABLE = str.maketrans(_EN, _RU)
_WORD = re.compile(r"[^\W\d_]{2,}")
ETYPES = ("province", "district", "city", "living_area")  # улицы по индексу ключей: lookup по ним дорог


def convert(raw: str) -> str:
    return raw.translate(TABLE)


class Layout:
    name = "layout"

    def __init__(self, store: Store | None = None, rules: Rules | None = None) -> None:
        self.store = store or get_store()
        self.rules = rules or get_rules()
        self.markers = all_marker_words()

    def known(self, word: str) -> bool:
        f = fold(word)
        return f in self.markers or bool(self.store.lookup(word, ETYPES)) or f in self.store.street_keys_global

    def fix(self, raw: str) -> str | None:
        letters = [c for c in raw if c.isalpha()]
        if len(letters) < 4 or not all(c.isascii() for c in letters):
            return None
        conv = convert(raw)
        before = sum(self.known(w) for w in _WORD.findall(raw))
        after = sum(self.known(w) for w in _WORD.findall(conv))
        return conv if after >= 2 and after > 2 * before else None

    def __call__(self, state: ParseState) -> ParseState:
        tr = StepTrace(step=self.name)
        conv = self.fix(state.raw)
        if conv is not None:
            tr.notes.append(f"английская раскладка: {state.raw!r} -> {conv!r}")
            state.raw = conv
            state.flags.add("layout_fixed")
            # разметку теггера пересчитать уже по перекодированной строке
            state.model, state.model_tried = None, False
        state.trace.append(tr)
        return state
