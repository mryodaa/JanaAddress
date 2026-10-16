"""Скрипт метрики сам должен считать ровно по ТЗ, иначе вся настройка правил идёт вслепую."""

from __future__ import annotations

import math

from scripts.eval import evaluate, norm


def rec(**kw: object) -> dict[str, object]:
    base: dict[str, object] = {"id": "1", "raw_address": "Алматы, ул. Абая 1/2, кв 5"}
    base.update(kw)
    return base


def test_norm_rules() -> None:
    assert norm("  Казыбек   Би. ") == "казыбек би"
    assert norm("1/2") == "12"  # пунктуация удаляется буквально
    assert norm(None) == ""
    assert norm("Абая") != norm("Абаю")  # падежи не прощаются


def test_exact_match_full_score() -> None:
    g = [rec(province="Алматы", city="Алматы", street_name="Абая", house="1/2", apartment="5")]
    r = evaluate(g, g)
    assert math.isclose(r["score"], 1.0)
    assert r["fields"]["house"]["total"] == 1


def test_null_vs_value_and_exclusions() -> None:
    gold = [rec(street_name="Абая", house="1/2", apartment=None)]
    pred = [rec(street_name="абая", house=None, apartment="7")]
    r = evaluate(pred, gold)
    assert r["fields"]["street_name"]["correct"] == 1  # регистр не важен
    assert r["fields"]["house"]["correct"] == 0 and r["fields"]["house"]["total"] == 1
    assert r["fields"]["apartment"]["total"] == 0 and r["fields"]["apartment"]["fp"] == 1
    strict = evaluate(pred, gold, strict_fp=True)
    assert strict["fields"]["apartment"]["total"] == 1


def test_reference_fields_only_when_in_string() -> None:
    gold = [
        rec(id="1", raw_address="Ауэзовский район, Абая 1", district="Ауэзовский"),
        rec(id="2", raw_address="Абая 1", district="Ауэзовский"),
        rec(id="3", raw_address="Ауэзовский р-н", district="Ауэзовский", _from_reference=["district"]),
    ]
    pred = [rec(id="1", district=None), rec(id="2", district="Бостандыкский"), rec(id="3", district=None)]
    r = evaluate(pred, gold)
    assert r["fields"]["district"]["total"] == 1  # только запись 1
    assert r["fields"]["district"]["correct"] == 0


def test_weights() -> None:
    gold = [rec(province="Алматы", apartment="5", district=None)]
    pred = [rec(province="Алматы", apartment="6")]
    r = evaluate(pred, gold)
    # справочная группа пуста -> веса 0.60 и 0.25 перенормируются
    assert math.isclose(r["score"], 0.60 / 0.85)
