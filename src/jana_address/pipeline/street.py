"""Шаг 6. Тип и название улицы, микрорайон / ЖК.

Правила ТЗ:
  * микрорайон (или другой «площадной» тип) без отдельной улицы -> street_type=«микрорайон», street_name=<имя>;
  * микрорайон + улица -> living_area=<имя мкр>, street_type/street_name = улица;
  * street_name режется из ОРИГИНАЛЬНОЙ строки: без типа, без номера дома, регистр и опечатки как есть.
Номер рядом с маркером площадного типа входит в название («мкр Аксай 3а», «Нурсити 2 микрорайон», «66квартал»).
Если маркера типа нет, улицей считаем свободную группу слов перед номером («Кулманова 133», «Назарбаева8»).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..reference.normalize import fold
from ..reference.store import Store, get_store
from ..rules_loader import Rules, StreetType, get_rules
from .base import ParseState, StepTrace, Token
from .util import mark, marker_ok, match_phrase, segments, value_from

# маркеры, которые в казахском стоят ПОСЛЕ названия («Абай көшесі», «Самал шағын ауданы»)
POSTFIX_FOLDS = frozenset(
    {
        "кошеси",
        "коше",
        "кош",
        "кошесы",
        "дангылы",
        "дангыл",
        "данг",
        "шагын ауданы",
        "шагын аудан",
        "ыкшам аудан",
        "ыкшам ауданы",
        "ыкшамауданы",
        "шагынауданы",
        "тас жолы",
        "тасжолы",
        "аланы",
        "жагалауы",
        "гулзар",
        "желекжолы",
        "орамы",
        "тугыгы",
        "откел",
        "алабы",
        "тургын алабы",
        "тургын уи кешени",
        "ш а",
        "ш/а",
        "ш.а",
    }
)


_DASH_NUM = re.compile(r"\d{1,2}[^\W\d_]?")
# маркеры перекрёстка (они же предлоги ориентира в rules/landmarks.yaml)
INTERSECTION = frozenset({"угол", "уг", "пересечение", "киылысы", "бурышы"})


def _is_initial(toks: list[Token], i: int) -> bool:
    """Заглавная буква с точкой перед словом: «Ш. Мыкитанулы», «К. Аманжолова»."""
    t = toks[i]
    return (
        len(t.text) == 1
        and t.text.isupper()
        and i + 2 < len(toks)
        and toks[i + 1].text == "."
        and toks[i + 2].kind == "word"
        and toks[i + 2].free
    )


def _house_like(t: Token) -> bool:
    """После улицы без маркера: свободный номер или дом, уже взятый по маркеру («Чапаева д.65», «Жамбыла 3дом»)."""
    return (t.kind == "num" and t.free) or t.used_by in ("house", "marker:house")


@dataclass
class Cand:
    st: StreetType
    marker: list[int]
    name: list[int] = field(default_factory=list)
    marked: bool = True

    @property
    def kind(self) -> str:
        return self.st.kind


class Street:
    name = "street"

    def __init__(self, store: Store | None = None, rules: Rules | None = None) -> None:
        self.store = store or get_store()
        self.rules = rules or get_rules()

    # ---------- классификация слов ----------
    def is_stop_word(self, text: str, noise: bool = True) -> bool:
        """Слово, которое не может входить в название улицы. Шумовые слова («Казахстан», «РК») стоп только
        для улицы без маркера: «ул. Казахстан» это настоящая улица."""
        r = self.rules
        if noise and text in r.noise:
            return True
        return (
            text in r.details
            or text in r.street_types
            or text in r.lm_prepositions
            or text in r.lm_objects
            or text in r.lm_brands
            # «к», «с» корпусом бывают только слитно с числом (шаг parts), а «С.Кожанов», «К. Аманжолова» это инициал
            or (text in r.building_part and len(text) > 1)
        )

    def _collect(
        self,
        state: ParseState,
        seg: list[int],
        k: int,
        direction: int,
        area: bool,
        later_free_num: bool,
        complex_: bool = False,
    ) -> list[int]:
        """Имя по одну сторону от маркера в пределах сегмента."""
        toks = state.tokens
        out: list[int] = []
        words = 0
        j = k
        while 0 <= j < len(seg):
            t = toks[seg[j]]
            if t.kind == "punct" and t.text in ".-'\"" and t.free:
                j += direction
                continue
            if not t.free:
                break
            if t.kind == "word":
                if direction > 0 and _is_initial(toks, seg[j]):
                    out.append(seg[j])  # «ул. Ш. Мыкитанулы»: инициал, а не «ш.» (шоссе)
                    j += direction
                    continue
                stop = self.is_stop_word(t.text, noise=False)
                # латиница в названиях ЖК («ЖК EXPO Boulevard», «Luxury Park»): не тип улицы и не ориентир
                if stop and area and t.text.isascii() and t.text not in self.rules.details:
                    stop = False
                if stop and complex_ and direction > 0 and out and self._complex_tail(state, seg, j):
                    out.append(seg[j])  # «ЖК Есентай парк кв 18», «ЖК Изумрудный квартал»: слово-объект в конце имени
                    break
                if stop or words >= 4:
                    break
                out.append(seg[j])
                words += 1
            elif t.kind == "num":
                if not area and direction > 0 and self._dash_number(state, out, seg[j]):
                    out.append(seg[j])  # «Самал-3 40»
                    break
                if not area and direction > 0 and self._name_number(state, out, seg, j):
                    out.append(seg[j])  # «переулок Мусорского 2 д. 51»
                    break
                if not area:
                    # «ул. 8 Марта»: число перед словом в начале имени
                    nxt = seg[j + direction] if 0 <= j + direction < len(seg) else None
                    if (
                        direction > 0
                        and not out
                        and nxt is not None
                        and toks[nxt].kind == "word"
                        and toks[nxt].free
                        and not self.is_stop_word(toks[nxt].text, noise=False)
                    ):
                        out.append(seg[j])
                        j += direction
                        continue
                    break
                if direction > 0 and out and self._glued_dash(toks, out, seg[j]):
                    out.append(seg[j])  # «мкр Коктал-1, ул. ...»: номер через дефис слитно это часть названия
                    break
                if direction < 0:
                    out.append(seg[j])  # «Нурсити 2 микрорайон», «66квартал»
                elif not out:
                    out.append(seg[j])  # «мкр 5»
                    if not any(toks[x].kind == "word" for x in out):
                        # после номера мкр может идти только слово-продолжение, не второй номер
                        nxt = seg[j + 1] if j + 1 < len(seg) else None
                        if nxt is None or toks[nxt].kind != "word":
                            break
                else:
                    if self._area_number(state, out, seg[j], later_free_num):
                        out.append(seg[j])
                    break
            else:
                break
            j += direction
        return out if direction > 0 else out[::-1]

    @staticmethod
    def _glued_dash(toks: list[Token], name: list[int], num: int) -> bool:
        t, dash = toks[num], toks[num - 1]
        return (
            t.free
            and t.glued_left
            and name[-1] == num - 2
            and dash.text == "-"
            and dash.glued_left
            and bool(_DASH_NUM.fullmatch(t.text))
        )

    def _complex_tail(self, state: ParseState, seg: list[int], j: int) -> bool:
        """Слово-объект («парк», «квартал», «сити») после имени ЖК входит в имя, если за ним конец сегмента,
        номер или маркер детали, то есть ориентиром оно быть не может."""
        r, toks = self.rules, state.tokens
        t = toks[seg[j]]
        if t.text in r.details or t.text in r.lm_prepositions:
            return False
        nxt = seg[j + 1] if j + 1 < len(seg) else None
        return nxt is None or toks[nxt].kind == "num" or toks[nxt].text in r.details

    def _name_number(self, state: ParseState, name: list[int], seg: list[int], j: int) -> bool:
        """Короткий номер после названия входит в него, если дом уже взят маркером сразу за номером
        («Мусорского 2 д. 51», «Сыргак батыр 3, 11дом») или справочник города знает имя с номером, а без
        номера нет. «Абая 12 кв 5» не трогаем: за номером маркер квартиры, дома по маркеру нет."""
        toks = state.tokens
        t = toks[seg[j]]
        if not name or not t.free or not re.fullmatch(r"\d{1,2}", t.text):
            return False
        base = " ".join(toks[i].text for i in name)
        cid = state.ref_ids.get("city")
        if cid is not None and self.store.streets(f"{base} {t.text}", cid) and not self.store.streets(base, cid):
            return True
        k = seg[j] + 1
        while k < len(toks) and (toks[k].kind == "sep" or toks[k].text == "."):
            k += 1
        return "house" in state.fields and k < len(toks) and toks[k].used_by in ("marker:house", "house")

    def _dash_number(self, state: ParseState, name: list[int], num: int) -> bool:
        """«Самал-3 40», «САУЛЕТ-11 д.61»: короткий номер слитно через дефис входит в название, если справочник
        знает такое имя или дальше есть дом. Иначе («Абая-12 кв 5») это номер дома."""
        toks = state.tokens
        t = toks[num]
        if not name or not t.free or not t.glued_left or name[-1] != num - 2 or not _DASH_NUM.fullmatch(t.text):
            return False
        dash = toks[num - 1]
        if dash.text != "-" or not dash.glued_left:
            return False
        full = " ".join(toks[i].text for i in name) + "-" + t.text
        if self.store.lookup(full, ("street", "living_area")):
            return True
        return "house" in state.fields or any(u.kind == "num" and u.free for u in toks[num + 1 :])

    def _area_number(self, state: ParseState, name: list[int], num: int, later_free_num: bool) -> bool:
        """Входит ли число после имени микрорайона в его название («Аксай 3а») или это дом."""
        toks = state.tokens
        base = " ".join(toks[i].text for i in name)
        if self.store.lookup(f"{base} {toks[num].text}", ("living_area",)):
            return True
        k = num + 1
        while k < len(toks) and (toks[k].kind == "sep" or toks[k].text == "."):
            k += 1
        if k < len(toks) and toks[k].used_by in ("marker:house", "house"):
            return True  # «мкр Акмешит 3 дом 10»: дом идёт по маркеру сразу за номером, номер в названии
        if self.store.lookup(base, ("living_area",)):
            return False
        # дальше есть ещё свободный номер (это дом) или дом уже найден по маркеру
        later = any(t.kind == "num" and t.free for t in toks[num + 1 :])
        if "house" in state.fields or later:
            return True
        return bool(toks[num].text[-1:].isalpha())

    # ---------- проход ----------
    def __call__(self, state: ParseState) -> ParseState:
        tr = StepTrace(step=self.name)
        toks = state.tokens
        segs = segments(toks)
        cands: list[Cand] = []

        for si, seg in enumerate(segs):
            k = 0
            while k < len(seg):
                t = toks[seg[k]]
                if not t.free or t.kind != "word":
                    k += 1
                    continue
                m = match_phrase(state, self.rules.street_types, seg, k)  # type: ignore[arg-type]
                if not m or not marker_ok(state, self.rules, seg, k, m[1]):
                    k += 1
                    continue
                st, n = m
                assert isinstance(st, StreetType)
                marker = seg[k : k + n]
                area = st.kind in ("area", "numbered")
                later = any(toks[i].kind == "num" and toks[i].free for s in segs[si:] for i in s if i > marker[-1])
                after = self._collect(state, seg, k + n, +1, area, later, st.canonical == "жилой комплекс")
                before = self._collect(state, seg, k - 1, -1, area, later)
                # реестровый формат «ШУХОВА (УЛИЦА), 37Б»: тип в скобках после названия
                paren = k > 0 and toks[seg[k - 1]].text == "(" and k + n < len(seg) and toks[seg[k + n]].text == ")"
                if paren:
                    before = self._collect(state, seg, k - 2, -1, area, later)
                mfold = " ".join(fold(toks[i].text) for i in marker)
                after_words = any(toks[i].kind == "word" for i in after)
                if (mfold in POSTFIX_FOLDS or paren) and before:
                    name = before
                # «66квартал 12»: с обеих сторон только числа -> номер перед маркером это имя, после это дом
                elif after and (after_words or not before):
                    name = after
                elif before:
                    name = before
                else:
                    name = after
                if not name and st.kind == "street":
                    # «ул. 5, д. 7»: номер как название улицы, если дом уже найден по маркеру
                    nxt_i = k + n
                    while nxt_i < len(seg) and toks[seg[nxt_i]].kind == "punct" and toks[seg[nxt_i]].text == ".":
                        nxt_i += 1
                    if (
                        nxt_i < len(seg)
                        and toks[seg[nxt_i]].kind == "num"
                        and toks[seg[nxt_i]].free
                        and "house" in state.fields
                        # «ул. 5, д. 7» или «ул 7 д 14»: за номером конец сегмента или маркер дома
                        and (nxt_i == len(seg) - 1 or toks[seg[nxt_i + 1]].used_by == "marker:house")
                    ):
                        name = [seg[nxt_i]]
                if not name:
                    k += n
                    continue
                c = Cand(st, marker, name)
                cands.append(c)
                mark(state, marker, "marker:street")
                mark(state, name, "street:pending")
                k += n

        streets = [c for c in cands if c.kind in ("street", "numbered")]
        areas = [c for c in cands if c.kind == "area"]
        if not streets:
            guess = self._guess(state, segs)
            if guess:
                streets = [Cand(StreetType("", "street"), [], guess, marked=False)]
                state.flags.add("guessed_street")

        main: Cand | None = None
        living: Cand | None = None
        if streets:
            main = streets[0]
            living = areas[0] if areas else None
        elif areas:
            main = areas[-1]
            living = areas[0] if len(areas) > 1 else None

        if main is not None:
            v = value_from(state, [toks[i] for i in main.name])
            if v:
                state.set_field("street_name", v[0], span=v[1], score=1.0 if main.marked else 0.7)
                if main.st.canonical:
                    span = value_from(state, [toks[i] for i in main.marker])
                    state.set_field("street_type", main.st.canonical, span=span[1] if span else None)
                tr.notes.append(f"street {main.st.canonical or '?'} {v[0]!r}")
            mark(state, main.name, "street_name")
        if living is not None:
            v = value_from(state, [toks[i] for i in living.name])
            if v:
                state.set_field("living_area", v[0], span=v[1])
                state.ref_ids["living_area_type"] = living.st.canonical
                tr.notes.append(f"living_area {living.st.canonical} {v[0]!r}")
            mark(state, living.name, "living_area")
        # кандидаты, не ставшие ни улицей, ни living_area, возвращаются в свободные
        for c in cands:
            if c is not main and c is not living:
                for i in c.name:
                    toks[i].used_by = None
                for i in c.marker:
                    toks[i].used_by = None
        if main is not None and main.name:
            state.ref_ids["street_end"] = max(main.name)
        state.trace.append(tr)
        return state

    def _number_name(self, state: ParseState, seg: list[int], k: int) -> bool:
        """Число в начале названия улицы без маркера: «40 лет Победы», «9 Мая», «30 лет Казахстана». Только если за
        числом слово из number_name_words (rules/markers.yaml) или справочник города знает «число + слова»."""
        toks = state.tokens
        t = toks[seg[k]]
        if t.kind != "num" or not t.free or not t.text.isdigit() or k + 1 >= len(seg):
            return False
        nxt = toks[seg[k + 1]]
        if nxt.kind != "word" or not nxt.free or nxt.glued_left:
            return False
        if fold(nxt.text) in self.rules.number_name_words:
            return True
        cid = state.ref_ids.get("city")
        if cid is None:
            return False
        words = [t.text]
        for x in seg[k + 1 : k + 4]:
            if toks[x].kind != "word" or not toks[x].free:
                break
            words.append(toks[x].text)
            if self.store.streets(" ".join(words), cid):
                return True
        return False

    def _guess(self, state: ParseState, segs: list[list[int]]) -> list[int] | None:
        """Улица без маркера: свободная группа слов, за которой идёт свободный номер или дом по маркеру."""
        toks = state.tokens
        second: list[int] | None = None
        for si, seg in enumerate(segs):
            k = 0
            while k < len(seg):
                t = toks[seg[k]]
                lead_num = self._number_name(state, seg, k)
                if not lead_num and (not (t.free and t.kind == "word") or self.is_stop_word(t.text)):
                    k += 1
                    continue
                run: list[int] = [seg[k]] if lead_num else []
                j = k + 1 if lead_num else k
                while j < len(seg):
                    u = toks[seg[j]]
                    if u.kind == "punct" and u.text in ".-'" and u.free:
                        j += 1
                        continue
                    if u.kind == "word" and u.free and not self.is_stop_word(u.text) and len(run) < 4:
                        run.append(seg[j])
                        j += 1
                        continue
                    if u.kind == "num" and self._dash_number(state, run, seg[j]):
                        run.append(seg[j])
                        j += 1
                    break
                nxt = toks[seg[j]] if j < len(seg) else None
                if run and nxt is not None and _house_like(nxt):
                    return run
                # «Шаляпина угол Саина, д 34»: перекрёсток, улица записи первая, вторая уходит в ориентир
                if (
                    run
                    and nxt is not None
                    and fold(nxt.text) in INTERSECTION
                    and ("house" in state.fields or any(u.kind == "num" and u.free for u in toks[seg[j] :]))
                ):
                    return run
                # «Тараз қаласы Добролюбова, 22»: до улицы в сегменте только уже разобранное (город)
                if (
                    run
                    and nxt is None
                    and all(not toks[x].free or toks[x].kind == "punct" for x in seg[:k])
                    and second is None
                    and si + 1 < len(segs)
                    and _house_like(toks[segs[si + 1][0]])
                ):
                    second = run
                k = max(j, k + 1)
        return second
