"""Шаги пайплайна по отдельности: каждый тестируется на своём входе, без остальных шагов где можно."""

from __future__ import annotations

from pathlib import Path

import pytest

from jana_address.pipeline.base import ParseState
from jana_address.pipeline.bilingual import SplitBilingual
from jana_address.pipeline.clean import Clean, clean_text
from jana_address.pipeline.runner import Pipeline
from jana_address.pipeline.steps import build_default
from jana_address.pipeline.tokenize import Tokenize, tokenize

STEPS = {s.name: s for s in build_default()}
ORDER = [s.name for s in build_default()]


def run_until(raw: str, last: str) -> ParseState:
    steps = [STEPS[n] for n in ORDER[: ORDER.index(last) + 1]]
    return Pipeline(steps).run(raw)


# ---------------- clean ----------------
@pytest.mark.parametrize(
    "raw,clean",
    [
        ("ул.\u00a0Абая\u200b 150", "ул. Абая 150"),
        ("Ул .Курильская  9", "Ул.Курильская 9"),
        ("\ufeffАбая\u2060 1\u00ad0", "Абая 10"),
        ("a\x00b\x07c", "abc"),
        ("Абая\n12", "Абая,12"),
        ("  Абая   1 , кв 2  ", "Абая 1, кв 2"),
        ("Казибек би— 5", "Казибек би- 5"),
        ("й", "й"),  # NFD -> NFC
    ],
)
def test_clean_text(raw: str, clean: str) -> None:
    text, offs = clean_text(raw)
    assert text == clean
    assert len(offs) == len(text) + 1
    # каждый символ очищенной строки отображается на тот же (или эквивалентный) символ оригинала
    for i, ch in enumerate(text):
        o = raw[offs[i]]
        assert ch == o or ch == " " or o in "\u00a0\n—" or ch == "й"


def test_clean_keeps_raw_intact() -> None:
    raw = "ул.\u00a0Абая\u200b 150"
    st = Clean()(ParseState(raw=raw))
    assert st.raw == raw


def test_orig_span_roundtrip() -> None:
    raw = "ул.\u00a0Абая\u200b\u200b 150"
    st = Tokenize()(Clean()(ParseState(raw=raw)))
    abai = next(t for t in st.tokens if t.text == "Абая")
    assert st.orig_slice(abai.start, abai.end) == "Абая"
    num = next(t for t in st.tokens if t.kind == "num")
    assert st.orig_slice(num.start, num.end) == "150"


# ---------------- tokenize ----------------
@pytest.mark.parametrize(
    "text,expected",
    [
        ("66квартал", [("66", "num"), ("квартал", "word")]),
        ("Назарбаева8", [("Назарбаева", "word"), ("8", "num")]),
        ("11дом", [("11", "num"), ("дом", "word")]),
        ("4подьезд", [("4", "num"), ("подьезд", "word")]),
        ("9этаж", [("9", "num"), ("этаж", "word")]),
        ("69квартира", [("69", "num"), ("квартира", "word")]),
        ("1/2", [("1/2", "num")]),
        ("55/6", [("55/6", "num")]),
        ("12а,", [("12а", "num"), (",", "sep")]),
        ("12 А,", [("12 А", "num"), (",", "sep")]),
        ("12-а", [("12-а", "num")]),
        ("кв70", [("кв", "word"), ("70", "num")]),
        ("ж/м Шанырак", [("ж/м", "word"), ("Шанырак", "word")]),
        ("пр-т Абая", [("пр-т", "word"), ("Абая", "word")]),
        ("150-23", [("150", "num"), ("-", "punct"), ("23", "num")]),
        ("12 а кв 5", [("12 а", "num"), ("кв", "word"), ("5", "num")]),
        ("12 а Абая", [("12", "num"), ("а", "word"), ("Абая", "word")]),
        ("12 а.", [("12", "num"), ("а", "word"), (".", "punct")]),
    ],
)
def test_tokenize(text: str, expected: list[tuple[str, str]]) -> None:
    assert [(t.text, t.kind) for t in tokenize(text)] == expected


def test_glued_flag() -> None:
    toks = tokenize("11дом 5 подъезд")
    assert toks[1].glued_left and not toks[2].glued_left


# ---------------- split_bilingual ----------------
@pytest.mark.parametrize(
    "raw,dropped",
    [
        ("город Алматы/Алматы қаласы, Мкр Аксай", "Алматы қаласы"),
        ("город Актобе/Ақтөбе қаласы", "Ақтөбе қаласы"),
        ("Ақтөбе облысы/Актюбинская область", "Ақтөбе облысы"),
        ("город Алматы/Алматы қаласы Мкр Аксай 3а", "Алматы қаласы"),
        ("Алматы/Almaty", "Almaty"),
    ],
)
def test_bilingual(raw: str, dropped: str) -> None:
    st = SplitBilingual()(Tokenize()(Clean()(ParseState(raw=raw))))
    got = " ".join(t.text for t in st.tokens if t.used_by == "kz_dup")
    assert got == dropped


def test_bilingual_keeps_fraction() -> None:
    st = SplitBilingual()(Tokenize()(Clean()(ParseState(raw="Абая 1/2"))))
    assert not any(t.used_by == "kz_dup" for t in st.tokens)
    assert any(t.text == "1/2" for t in st.tokens)


def test_bilingual_short_abbr_not_split() -> None:
    st = SplitBilingual()(Tokenize()(Clean()(ParseState(raw="ж/м Шанырак 5"))))
    assert not any(t.used_by == "kz_dup" for t in st.tokens)


# ---------------- admin ----------------
@pytest.mark.parametrize(
    "raw,province,city,district",
    [
        ("город Актобе/Ақтөбе қаласы", None, "Актобе", None),
        ("Актюбинская область, г. Актобе", "Актюбинская область", "Актобе", None),
        ("обл. Актюбинская", "Актюбинская область", None, None),
        ("Ақтөбе облысы", "Актюбинская область", None, None),
        ("ВКО, Усть-Каменогорск", "Восточно-Казахстанская область", "Усть-Каменогорск", None),
        ("Илийский район", None, None, "Илийский"),
        ("Іле ауданы", None, None, "Іле"),  # Q22: как в строке, без «ауданы»
        ("Турксибский р-н", None, None, "Турксибский"),
        ("г. Алматы, Алматы", None, "Алматы", None),
        ("Самал шағын ауданы", None, None, None),  # микрорайон, не район
        ("Алма-Ата", None, "Алма-Ата", None),  # Q22: русское написание как в строке
        ("Almaty", None, "Almaty", None),
    ],
)
def test_admin(raw: str, province: str | None, city: str | None, district: str | None) -> None:
    st = run_until(raw, "admin")
    assert (st.get("province"), st.get("city"), st.get("district")) == (province, city, district)


def test_admin_city_word_before_number_is_street() -> None:
    st = run_until("Туркестан 12", "admin")
    assert st.get("city") is None


# ---------------- details ----------------
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("кв 70", {"apartment": "70"}),
        ("кв.70", {"apartment": "70"}),
        ("kv12", {"apartment": "12"}),
        ("flat 191", {"apartment": "191"}),
        ("apt 5", {"apartment": "5"}),
        ("239 кв", {"apartment": "239"}),
        ("69квартира", {"apartment": "69"}),
        ("5 пәтер", {"apartment": "5"}),
        ("4подьезд", {"entrance": "4"}),
        ("подъезд 3", {"entrance": "3"}),
        ("подъез 3", {"entrance": "3"}),
        ("pod 2", {"entrance": "2"}),
        ("2 кіреберіс", {"entrance": "2"}),
        ("9этаж", {"floor": "9"}),
        ("эт. 4", {"floor": "4"}),
        ("etazh 4", {"floor": "4"}),
        ("3 қабат", {"floor": "3"}),
        ("дом 4", {"house": "4"}),
        ("д. 12/1", {"house": "12/1"}),
        ("11дом", {"house": "11"}),
        ("dom 7", {"house": "7"}),
        ("12 үй", {"house": "12"}),
        ("11дом 5 подьезд 239 кв", {"house": "11", "entrance": "5", "apartment": "239"}),
        ("дом 4, кв 12, подъезд 1, этаж 2", {"house": "4", "apartment": "12", "entrance": "1", "floor": "2"}),
        ("Туран 55/6 магазин береке 4подьезд 9этаж", {"entrance": "4", "floor": "9"}),
    ],
)
def test_details(raw: str, expected: dict[str, str]) -> None:
    st = run_until(raw, "details")
    got = {k: st.get(k) for k in ("house", "apartment", "entrance", "floor") if st.get(k)}
    assert got == expected


# ---------------- street ----------------
@pytest.mark.parametrize(
    "raw,stype,name,living",
    [
        ("ул. Абая 10", "улица", "Абая", None),
        ("пр. Абая 10", "проспект", "Абая", None),
        ("проспект Абая 10", "проспект", "Абая", None),
        ("Рыбинский переулок, дом 4", "переулок", "Рыбинский", None),
        ("Мкр Аксай 3а, 59", "микрорайон", "Аксай 3а", None),
        ("мкр 5, 12", "микрорайон", "5", None),
        ("Нурсити 2 микрорайон 11дом", "микрорайон", "Нурсити 2", None),
        ("66квартал 12дом", "квартал", "66", None),
        ("Самал шағын ауданы 5", "микрорайон", "Самал", None),
        ("мкр Самал-2, ул. Жолдасбекова 97", "улица", "Жолдасбекова", "Самал-2"),
        ("ЖК Томирис, ул. Сарайшык 5", "улица", "Сарайшык", "Томирис"),
        ("ж/м Шанырак 5", "жилой массив", "Шанырак 5", None),  # «Шанырак-5» есть в справочнике
        ("ж/м Улжан, 5", "жилой массив", "Улжан", None),
        ("Абай көшесі 10", "улица", "Абай", None),
        ("Кулманова 133", None, "Кулманова", None),
        ("у. Абая 5", "улица", "Абая", None),
        ("ш. Алматинское 5", "шоссе", "Алматинское", None),
        ("ул. Казахстан 70", "улица", "Казахстан", None),
        ("5 линия, 12", "линия", "5", None),
    ],
)
def test_street(raw: str, stype: str | None, name: str, living: str | None) -> None:
    st = run_until(raw, "street")
    assert (st.get("street_type"), st.get("street_name"), st.get("living_area")) == (stype, name, living)


def test_street_name_cut_from_original() -> None:
    st = run_until("ул.\u00a0Казыбек\u00a0би\u200b 12", "street")
    assert st.get("street_name") == "Казыбек би"


# ---------------- landmark ----------------
@pytest.mark.parametrize(
    "raw,landmark",
    [
        ("Туран 55/6 магазин береке 4подьезд", "магазин береке"),
        ("Qazpost Солнечный", "Qazpost Солнечный"),
        ("напротив школы 25, ул. Ленина 3", "напротив школы 25"),
        ("возле ТЦ Мега, Абая 1", "возле ТЦ Мега"),
        ("ул. Ленина 3, рядом с аптекой", "рядом с аптекой"),
        ("ул. Ленина 3", None),
    ],
)
def test_landmark(raw: str, landmark: str | None) -> None:
    assert run_until(raw, "landmark").get("landmark") == landmark


# ---------------- numbers ----------------
@pytest.mark.parametrize(
    "raw,house,apartment",
    [
        ("Абая 12, 45", "12", "45"),
        ("Абая 150-23", "150", "23"),
        ("Абая 1/2", "1/2", None),
        ("050000, Абая 5", "5", None),  # индекс не дом
        ("Абая 5 87771234567", "5", None),  # телефон не квартира
    ],
)
def test_numbers(raw: str, house: str | None, apartment: str | None) -> None:
    st = run_until(raw, "numbers")
    assert (st.get("house"), st.get("apartment")) == (house, apartment)


# ---------------- reference ----------------
def test_reference_never_overwrites_string_value() -> None:
    st = run_until("Турксибский район, г. Алматы, мкр Аксай 3а, 5", "reference")
    assert st.fields["district"].source == "string"
    assert st.get("district") == "Турксибский"


def test_reference_sources_marked() -> None:
    st = run_until("г. Алматы, Мкр Аксай 3а, 59", "reference")
    assert st.fields["district"].source.startswith("reference:")
    assert st.get("district") == "Ауэзовский"
    assert st.fields["city"].source == "string"


def test_reference_province_from_city() -> None:
    st = run_until("г. Караганда, ул. Ерубаева 5", "reference")
    assert st.get("province") == "Карагандинская область"
    assert st.fields["province"].source.startswith("reference:")


def test_reference_district_to_city() -> None:
    st = run_until("Медеуский район, ул. Абая 5", "reference")
    assert (st.get("city"), st.get("province")) == ("Алматы", "Алматы")


# ---------------- confidence ----------------
def test_confidence_orders_quality() -> None:
    full = run_until("г. Алматы, ул. Абая 10, кв 5", "confidence").confidence
    partial = run_until("Абая 10 зеленый забор синяя калитка", "confidence").confidence
    garbage = run_until("???", "confidence").confidence
    assert full > partial > garbage
    assert 0 <= garbage <= 0.1
    assert full >= 0.8


def test_confidence_trace_has_parts() -> None:
    st = run_until("ул. Абая 10", "confidence")
    assert "parts" in st.trace[-1].changes


def test_confidence_parts_sum_to_result() -> None:
    for raw in ("г. Алматы, ул. Абая 10, кв 5", "Абая 10 зеленый забор синяя калитка", "Fkvfns ek f,fz 150 rd 5"):
        st = run_until(raw, "confidence")
        assert sum(st.trace[-1].changes["parts"].values()) == pytest.approx(st.confidence, abs=0.01)


def test_confidence_penalty_not_swallowed_by_cap() -> None:
    # логистическая модель: флаг с отрицательным весом снижает итог и у самой уверенной записи
    from jana_address.pipeline.confidence import Confidence
    from jana_address.rules_loader import get_rules

    rules = get_rules()
    neg = next(k for k, v in rules.confidence["flags"].items() if v < 0)

    def unclipped(flags: set[str]) -> float:
        st = run_until("г. Алматы, ул. Абая 10, кв 5", "confidence")
        st.trace.pop()
        st.flags |= flags
        parts = Confidence(rules)(st).trace[-1].changes["parts"]
        return float(sum(v for k, v in parts.items() if k != "cap"))

    assert unclipped({neg}) < unclipped(set())


def test_old_confidence_yaml_rejected(tmp_path: Path) -> None:
    # старый линейный формат (base/bonus) молча дал бы всем ~0.5: падаем при загрузке
    import shutil

    from jana_address import config
    from jana_address.rules_loader import load_rules

    rules_dir = tmp_path / "rules"
    shutil.copytree(config.RULES_DIR, rules_dir)
    (rules_dir / "confidence.yaml").write_text("base: 0.3\nconsumed_ratio: 0.4\nbonus: {}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="intercept"):
        load_rules(rules_dir)


# ---------- parts: организации и корпуса; layout: английская раскладка ----------
def test_tokenize_splits_glued_building() -> None:
    from jana_address.pipeline.tokenize import tokenize

    assert [(t.text, t.kind) for t in tokenize("11к2")] == [("11", "num"), ("к", "word"), ("2", "num")]
    assert [(t.text, t.kind) for t in tokenize("12к")] == [("12к", "num")]  # литера без номера корпуса


def _run_until(raw: str, last: str) -> object:
    from jana_address.pipeline.runner import Pipeline

    p = Pipeline(tagger_mode="off")
    p.steps = p.steps[: [s.name for s in p.steps].index(last) + 1]
    return p.run(raw)


def test_parts_consumes_org_and_building() -> None:
    state = _run_until("ТОО «Сапа Трейд», ул. Абая 5 корп 2, АО Казахтелеком", "parts")
    used = {t.text: t.used_by for t in state.tokens}  # type: ignore[attr-defined]
    assert used["Сапа"] == used["Трейд"] == used["Казахтелеком"] == "noise:org"
    assert used["корп"] == used["2"] == "building" and used["Абая"] is None
    assert "building_part_ignored" in state.flags  # type: ignore[attr-defined]


def test_parts_keeps_caps_street_and_lone_k() -> None:
    state = _run_until("УЛ. АК ЖОЛ 5, к Абая", "parts")
    assert all(t.used_by is None for t in state.tokens if t.kind == "word")  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("raw", "fixed"),
    [("Fkvfns ek f,fz 150", "Алматы ул абая 150"), ("Almaty, ul. Abaya 150", None), ("Hello world 5", None),
     ("ул. Абая 5", None)],
)  # fmt: skip
def test_layout(raw: str, fixed: str | None) -> None:
    from jana_address.pipeline.layout import Layout

    assert Layout().fix(raw) == fixed


# ---------------- места без тестов до аудита ----------------
def test_leftover_takes_city_as_written() -> None:
    """Сегмент без маркера, найденный в справочнике как город: значение как в строке (Q22), источник string."""
    st = run_until("Илийский район, боралдай, ул. Ленина 1/2", "leftover")
    assert st.fields["city"].value == "боралдай"
    assert st.fields["city"].source == "string"


def test_rural_okrug_is_consumed_without_field() -> None:
    st = run_until("Илийский район, Байсеркенский СО, с. Байсерке, ул. Абая 5", "admin")
    okrug = [t.text.lower() for t in st.tokens if t.used_by == "admin:okrug"]
    assert okrug == ["байсеркенский", "со"]
    assert st.fields["city"].value == "Байсерке"


def test_historical_province_is_not_a_conflict() -> None:
    """Переделы областей: «ВКО, г. Семей» после 2022 года не конфликт, confidence за это не штрафуется."""
    st = run_until("Восточно-Казахстанская область, г. Семей, ул. Абая 5", "reference")
    assert "city_province_conflict" not in st.flags


def test_yaml_bool_in_list_is_rejected(tmp_path: Path) -> None:
    """Голое no/yes в списке YAML читается как bool: загрузчик должен остановиться, а не молча взять False."""
    from jana_address.rules_loader import _read

    bad = tmp_path / "bad.yaml"
    bad.write_text("noise: [адрес, no, rk]\n", encoding="utf-8")
    with pytest.raises(ValueError, match="кавычки"):
        _read(bad)


def test_latin_aliases_do_not_shadow_cyrillic_abbreviations() -> None:
    """«st»/«str» латиницей это улица, но кириллические «ст» и «стр» остаются станцией и строением."""
    from jana_address.rules_loader import get_rules

    r = get_rules()
    assert r.street_types.get("st") is not None
    assert "стр" in r.building_part
    assert r.street_types.get("стр") is None or "стр" in r.building_part
    st_type = r.street_types.get("ст")
    assert st_type is None or st_type.canonical != "улица"


def test_confidence_terms_explain_the_score() -> None:
    """Слагаемые в trace объясняют итог без остатка: база + баллы = logit, sigmoid(logit) в границах = confidence."""
    import math

    from jana_address import engine

    for raw in ["город Алматы/Алматы қаласы, Мкр Аксай 3а, 59, кв 70", "xyz qwe 17", "Туран 55/6 магазин береке"]:
        r = engine.parse_one({"id": "c", "raw_address": raw}, explain=True)
        c = next(t for t in r["trace"] if t["step"] == "confidence")["changes"]
        z = c["intercept"] + sum(t["points"] for t in c["terms"])
        assert abs(z - c["logit"]) < 0.01, raw
        lo, hi = c["bounds"]
        p = min(hi, max(lo, 1 / (1 + math.exp(-z))))
        assert abs(p - r["confidence"]) < 0.002, raw
        assert all(abs(t["w"] * t["x"] - t["points"]) < 0.002 for t in c["terms"])
