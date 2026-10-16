"""Шаг 6. Тип и название улицы, микрорайон / ЖК.

Правила ТЗ:
  * микрорайон (или другой «площадной» тип) без отдельной улицы -> street_type=«микрорайон», street_name=<имя>;
  * микрорайон + улица -> living_area=<имя мкр>, street_type/street_name = улица;
  * street_name режется из ОРИГИНАЛЬНОЙ строки: без типа, без номера дома, регистр и опечатки как есть.
Номер рядом с маркером площадного типа входит в название («мкр Аксай 3а», «Нурсити 2 микрорайон», «66квартал»).
Если маркера типа нет, улицей считаем свободную группу слов перед номером («Кулманова 133», «Назарбаева8»).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..reference.normalize import fold
from ..reference.store import Store, get_store
from ..rules_loader import Rules, StreetType, get_rules
from .base import ParseState, StepTrace
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
            or text in r.building_part
        )

    def _collect(
        self, state: ParseState, seg: list[int], k: int, direction: int, area: bool, later_free_num: bool
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
                if self.is_stop_word(t.text, noise=False) or words >= 4:
                    break
                out.append(seg[j])
                words += 1
            elif t.kind == "num":
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

    def _area_number(self, state: ParseState, name: list[int], num: int, later_free_num: bool) -> bool:
        """Входит ли число после имени микрорайона в его название («Аксай 3а») или это дом."""
        toks = state.tokens
        base = " ".join(toks[i].text for i in name)
        if self.store.lookup(f"{base} {toks[num].text}", ("living_area",)):
            return True
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
                after = self._collect(state, seg, k + n, +1, area, later)
                before = self._collect(state, seg, k - 1, -1, area, later)
                mfold = " ".join(fold(toks[i].text) for i in marker)
                after_words = any(toks[i].kind == "word" for i in after)
                before_words = any(toks[i].kind == "word" for i in before)
                if mfold in POSTFIX_FOLDS and before:
                    name = before
                elif after and (after_words or not before_words):
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
                        and nxt_i == len(seg) - 1
                        and "house" in state.fields
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

    def _guess(self, state: ParseState, segs: list[list[int]]) -> list[int] | None:
        """Улица без маркера: свободная группа слов, за которой идёт свободный номер."""
        toks = state.tokens
        second: list[int] | None = None
        for si, seg in enumerate(segs):
            k = 0
            while k < len(seg):
                t = toks[seg[k]]
                if not (t.free and t.kind == "word") or self.is_stop_word(t.text):
                    k += 1
                    continue
                run: list[int] = []
                j = k
                while j < len(seg):
                    u = toks[seg[j]]
                    if u.kind == "punct" and u.text in ".-'" and u.free:
                        j += 1
                        continue
                    if u.kind == "word" and u.free and not self.is_stop_word(u.text) and len(run) < 4:
                        run.append(seg[j])
                        j += 1
                        continue
                    break
                nxt = toks[seg[j]] if j < len(seg) else None
                if run and nxt is not None and nxt.kind == "num" and nxt.free:
                    return run
                if run and nxt is None and k == 0 and second is None and si + 1 < len(segs):
                    first_next = toks[segs[si + 1][0]]
                    if first_next.kind == "num" and first_next.free:
                        second = run
                k = max(j, k + 1)
        return second
