"""Арбитр правил и теггера на поддельной разметке (tests/tagger_fakes.py): решения не зависят от обучения."""

from __future__ import annotations

from tests.tagger_fakes import FakeTagger, find, pipeline_with

from jana_address.pipeline.runner import parse_records


def run(raw: str, spans: list[tuple[int, int, str, float]], mode: str = "on") -> dict[str, object]:
    out = parse_records(pipeline_with(FakeTagger({raw: spans}), mode), [{"id": 1, "raw_address": raw}], explain=True)
    return out[0]


def test_unmarked_settlement_before_street() -> None:
    """Правила склеили село с улицей; модель разделила, справочник подтвердил улицу в этом селе."""
    raw = "Бесагаш Айтеке би, 68 кв14"
    out = run(raw, [find(raw, "Бесагаш", "CITY"), find(raw, "Айтеке би", "STREET_NAME"), find(raw, "68", "HOUSE")])
    assert out["city"] == "Бесагаш" and out["street_name"] == "Айтеке би" and out["house"] == "68"
    assert out["province"] is not None  # область того из одноимённых сёл, где есть эта улица
    assert out["fields"]["street_name"]["source"] == "string"  # type: ignore[index]


def test_city_at_end_without_marker() -> None:
    raw = "ул Кенесары Касымова 139 Ерейментау"
    spans = [find(raw, "ул", "STREET_TYPE"), find(raw, "Кенесары Касымова", "STREET_NAME"), find(raw, "139", "HOUSE")]
    out = run(raw, [*spans, find(raw, "Ерейментау", "CITY")])
    assert out["city"] == "Ерейментау" and out["province"] == "Акмолинская область"
    assert out["street_name"] == "Кенесары Касымова" and out["house"] == "139"


def test_low_probability_model_only_field_stays_null() -> None:
    raw = "ул Кенесары Касымова 139 Ерейментау"
    out = run(raw, [find(raw, "Кенесары Касымова", "STREET_NAME"), find(raw, "Ерейментау", "CITY", p=0.5)])
    assert out["city"] is None


def test_overlap_resolved_jointly() -> None:
    """Модель называет этажом то, что правила взяли квартирой: один спан не может быть двумя полями."""
    raw = "г. Алматы, ул. Абая 150, 99"
    out = run(raw, [find(raw, "Абая", "STREET_NAME"), find(raw, "150", "HOUSE"), find(raw, "99", "FLOOR", p=0.95)])
    assert out["apartment"] == "99" and out["floor"] is None


def test_grammar_rejects_implausible_floor() -> None:
    raw = "г. Алматы, ул. Абая 150, этаж 99"
    out = run(raw, [find(raw, "Абая", "STREET_NAME"), find(raw, "150", "HOUSE"), find(raw, "99", "FLOOR", p=0.99)])
    model = out["model"]["fields"]["floor"]["model"]  # type: ignore[index]
    assert "grammar_bad" in model["checks"]


def test_agreement_keeps_rules_values() -> None:
    raw = "г. Алматы, ул. Абая 150, кв 5"
    spans = [find(raw, "Алматы", "CITY"), find(raw, "Абая", "STREET_NAME"), find(raw, "150", "HOUSE"),
             (len(raw) - 1, len(raw), "APARTMENT", 0.97)]  # fmt: skip
    base = run(raw, [], mode="off")
    out = run(raw, spans)
    for f in ("city", "street_name", "house", "apartment"):
        assert out[f] == base[f]
        assert out["model"]["fields"][f]["decision"] == "agree"  # type: ignore[index]


def test_string_values_cut_from_raw() -> None:
    """Значение модели это срез исходной строки (регистр и опечатки как есть), область каноном через справочник."""
    raw = "АЛМАТЫ, абая 150"
    out = run(raw, [find(raw, "АЛМАТЫ", "CITY"), find(raw, "абая", "STREET_NAME"), find(raw, "150", "HOUSE")], "only")
    assert out["street_name"] == "абая" and out["city"] == "АЛМАТЫ" and out["house"] == "150"


def test_only_mode_drops_rules_fields() -> None:
    raw = "г. Алматы, ул. Абая 150, кв 5"
    out = run(raw, [find(raw, "Абая", "STREET_NAME")], "only")
    assert out["street_name"] == "Абая" and out["house"] is None and out["apartment"] is None


def test_model_span_cannot_cut_number_but_can_split_glued_word() -> None:
    """Номер неделим («Абая-1|2»); склейку слов, которую не разделил токенизатор, модель делить может."""
    raw = "ул. Абая-12 кв 5"
    out = run(raw, [find(raw, "Абая-1", "STREET_NAME"), (9, 10, "HOUSE", 0.99)], "only")
    assert out["street_name"] is None and out["house"] is None
    raw = "улицаАбая 5"
    out = run(
        raw, [find(raw, "улица", "STREET_TYPE"), find(raw, "Абая", "STREET_NAME"), find(raw, "5", "HOUSE")], "only"
    )
    assert out["street_name"] == "Абая" and out["street_type"] == "улица"
