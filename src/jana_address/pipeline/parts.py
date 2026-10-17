"""Шаг parts: то, что встречается в адресе, но не является полем ответа, забирается до разбора полей.

* Организация: «ТОО «Альфа Трейд»», «ИП Касымов», «АО Казахтелеком», «ЖШС Береке». Форма + название (в кавычках
  или до трёх слов с заглавной до разделителя) -> noise:org. Иначе название попадает в улицу или ориентир.
* Корпус / строение / блок / литер с номером: «корп 2», «к.2», «11к2», «стр. 1», «блок С». Забирается здесь, чтобы
  номер корпуса не стал квартирой, а «корп» частью названия улицы; в house его добавляет шаг building (ниже), когда
  дом уже определён (Q10: корпус входит в house как написано).
Словари в rules/markers.yaml (org_forms, org_forms_upper, building_part).
"""

from __future__ import annotations

import unicodedata

from ..reference.normalize import fold
from ..rules_loader import Rules, get_rules
from .base import SOURCE_STRING, ParseState, StepTrace, Token
from .util import house_text

OPEN_QUOTES = {"«": "»", '"': '"', "“": "”", "„": "“", "'": "'"}


class Parts:
    name = "parts"

    def __init__(self, rules: Rules | None = None) -> None:
        self.rules = rules or get_rules()

    def __call__(self, state: ParseState) -> ParseState:
        tr = StepTrace(step=self.name)
        caps = state.text.isupper()
        self._orgs(state, tr, caps)
        self._building(state, tr)
        state.trace.append(tr)
        return state

    # ---------- организации ----------
    def _is_org(self, t: Token, caps: bool) -> bool:
        if t.kind != "word" or not t.free:
            return False
        f = fold(t.text)
        if f in self.rules.org_forms:
            return True
        # «АО», «АҚ» только заглавными и не в строке капсом («УЛ. АҚ ЖОЛ» это улица)
        return f in self.rules.org_forms_upper and t.text.isupper() and not caps

    def _stop(self, t: Token) -> bool:
        r = self.rules
        x = t.text
        return (
            x in r.street_types
            or x in r.details
            or x in r.city_prefix
            or x in r.settlement_prefix
            or x in r.province_markers
            or x in r.district_markers
            or x in r.lm_prepositions
            or x in r.building_part
        )

    def _orgs(self, state: ParseState, tr: StepTrace, caps: bool) -> None:
        toks = state.tokens
        # предыдущий не-punct токен для каждой позиции, одним проходом: поиск назад на каждом шаге квадратичен
        prev_np: list[Token | None] = []
        last: Token | None = None
        for t in toks:
            prev_np.append(last)
            if t.kind != "punct":
                last = t
        i = 0
        while i < len(toks):
            prev = prev_np[i]
            # «ул. АК ЖОЛ», «пр. АО ...»: после маркера улицы это название, а не организация
            after_street = prev is not None and prev.kind == "word" and prev.text in self.rules.street_types
            if after_street or not self._is_org(toks[i], caps):
                i += 1
                continue
            taken = [i]
            j = i + 1
            while j < len(toks) and toks[j].text == "." and toks[j].free:
                taken.append(j)
                j += 1
            if j < len(toks) and toks[j].text in OPEN_QUOTES:
                close = OPEN_QUOTES[toks[j].text]
                k = j + 1
                while k < len(toks) and toks[k].text != close and toks[k].kind != "sep" and k - j <= 8:
                    k += 1
                if k < len(toks) and toks[k].text == close:
                    taken += list(range(j, k + 1))
                    j = k + 1
            else:
                words = 0
                while (
                    j < len(toks)
                    and words < 3
                    and toks[j].free
                    and toks[j].kind == "word"
                    and (toks[j].text[:1].isupper() or caps)
                    and not self._stop(toks[j])
                ):
                    taken.append(j)
                    words += 1
                    j += 1
            for k in taken:
                toks[k].used_by = "noise:org"
            s, e = state.orig_span(toks[taken[0]].start, toks[taken[-1]].end)
            tr.notes.append(f"организация {state.raw[s:e]!r}: не адрес")
            i = j

    # ---------- корпус / строение ----------
    def _building(self, state: ParseState, tr: StepTrace) -> None:
        toks = state.tokens
        for i, t in enumerate(toks):
            if t.kind != "word" or not t.free or t.text not in self.rules.building_part:
                continue
            # латинское «str.» это улица (street), хотя транслитом совпадает с «стр.» (строение)
            if t.text.isascii() and t.text in self.rules.street_types:
                continue
            j = i + 1
            dot = j < len(toks) and toks[j].text == "."
            if dot:
                j += 1
            if j >= len(toks) or not toks[j].free:
                continue
            nxt = toks[j]
            value_ok = nxt.kind == "num" or (nxt.kind == "word" and len(nxt.text) == 1 and nxt.text.isalpha())
            # однобуквенные «к», «с» только «к.2», «к2», «11к2», «16с5»: иначе это может быть что угодно («с» село)
            if len(t.text) == 1 and not (dot or nxt.glued_left or t.glued_left):
                continue
            # «блок С», «корпус Б»: буква только после полного слова, не после «к»/«бл»
            if nxt.kind == "word" and len(t.text) < 4:
                continue
            if not value_ok:
                continue
            for k in range(i, j + 1):
                toks[k].used_by = "building"
            state.flags.add("building_part_ignored")
            s, e = state.orig_span(t.start, nxt.end)
            tr.notes.append(f"корпус/строение {state.raw[s:e]!r}: не входит в дом (Q10)")


def _only_separators(text: str) -> bool:
    return all(ch.isspace() or ch in ",.;:-" or unicodedata.category(ch) == "Cf" for ch in text)


# строение без номера дома перед ним = номер здания («строение 25» -> «25»), корпус/блок остаются как написано (Q10)
STRUCTURE_WORDS = frozenset({"строение", "стр"})


class AttachBuilding:
    """Шаг building: корпус/строение, забранные шагом parts, входят в house как написано (Q10): «5 корп 2», «11к2»,
    «30/1 стр. 2». Только если корпус идёт сразу за номером дома (между ними пробелы, запятая, точка или ничего);
    значение это срез исходной строки от начала дома до конца корпуса. Дома в строке нет («ЖК Хайвил, блок С, кв 5»):
    house = сам корпус (если в эталоне дома нет, значение в метрику не входит, Q5)."""

    name = "building"

    def __call__(self, state: ParseState) -> ParseState:
        tr = StepTrace(step=self.name)
        groups = self._groups(state)
        if groups:
            house = state.fields.get("house")
            attached: list[list[int]] = []
            if house is not None and house.source == SOURCE_STRING and house.span is not None:
                s, e = house.span
                for idx in groups:
                    gs, ge = self._span(state, idx)
                    if gs >= e and _only_separators(state.raw[e:gs]):
                        e = ge
                        attached.append(idx)
                if attached:
                    value = house_text(state.raw[s:e])
                    state.set_field("house", value, span=(s, e), score=house.score, overwrite=True)
                    tr.notes.append(f"house {value!r}: с корпусом/строением (Q10)")
            elif house is None:
                gs, ge = self._span(state, groups[0])
                nums = [i for i in groups[0] if state.tokens[i].kind == "num"]
                if fold(state.tokens[groups[0][0]].text) in STRUCTURE_WORDS and nums:
                    # «улица Кривенко, строение 25»: строение без дома это и есть номер здания
                    gs, ge = self._span(state, nums)
                value = house_text(state.raw[gs:ge])
                if state.set_field("house", value, span=(gs, ge), score=0.6):
                    attached.append(groups[0])
                    tr.notes.append(f"house {value!r}: дома в строке нет, корпус вместо него")
            for idx in attached:
                for i in idx:
                    state.tokens[i].used_by = "house"
            if len(attached) == len(groups):
                state.flags.discard("building_part_ignored")
        state.trace.append(tr)
        return state

    @staticmethod
    def _groups(state: ParseState) -> list[list[int]]:
        """Подряд идущие токены корпуса («корп», «.», «2») -> группы индексов, слева направо."""
        out: list[list[int]] = []
        for i, t in enumerate(state.tokens):
            if t.used_by != "building":
                continue
            if out and out[-1][-1] == i - 1:
                out[-1].append(i)
            else:
                out.append([i])
        return out

    @staticmethod
    def _span(state: ParseState, idx: list[int]) -> tuple[int, int]:
        toks = state.tokens
        return state.orig_span(toks[idx[0]].start, toks[idx[-1]].end)
