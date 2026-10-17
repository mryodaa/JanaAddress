"""Шаг arbiter: сверка полей правил с разметкой теггера, решение по спорным полям совместно.

Для каждого поля до двух кандидатов: правила (значение, спан, score шага) и модель (спан, откалиброванная
вероятность). Совпали спаны: остаётся значение правил (флаг model_agree). Разошлись: каждого кандидата проверяем
справочником (город существует и согласован, улица есть в городе, дом на улице, мкр в городе) и грамматикой
(этаж <= 40, подъезд <= 20, квартира правдоподобна); спорные поля решаются перебором комбинаций с запретом
пересечения спанов (один символ raw не принадлежит двум полям). Веса в rules/arbiter.yaml.

Значения модели строятся так же, как у правил: строковые поля срезом raw по спану (tidy_value), canonical-поля
(province, city, district) модель только локализует, вид ответа даёт справочник; без совпадения в справочнике
кандидат модели недействителен. Режимы: shadow (только trace/explain), on (применяем), only (поля только модели,
для оценки eval --mode tagger).
"""

from __future__ import annotations

import itertools
import re
from dataclasses import dataclass, field
from typing import Any

from ..models import PARSED_FIELDS
from ..reference.store import Entity, Store
from ..rules_loader import Rules
from ..tagger.runtime import Prediction
from .base import SOURCE_STRING, ParseState, StepTrace
from .reference_step import AREA_TYPES, historical_province
from .util import as_written, house_text, tidy_value, trim_span

LABEL = {f: f.upper() for f in PARSED_FIELDS}
CANONICAL = ("province", "city", "district")
ETYPE = {"province": "province", "city": "city", "district": "district"}
_HOUSE = re.compile(r"^\d{1,4}(?:[ -]?[^\W\d_])?(?:/\d{1,4}(?:[ -]?[^\W\d_])?)?$")
_SMALL_NUM = re.compile(r"^\d{1,4}(?:[ -]?[^\W\d_])?$")
_PHONE_LIKE = re.compile(r"\d{6,}")


def _script(ch: str) -> str:
    if not ch.isalpha():
        return "other"
    return "lat" if ch.isascii() else "cyr"


# проверки, которые подтверждают топоним вторым полем записи (улица в этом городе, город в этой области)
CORROBORATE = frozenset({"ref_consistent", "street_in_city", "house_on_street", "city_status"})
# город со статусом города в начале записи и дальше слово: «Жанаозен Самал 12-4» (одноимённых сёл у таких нет,
# а «Аксай 3а 59» с номером сразу после названия это микрорайон, не город)
_CITY_HEAD = re.compile(r"^[\s,.;:/|-]*$")
_WORD_NEXT = re.compile(r"^[\s,]*[^\W\d_]")


@dataclass
class Cand:
    fname: str
    source: str  # rules | model
    value: str
    span: tuple[int, int] | None  # обрезанный спан в raw
    p: float
    entity: Entity | None = None
    alts: list[Entity] = field(default_factory=list)  # одноимённые топонимы: выбор по улице записи
    checks: dict[str, float] = field(default_factory=dict)
    score: float = 0.0

    def brief(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "span": list(self.span) if self.span else None,
            "p": round(self.p, 3),
            "score": round(self.score, 3),
            "checks": {k: round(v, 2) for k, v in self.checks.items()},
        }


class _Lookups:
    """Запросы к справочнику в пределах одной записи: перебор комбинаций спорных полей повторяет одни и те же
    проверки (до 2^8 раз). Кэш живёт один вызов арбитра, между записями ничего не хранится."""

    def __init__(self, store: Store) -> None:
        self._store = store
        self._memo: dict[tuple[Any, ...], Any] = {}

    def __call__(self, method: str, *args: Any) -> Any:
        key = (method, *args)
        if key not in self._memo:
            self._memo[key] = getattr(self._store, method)(*args)
        return self._memo[key]


class Arbiter:
    name = "arbiter"

    def __init__(self, store: Store, rules: Rules, mode: str) -> None:
        self.store = store
        self.rules = rules
        self.mode = mode
        cfg = rules.arbiter
        wp = cfg.get("w_p", 1.0)
        # вес p по источнику: p правил (score шага) и p модели (калибровка на val) в разных шкалах
        self.w_p = (
            {k: float(wp.get(k, 1.0)) for k in ("rules", "model")}
            if isinstance(wp, dict)
            else {
                "rules": float(wp),
                "model": float(wp),
            }
        )
        self.prior = cfg.get("prior", {"rules": 0.35, "model": 0.0})
        self.rules_p = cfg.get("rules_p", {"default": 0.9})
        self.w = cfg.get("checks", {})
        self.accept = cfg.get("accept_model_only", {"default": 1.3})
        self.min_p = cfg.get("min_p_model_only", {"default": 0.9})
        self.noise_p = float(cfg.get("noise_p", 0.8))
        self.max_disputed = int(cfg.get("max_disputed", 8))
        self.hard_veto = set(cfg.get("hard_veto", ["grammar_bad", "marker_only"]))

    def _get(self, table: dict[str, Any], f: str) -> float:
        return float(table.get(f, table.get("default", 0.0)))

    # ---------- кандидаты ----------
    def _rules_cands(self, state: ParseState) -> dict[str, Cand]:
        out = {}
        for f, fv in state.fields.items():
            if fv.source != SOURCE_STRING:
                continue
            span = trim_span(state.raw, *fv.span) if fv.span else None
            ent = self.store.get(ETYPE[f], state.ref_ids.get(f)) if f in CANONICAL else None
            p = min(1.0, self._get(self.rules_p, f) * fv.score)
            out[f] = Cand(f, "rules", fv.value, span, p, ent)
        return out

    def _lookup(self, f: str, text: str, ctx_prov: int | None) -> list[Entity]:
        found = self.store.lookup(text, (ETYPE[f],))
        if not found and f == "province":
            found = self.store.lookup(f"{text} область", ("province",))
        if ctx_prov is not None:
            same = [e for e in found if e.province_id == ctx_prov]
            found = same or found
        # города раньше сёл: «Акколь» без уточнений скорее город
        rank = {"republican": 0, "city": 1, "town": 2, "village": 3}
        src = {"seed": 0, "osm": 1, "kato": 2}  # пункт только из КАТО (без улиц) после подтверждённых OSM
        return sorted(found, key=lambda e: (rank.get(e.kind or "", 4), src.get(e.source, 3)))

    @staticmethod
    def _guarded(state: ParseState) -> list[tuple[int, int, str]]:
        """Спаны токенов, которые модель не может забрать в поле: корпус/строение, организация, телефон, индекс,
        маркеры деталей («кв», «корп», «д.»). Иначе «Абая 5 корп 2» -> улица «Абая 5 корп», дом «2»."""
        out = []
        city = state.fields.get("city")
        for t in state.tokens:
            lab = t.used_by or ""
            span = state.orig_span(t.start, t.end)
            if (
                lab == "admin:city"
                and city is not None
                and city.span is not None
                and not (city.span[0] <= span[0] < city.span[1])
            ):
                # повтор города вне спана поля city («город Караганда/..., Караганда Ермекова 77/2»)
                out.append((*span, "admin:city_dup"))
                continue
            # kz_dup: казахская половина двуязычной записи («Алматы облысы»), поле из неё было бы дублем
            if (
                lab in ("building", "kz_dup")
                or lab.startswith("noise")
                or (lab.startswith("marker:") and lab != "marker:city")
            ):
                out.append((*state.orig_span(t.start, t.end), lab))
        return out

    @staticmethod
    def _bounds(state: ParseState) -> tuple[set[int], set[int]]:
        """Где спан модели может начинаться и кончаться: границы токенов, а внутри слова ещё и смена регистра,
        алфавита или класса символа («улциаАбая», «47Бдом»: склейку токенизатор правил не разделил). Номер
        неделим: «Абая-1|2» и «33| / 1» недействительны."""
        starts, ends = set(), set()
        raw = state.raw
        for t in state.tokens:
            a, b = state.orig_span(t.start, t.end)
            starts.add(a)
            ends.add(b)
            if t.kind != "word":
                continue
            for i in range(a + 1, b):
                x, y = raw[i - 1], raw[i]
                if (x.islower() and y.isupper()) or x.isdigit() != y.isdigit() or _script(x) != _script(y):
                    starts.add(i)
                    ends.add(i)
        return starts, ends

    def _model_cands(self, state: ParseState, pred: Prediction, rules: dict[str, Cand]) -> dict[str, Cand]:
        out: dict[str, Cand] = {}
        raw = state.raw
        starts, ends = self._bounds(state)
        guarded = self._guarded(state)
        prov = rules["province"].entity.id if "province" in rules and rules["province"].entity else None
        for f in PARSED_FIELDS:
            spans = sorted(pred.of(LABEL[f]), key=lambda s: -s.p_cal)
            for sp in spans:
                s, e = trim_span(raw, sp.start, sp.end)
                if s >= e or s not in starts or e not in ends:
                    continue
                # правила уверенно разобрали это как корпус, организацию, телефон или маркер детали
                # повтор города не даём только в улицу: «ЖК Реал Алматы» это имя ЖК с названием города
                if any(gs < e and s < ge
                       and not (f in ("street_name", "street_type") and lab == "marker:street")
                       and not (lab == "admin:city_dup" and f != "street_name")
                       for gs, ge, lab in guarded):  # fmt: skip
                    continue
                text = raw[s:e]
                ent: Entity | None = None
                alts: list[Entity] = []
                if f in CANONICAL:
                    alts = self._lookup(f, tidy_value(text), prov)
                    if not alts:
                        continue
                    ent = alts[0]
                    # Q13/Q22: город и район как в строке, область каноном справочника (слайд 08)
                    value = ent.name if f == "province" else as_written(tidy_value(text), ent.name)
                elif f == "street_type":
                    st = self.rules.street_types.get(text)
                    if st is None:
                        continue
                    value = st.canonical
                elif f in ("house", "apartment", "entrance", "floor"):
                    value = house_text(text)
                else:
                    value = tidy_value(text)
                if value:
                    out[f] = Cand(f, "model", value, (s, e), sp.p_cal, ent, alts)
                    break
        return out

    # ---------- проверки ----------
    def _checks(
        self, c: Cand, ctx: dict[str, Cand], pred: Prediction | None, raw: str, look: _Lookups
    ) -> dict[str, float]:
        w, f, v = self.w, c.fname, c.value
        out: dict[str, float] = {}
        city = ctx.get("city")
        city_e = city.entity if city else None
        prov = ctx.get("province")
        prov_e = prov.entity if prov else None
        if f == "city" and len(c.alts) > 1:
            # одноимённые сёла: берём то, где есть улица записи, иначе то, что в области записи
            st, typ = ctx.get("street_name"), ctx.get("street_type")
            with_street = (
                [a for a in c.alts if look("streets", st.value, a.id)]
                if st is not None and (typ is None or typ.value not in AREA_TYPES)
                else []
            )
            in_prov = [a for a in c.alts if prov_e is not None and a.province_id == prov_e.id]
            # район в строке различает одноимённые сёла одной и разных областей («Аральский район, Абай»)
            dist = ctx.get("district")
            dist_e = dist.entity if dist else None
            in_dist = [a for a in c.alts if dist_e is not None and a.district_id == dist_e.id]
            c.entity = ([a for a in in_dist if a in with_street] or in_dist or with_street or in_prov or c.alts)[0]
        if f in CANONICAL and c.entity is not None:
            out["ref_exists"] = w.get("ref_exists", 0.0)
            e = c.entity
            if f == "city" and prov_e is not None:
                ok = e.province_id == prov_e.id or historical_province(self.rules, self.store, prov_e, e)
                key = "ref_consistent" if ok else "ref_conflict"
                out[key] = w.get(key, 0.0)
            if f == "province" and city_e is not None:
                ok = city_e.province_id == e.id or historical_province(self.rules, self.store, e, city_e)
                key = "ref_consistent" if ok else "ref_conflict"
                out[key] = w.get(key, 0.0)
            if f == "district" and city_e is not None and e.kind == "city":
                key = "ref_consistent" if e.city_id == city_e.id else "ref_conflict"
                out[key] = w.get(key, 0.0)
            if f == "city":
                st, typ = ctx.get("street_name"), ctx.get("street_type")
                area = typ is not None and typ.value in AREA_TYPES
                if st is not None and not area and look("streets", st.value, e.id):
                    out["street_in_city"] = w.get("street_in_city", 0.0)
                if (
                    e.kind in ("republican", "city")
                    and c.span is not None
                    and _CITY_HEAD.match(raw[: c.span[0]])
                    and _WORD_NEXT.match(raw[c.span[1] :])
                ):
                    out["city_status"] = w.get("city_status", 0.0)
        elif f == "street_name":
            area = ctx.get("street_type") is not None and ctx["street_type"].value in AREA_TYPES
            cid = city_e.id if city_e else None
            if not area and cid is not None:
                streets = look("streets", v, cid)
                if streets:
                    out["street_in_city"] = w.get("street_in_city", 0.0)
                    h = ctx.get("house")
                    if h is not None and any(look("house", s.id, h.value) for s in streets):
                        out["house_on_street"] = w.get("house_on_street", 0.0)
                elif look("street_fuzzy", v, cid):
                    out["street_fuzzy"] = w.get("street_fuzzy", 0.0)
            elif area:
                found = look("lookup", v, ("living_area",))
                if found and cid is not None and any(a.city_id == cid for a in found):
                    out["area_in_city"] = w.get("area_in_city", 0.0)
            if _PHONE_LIKE.search(v) or (not re.search(r"[^\W\d_]", v) and not area):
                out["grammar_bad"] = w.get("grammar_bad", 0.0)
            if self._marker_only(v):
                out["marker_only"] = w.get("marker_only", 0.0)
        elif f == "living_area":
            found = look("lookup", v, ("living_area",))
            if found and city_e is not None and any(a.city_id == city_e.id for a in found):
                out["area_in_city"] = w.get("area_in_city", 0.0)
        elif f in ("house", "apartment", "entrance", "floor"):
            ok = self._grammar(f, v)
            out["grammar_ok" if ok else "grammar_bad"] = w.get("grammar_ok" if ok else "grammar_bad", 0.0)
            if (
                f == "house"
                and ok
                and city_e is not None
                and "street_name" in ctx
                and any(look("house", s.id, v) for s in look("streets", ctx["street_name"].value, city_e.id))
            ):
                out["house_on_street"] = w.get("house_on_street", 0.0)
        elif f == "landmark" and self._marker_only(v):
            out["marker_only"] = w.get("marker_only", 0.0)
        if pred is not None and c.span is not None and f not in ("street_type",):
            cs, ce = c.span
            if any(
                sp.label in ("NOISE", "KZ_DUP") and sp.p_cal >= self.noise_p and sp.start < ce and cs < sp.end
                for sp in pred.spans
            ):
                out["noise_overlap"] = w.get("noise_overlap", 0.0)
        return out

    def _grammar(self, f: str, v: str) -> bool:
        if f == "house":
            return bool(_HOUSE.match(v))
        if not _SMALL_NUM.match(v):
            return False
        n = int(re.match(r"\d+", v).group())  # type: ignore[union-attr]
        limit = {"apartment": 2000, "entrance": 20, "floor": 40}[f]
        return 0 < n <= limit

    def _marker_only(self, v: str) -> bool:
        r = self.rules
        return v in r.street_types or v in r.details or v in r.noise or v in r.city_prefix or v in r.province_markers

    def _score(self, c: Cand, ctx: dict[str, Cand], pred: Prediction | None, raw: str, look: _Lookups) -> float:
        c.checks = self._checks(c, ctx, pred, raw, look)
        c.score = float(self.prior.get(c.source, 0.0)) + self.w_p[c.source] * c.p + sum(c.checks.values())
        return c.score

    # ---------- решение ----------
    def __call__(self, state: ParseState) -> ParseState:
        tr = StepTrace(step=self.name)
        pred = state.model
        if pred is None:
            tr.notes.append("нет разметки модели: поля правил без изменений")
            state.trace.append(tr)
            return state
        rules = self._rules_cands(state)
        model = self._model_cands(state, pred, rules)
        look = _Lookups(self.store)
        if self.mode == "only":
            self._apply_only(state, model, tr)
            state.trace.append(tr)
            return state

        agree, disputed = [], []
        for f in PARSED_FIELDS:
            r, m = rules.get(f), model.get(f)
            if r is None and m is None:
                continue
            if r is not None and m is not None and self._same(r, m):
                agree.append(f)
            elif m is not None:
                disputed.append(f)
            # только правила: оставляем (модель могла не увидеть поле), но это расхождение
        rules_only = [f for f in rules if f not in model]
        options = {f: [c for c in (rules.get(f), model.get(f)) if c is not None] for f in disputed}
        for f in disputed:
            if f not in rules:
                options[f].append(None)  # type: ignore[arg-type]  # null: поле модели не принято

        choice = {f: rules.get(f) for f in disputed}
        if disputed and len(disputed) <= self.max_disputed:
            choice = self._solve(state, rules, options, agree, pred, look)
        # счёт всех кандидатов в контексте итогового решения: для trace и для training/fit_arbiter.py
        final = {f: c for f, c in rules.items() if f not in choice} | {f: c for f, c in choice.items() if c}
        for c in (*rules.values(), *model.values()):
            self._score(c, final, pred, state.raw, look)
        decisions: dict[str, Any] = {}
        changed = []
        for f in PARSED_FIELDS:
            r, m = rules.get(f), model.get(f)
            if r is None and m is None:
                continue
            d: dict[str, Any] = {"rules": r.brief() if r else None, "model": m.brief() if m else None}
            if f in agree:
                d["decision"] = "agree"
            elif f in disputed:
                win = choice.get(f)
                d["decision"] = "none" if win is None else win.source
                if win is not None and win.source == "model":
                    changed.append(f)
            else:
                d["decision"] = "rules_only"
            decisions[f] = d
        state.arbiter = {"mode": self.mode, "fields": decisions, "applied": self.mode == "on" and bool(changed)}

        if agree and not disputed and not rules_only:
            state.flags.add("model_agree_all")
        if disputed or rules_only:
            state.flags.add("model_disagree")
        tr.notes.append(
            f"согласны: {', '.join(agree) or '-'}; спор: {', '.join(disputed) or '-'}; "
            f"только правила: {', '.join(rules_only) or '-'}"
        )
        for f in disputed:
            win = choice.get(f)
            tr.notes.append(
                f"{f}: правила {rules[f].value!r} ({rules[f].score:.2f})" if f in rules else f"{f}: правила null"
            )
            tr.notes[-1] += (
                f" vs модель {model[f].value!r} ({model[f].score:.2f}) -> "
                + ("null" if win is None else win.source)
                + f" {model[f].checks}"
            )
        if self.mode == "on" and changed:
            for f in changed:
                self._apply(state, choice[f], rules.get(f))  # type: ignore[arg-type]
            state.flags.add("model_override")
        state.trace.append(tr)
        return state

    def _same(self, r: Cand, m: Cand) -> bool:
        if r.fname in CANONICAL and r.entity is not None and m.entity is not None:
            return r.span == m.span or r.entity.id in {a.id for a in m.alts} or r.entity.id == m.entity.id
        if r.span is not None and m.span is not None:
            return r.span == m.span
        return r.value.casefold() == m.value.casefold()

    def _solve(
        self,
        state: ParseState,
        rules: dict[str, Cand],
        options: dict[str, list[Cand]],
        agree: list[str],
        pred: Prediction,
        look: _Lookups,
    ) -> dict[str, Cand | None]:
        """Перебор комбинаций спорных полей: максимум суммы счётов без пересечения спанов разных полей."""
        fixed = {f: rules[f] for f in rules if f not in options}  # согласованные и «только правила»
        names = list(options)
        baseline = tuple(rules.get(f) for f in names)
        best: tuple[float, float, tuple[Cand | None, ...]] | None = None
        for combo in itertools.product(*(options[f] for f in names)):
            ctx = dict(fixed)
            ctx.update({f: c for f, c in zip(names, combo, strict=True) if c is not None})
            if combo != baseline and (self._overlap(ctx) or not self._covered(state.raw, rules, ctx, pred)):
                continue
            total, p_sum = 0.0, 0.0
            for f, c in zip(names, combo, strict=True):
                if c is None:
                    total += self._get(self.accept, f)  # порог: модель должна набрать больше
                    continue
                s = self._score(c, ctx, pred, state.raw, look)
                only_model = c.source == "model" and f not in rules
                if c.source == "model" and (
                    self.hard_veto & set(c.checks)
                    or (only_model and c.p < self._get(self.min_p, f))
                    # топоним только от модели: одного существования мало (сёл «Солнечный» тысячи), нужно второе поле
                    or (only_model and f in CANONICAL and not CORROBORATE & set(c.checks))
                ):
                    s = float("-inf")
                total += s
                p_sum += c.p
            if best is None or (total, p_sum) > (best[0], best[1]):
                best = (total, p_sum, combo)
        assert best is not None
        # счёт для trace у всех кандидатов в контексте победившей комбинации
        ctx = dict(fixed)
        ctx.update({f: c for f, c in zip(names, best[2], strict=True) if c is not None})
        for f in names:
            for c in options[f]:
                if c is not None:
                    self._score(c, ctx, pred, state.raw, look)
        return dict(zip(names, best[2], strict=True))

    def _covered(self, raw: str, rules: dict[str, Cand], ctx: dict[str, Cand], pred: Prediction) -> bool:
        """Модель забрала у правил часть спана поля: остаток должен достаться другому принятому полю или уверенному
        мусору модели. «Бесагаш Айтеке би» -> город + улица можно; «Нурсити 2» -> «2», если «Нурсити» никуда не
        делся (город не найден в справочнике), нельзя: поле правил просто обрезано."""
        taken = [c.span for c in ctx.values() if c.span is not None]
        taken += [
            (sp.start, sp.end) for sp in pred.spans if sp.label in ("NOISE", "KZ_DUP") and sp.p_cal >= self.noise_p
        ]
        for f, c in ctx.items():
            r = rules.get(f)
            if c.source != "model" or r is None or r.span is None:
                continue
            for i in range(*r.span):
                if raw[i].isalnum() and not any(a <= i < b for a, b in taken):
                    return False
        return True

    @staticmethod
    def _overlap(ctx: dict[str, Cand]) -> bool:
        spans = sorted((c.span, f) for f, c in ctx.items() if c.span is not None)
        return any(a[0][1] > b[0][0] for a, b in itertools.pairwise(spans))

    # ---------- применение ----------
    def _tokens_in(self, state: ParseState, span: tuple[int, int]) -> list[int]:
        s, e = span
        out = []
        for i, t in enumerate(state.tokens):
            ts, te = state.orig_span(t.start, t.end)
            if ts < e and s < te:
                out.append(i)
        return out

    def _apply(self, state: ParseState, c: Cand, old: Cand | None) -> None:
        f = c.fname
        if old is not None and old.span is not None:
            for i in self._tokens_in(state, old.span):
                if state.tokens[i].used_by in (f, f"admin:{f}"):
                    state.tokens[i].used_by = None
        assert c.span is not None
        state.set_field(f, c.value, span=c.span, score=c.p, overwrite=True)
        if c.entity is not None:
            state.ref_ids[f] = c.entity.id
            if f == "city" and c.entity.province_id and "province" not in state.fields:
                state.ref_ids["province"] = c.entity.province_id
        for i in self._tokens_in(state, c.span):
            state.tokens[i].used_by = f

    def _apply_only(self, state: ParseState, model: dict[str, Cand], tr: StepTrace) -> None:
        """Режим only: поля только из модели (оценка самой модели; canonical через справочник)."""
        for f in [f for f, fv in state.fields.items() if fv.source == SOURCE_STRING]:
            del state.fields[f]
        for k in ("province", "city", "district", "street_end", "living_area_type"):
            state.ref_ids.pop(k, None)
        for t in state.tokens:
            if t.used_by is not None and not t.used_by.startswith("noise"):
                t.used_by = None
        for c in model.values():
            self._apply(state, c, None)
        tr.notes.append("режим only: " + ", ".join(f"{f}={c.value!r}" for f, c in model.items()))
        state.arbiter = {"mode": "only", "fields": {f: {"model": c.brief()} for f, c in model.items()}}
