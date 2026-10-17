"""Шаг 3. Токены с позициями. Слитное написание разделяется регуляркой («66квартал» -> 66 | квартал,
«Назарбаева8» -> Назарбаева | 8), дроби и литеры дома остаются одним номером (1/2, 12а, 12-а, 12 А).
"""

from __future__ import annotations

import re

from ..reference.normalize import norm
from ..rules_loader import get_rules
from .base import ParseState, StepTrace, Token

_L = r"[^\W\d_]"
_TOKEN = r"""
    (?P<num>\d+(?:-?{L}(?!{L}))?(?:{S}/{S}\d+(?:-?{L}(?!{L}))?)*)
  | (?P<abbr>{L}{{1,2}}/{L}{{1,2}}(?!{L}))
  | (?P<word>{L}+(?:['\-]{L}+)*)
  | (?P<sep>[,;|])
  | (?P<punct>\S)
"""
TOKEN_RE = re.compile(_TOKEN.format(L=_L, S=r"\s?"), re.VERBOSE | re.UNICODE)
# строка с « / » как разделителем («Алматы / ул. Абая 19 / 119 кв»): дробь только слитная
TOKEN_RE_SLASH_SEP = re.compile(_TOKEN.format(L=_L, S=""), re.VERBOSE | re.UNICODE)
_SLASH_SEP = re.compile(r"(?:[^\W\d]|[.,])\s+/|/\s+[^\W\d]")

# служебные числа: в адрес не входят и не должны доставаться маркерам («кв 050000», «+7 701 ...»)
_PHONE = re.compile(
    r"(?<!\d)(?:\+\s?7|8|7)[\s\-()]*7\d{2}[\s\-()]*\d{3}[\s\-]*\d{2}[\s\-]*\d{1,2}(?!\d)|(?<!\d)\d{9,}(?!\d)"
)
_POSTCODE = re.compile(r"(?<![\d/\-])\d{6}(?![\d/\-])")
# время: с двоеточием всегда; с точкой только при явном контексте, иначе «Абая 10.30» (дом через точку)
# потерял бы номер. Контекст: «ч», «час», «до», дефис после или предлог времени перед. Группа t: само время
_TIME = re.compile(
    r"(?<!\d)(?P<t>\d{1,2}:\d{2})(?!\d)"
    r"|(?<!\d)(?P<t2>\d{1,2}\.\d{2})(?![\d.])(?=\s*(?:ч|час|до|-))"
    r"|(?i:(?<![^\W\d_])(?:до|после|с|в|к)\s+)(?P<t3>\d{1,2}\.\d{2})(?![\d.])"
)
# «1-я Лодочная», «2-й переулок»: порядковое числительное это часть названия, а не номер
_ORDINAL = re.compile(r"^\d{1,3}-?(й|я|ая|ый|ий|ой)$")
# литера через пробел: «12 А», «5 б», «135 Л». Без однобуквенных маркеров и союзов
# (д — дом, к — корпус, п/с/т/у/ш — с точкой это сокращения, и — «12 и 14»)
HOUSE_LETTERS = frozenset("абвгежзлмнорфхцчщэюяabc")
_QUOTES = frozenset({'"', "«", "»", "“", "”", "„", "'"})


def tokenize(text: str) -> list[Token]:
    toks: list[Token] = []
    slash_sep = bool(_SLASH_SEP.search(text))
    for m in (TOKEN_RE_SLASH_SEP if slash_sep else TOKEN_RE).finditer(text):
        kind = m.lastgroup or "punct"
        if kind == "abbr":
            kind = "word"
        elif kind == "punct" and slash_sep and m.group() == "/":
            kind = "sep"
        elif kind == "num" and _ORDINAL.match(m.group()):
            kind = "word"
        s, e = m.span()
        t = Token(text=m.group(), norm=norm(m.group()), start=s, end=e, kind=kind)
        t.glued_left = bool(toks) and toks[-1].end == s
        toks.append(t)
    return _merge_spaced_letters(text, _split_building_glue(_split_letter_marker(text, toks)))


# «11к2», «5с1», «1А/1с9»: дом + корпус/строение слитно; регулярка отдала «к» номеру как литеру
_BUILDING_GLUE = re.compile(r"^(\d(?:.*\d)?)([кКсС])$")


def _split_building_glue(toks: list[Token]) -> list[Token]:
    out: list[Token] = []
    for i, t in enumerate(toks):
        nxt = toks[i + 1] if i + 1 < len(toks) else None
        m = _BUILDING_GLUE.match(t.text) if t.kind == "num" else None
        if m and nxt is not None and nxt.kind == "num" and nxt.glued_left:
            n = len(m.group(1))
            out.append(Token(text=m.group(1), norm=norm(m.group(1)), start=t.start, end=t.start + n, kind="num",
                             glued_left=t.glued_left))  # fmt: skip
            out.append(Token(text=m.group(2), norm=norm(m.group(2)), start=t.start + n, end=t.end, kind="word",
                             glued_left=True))  # fmt: skip
            continue
        out.append(t)
    return out


def _split_letter_marker(text: str, toks: list[Token]) -> list[Token]:
    """«47Бдом», «15адом»: литера дома слиплась с маркером, регулярка отдала её слову. Возвращаем литеру номеру."""
    out: list[Token] = []
    details = get_rules().details
    for t in toks:
        prev = out[-1] if out else None
        if (
            prev is not None
            and t.kind == "word"
            and t.glued_left
            and prev.kind == "num"
            and prev.text[-1].isdigit()
            and len(t.text) > 2
            and t.text[0].isalpha()
            and details.get(t.text[1:]) is not None
            and details.get(t.text) is None
        ):
            num = Token(
                text=text[prev.start : t.start + 1],
                norm=norm(text[prev.start : t.start + 1]),
                start=prev.start,
                end=t.start + 1,
                kind="num",
                glued_left=prev.glued_left,
            )
            word = Token(text=t.text[1:], norm=norm(t.text[1:]), start=t.start + 1, end=t.end, kind="word")
            word.glued_left = True
            out[-1] = num
            out.append(word)
            continue
        out.append(t)
    return out


def _merge_spaced_letters(text: str, toks: list[Token]) -> list[Token]:
    out: list[Token] = []
    i = 0
    while i < len(toks):
        t = toks[i]
        if (
            t.kind == "num"
            and not t.text[-1].isalpha()
            and i + 3 < len(toks)
            and toks[i + 1].text in _QUOTES
            and toks[i + 2].kind == "word"
            and len(toks[i + 2].text) == 1
            and toks[i + 2].text.isalpha()
            and toks[i + 3].text in _QUOTES
        ):
            # литера в кавычках: «85 "А"», «12 «а»» (реестры, справки)
            end = toks[i + 3].end
            merged = Token(
                text=text[t.start : end],
                norm=norm(text[t.start : end]),
                start=t.start,
                end=end,
                kind="num",
                glued_left=t.glued_left,
            )
            merged.tags.add("spaced_letter")
            out.append(merged)
            i += 4
            continue
        if (
            t.kind == "num"
            and not t.text[-1].isalpha()
            and i + 1 < len(toks)
            and toks[i + 1].kind == "word"
            and len(toks[i + 1].text) == 1
            and toks[i + 1].text.lower() in HOUSE_LETTERS
            and not toks[i + 1].glued_left
            and _letter_context_ok(toks, i + 2)
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


def _letter_context_ok(toks: list[Token], j: int) -> bool:
    """«12 а.» / «12 а Абая»: буква с точкой или перед словом это не литера.
    Исключение: маркер детали после буквы («12 А кв 4», «5 б подъезд 2») однозначно делает её литерой."""
    if j >= len(toks):
        return True
    nxt = toks[j]
    if nxt.kind == "word":
        # «12 А кв 4», «73 Е корп. 5»: маркер детали или корпуса после буквы делает её литерой
        rules = get_rules()
        return rules.details.get(nxt.text) is not None or nxt.text in rules.building_part
    return nxt.text != "."


def mark_service_numbers(text: str, toks: list[Token]) -> list[str]:
    """Телефоны, почтовые индексы, время («до 18:00»): токены помечаются noise:*, дальше их никто не берёт."""
    notes: list[str] = []
    for label, rx in (("phone", _PHONE), ("postcode", _POSTCODE), ("time", _TIME)):
        for m in rx.finditer(text):
            # у времени помечаем только само число, без предлога перед ним (предлог снимается ниже)
            g = next((k for k in ("t", "t2", "t3") if k in rx.groupindex and m.group(k)), None)
            ms, me = m.span(g) if g else m.span()
            hit = [t for t in toks if t.free and t.start < me and t.end > ms]
            # индекс и время только целыми токенами: «12/050000» или «д.12.30» не трогаем
            if label != "phone" and not all(ms <= t.start and t.end <= me for t in hit):
                continue
            if not hit or any(t.kind == "word" for t in hit):
                continue
            for t in hit:
                t.used_by = f"noise:{label}"
            notes.append(f"{label} {m.group()!r}")
    # «+» перед телефоном и предлог времени («до 18:00», «после 14.00») тоже не адрес
    for i, t in enumerate(toks):
        nxt = toks[i + 1] if i + 1 < len(toks) else None
        if (
            t.free
            and nxt is not None
            and nxt.used_by in ("noise:phone", "noise:time")
            and (t.text == "+" or (nxt.used_by == "noise:time" and t.norm in ("до", "после", "с", "в", "к")))
        ):
            t.used_by = nxt.used_by
    return notes


class Tokenize:
    name = "tokenize"

    def __call__(self, state: ParseState) -> ParseState:
        state.tokens = tokenize(state.text)
        tr = StepTrace(step=self.name)
        tr.notes.append(" | ".join(f"{t.text}:{t.kind[0]}" for t in state.tokens))
        tr.notes += mark_service_numbers(state.text, state.tokens)
        state.trace.append(tr)
        return state
