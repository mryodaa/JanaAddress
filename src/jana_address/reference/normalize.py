"""Нормализация для СРАВНЕНИЯ (никогда для вывода).

norm()  нижний регистр, ё->е, латинские двойники кириллицы в кириллических словах, без точек по краям.
fold()  norm + казахские буквы -> ближайшие русские, ъ->ь, дефисы -> пробел. Для словарей и справочника.
translit_lat() латиница (в т.ч. новый казахский алфавит) -> кириллица, чтобы «almaty» нашло «алматы».
"""

from __future__ import annotations

import re
from functools import lru_cache

KAZ_FOLD = str.maketrans(
    {
        "ә": "а",
        "ғ": "г",
        "қ": "к",
        "ң": "н",
        "ө": "о",
        "ұ": "у",
        "ү": "у",
        "һ": "х",
        "і": "и",
        "ё": "е",
        "ъ": "ь",
    }
)
# латинские буквы, которые выглядят как кириллические (подмена при наборе)
LAT_HOMOGLYPH = str.maketrans(
    {
        "a": "а",
        "c": "с",
        "e": "е",
        "o": "о",
        "p": "р",
        "x": "х",
        "y": "у",
        "k": "к",
        "m": "м",
        "t": "т",
        "h": "н",
        "b": "в",
        "i": "і",
    }
)
_CYR = re.compile(r"[а-яёәғқңөұүһі]")
_LAT = re.compile(r"[a-z]")
_EDGE = re.compile(r"^[\s.\-–—,;:'\"«»()]+|[\s.\-–—,;:'\"«»()]+$")
_WS = re.compile(r"\s+")

LAT2CYR_MULTI = [
    ("shch", "щ"),
    ("sch", "щ"),
    ("yo", "ё"),
    ("yu", "ю"),
    ("ya", "я"),
    ("ye", "е"),
    ("zh", "ж"),
    ("kh", "х"),
    ("ch", "ч"),
    ("sh", "ш"),
    ("ts", "ц"),
    ("ou", "у"),
]
LAT2CYR_SINGLE = str.maketrans(
    {
        "a": "а",
        "b": "б",
        "c": "к",
        "d": "д",
        "e": "е",
        "f": "ф",
        "g": "г",
        "h": "х",
        "i": "и",
        "j": "ж",
        "k": "к",
        "l": "л",
        "m": "м",
        "n": "н",
        "o": "о",
        "p": "п",
        "q": "к",
        "r": "р",
        "s": "с",
        "t": "т",
        "u": "у",
        "v": "в",
        "w": "у",
        "x": "кс",
        "y": "ы",
        "z": "з",
        # казахская латиница 2021
        "ä": "а",
        "ğ": "г",
        "ı": "ы",
        "ñ": "н",
        "ö": "о",
        "ş": "ш",
        "ç": "ч",
        "ü": "у",
        "ū": "у",
        "'": "",
        "’": "",
    }
)


@lru_cache(maxsize=65536)
def norm(s: str) -> str:
    s = s.lower().replace("ё", "е")
    if _CYR.search(s) and _LAT.search(s):
        s = s.translate(LAT_HOMOGLYPH)
    s = _EDGE.sub("", s)
    return _WS.sub(" ", s)


@lru_cache(maxsize=65536)
def fold(s: str) -> str:
    s = norm(s).translate(KAZ_FOLD)
    s = s.replace("-", " ").replace("‐", " ").replace("–", " ")
    return _WS.sub(" ", s).strip()


@lru_cache(maxsize=65536)
def translit_lat(s: str) -> str:
    s = s.lower()
    for a, b in LAT2CYR_MULTI:
        s = s.replace(a, b)
    return s.translate(LAT2CYR_SINGLE)


def is_latin(s: str) -> bool:
    return bool(_LAT.search(s.lower())) and not _CYR.search(s.lower())


def keys(s: str) -> list[str]:
    """Все ключи, под которыми строку ищем в словарях: fold и, для латиницы, транслит."""
    k = [fold(s)]
    if is_latin(s):
        t = fold(translit_lat(s))
        if t not in k:
            k.append(t)
    return k
