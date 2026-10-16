"""Сборка справочника из OSM на синтетическом мини-фрагменте и восстановление полей по нему.

Нужны зависимости сборки (pip install -e .[build]); в рантайм-образе их нет, тогда тест пропускается.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("osmium")
pytest.importorskip("shapely")

from jana_address.pipeline.runner import Pipeline
from jana_address.reference.store import Store
from jana_address.rules_loader import get_rules

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Store:
    # импорт здесь, а не наверху: без osmium/shapely модуль должен пропускаться, а не падать
    from scripts.build_reference import assign_districts, build_sqlite, osm_extract

    d = tmp_path_factory.mktemp("ref")
    assert osm_extract.main([str(FIX / "mini.osm"), "--out", str(d / "raw.jsonl")]) == 0
    assert assign_districts.main(["--raw", str(d / "raw.jsonl"), "--out", str(d / "assigned.json")]) == 0
    assert build_sqlite.main(["--osm", str(d / "assigned.json"), "--out", str(d / "ref.sqlite")]) == 0
    return Store(d / "ref.sqlite")


def pipeline(store: Store) -> Pipeline:
    from jana_address.pipeline import (
        admin,
        bilingual,
        clean,
        confidence,
        details,
        landmark,
        leftover,
        numbers,
        reference_step,
        street,
        tokenize,
    )

    rules = get_rules()
    return Pipeline(
        [
            clean.Clean(),
            tokenize.Tokenize(),
            bilingual.SplitBilingual(),
            admin.Admin(store, rules),
            details.Details(rules),
            street.Street(store, rules),
            landmark.Landmark(rules),
            numbers.Numbers(rules),
            leftover.Leftover(store),
            reference_step.Reference(store),
            confidence.Confidence(rules),
        ]
    )


def test_osm_entities_loaded(store: Store) -> None:
    st = store.stats()
    assert st["houses"] == 2
    assert st["counts"]["street"] == 2
    assert "osm" in st["sources"]


def test_district_by_house_and_type_from_reference(store: Store) -> None:
    s = pipeline(store).run("г. Алматы, Курильская 9")
    assert s.get("street_name") == "Курильская"
    assert s.get("street_type") == "улица"
    assert s.fields["street_type"].source == "reference:osm"
    assert s.get("district") == "Алатауский"


def test_street_district_and_kazakh_alias(store: Store) -> None:
    s = pipeline(store).run("Алматы, Абай көшесі 10")
    assert s.get("street_name") == "Абай"  # в ответ идёт написание из строки
    assert s.get("district") == "Медеуский"


def test_city_restored_from_unique_street(store: Store) -> None:
    s = pipeline(store).run("Курильская 9")
    assert s.get("city") == "Алматы"
    assert s.fields["city"].source.startswith("reference:")
