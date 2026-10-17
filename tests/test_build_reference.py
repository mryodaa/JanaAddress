"""Сборка справочника из OSM на синтетическом мини-фрагменте и восстановление полей по нему.

Нужны зависимости сборки (pip install -e .[build]); в рантайм-образе их нет, тогда тест пропускается.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("osmium")
pytest.importorskip("shapely")

from jana_address.pipeline.runner import Pipeline
from jana_address.reference.store import Store
from jana_address.rules_loader import get_rules

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Path:
    # импорт здесь, а не наверху: без osmium/shapely модуль должен пропускаться, а не падать
    from scripts.build_reference import assign_districts, build_sqlite, osm_extract

    d = tmp_path_factory.mktemp("ref")
    assert osm_extract.main([str(FIX / "mini.osm"), "--out", str(d / "raw.jsonl")]) == 0
    assert assign_districts.main(["--raw", str(d / "raw.jsonl"), "--out", str(d / "assigned")]) == 0
    assert build_sqlite.main(["--osm", str(d / "assigned"), "--out", str(d / "ref.sqlite")]) == 0
    return d


@pytest.fixture(scope="module")
def store(built: Path) -> Store:
    return Store(built / "ref.sqlite")


@pytest.fixture(scope="module")
def meta(built: Path) -> dict[str, Any]:
    return json.loads((built / "assigned" / "meta.json").read_text(encoding="utf-8"))  # type: ignore[no-any-return]


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
    assert st["houses"] == 8
    assert st["counts"]["street"] == 8
    assert "osm" in st["sources"]


def test_district_by_house_and_type_from_reference(store: Store) -> None:
    s = pipeline(store).run("г. Алматы, Курильская 9")
    assert s.get("street_name") == "Курильская"
    assert s.get("street_type") == "улица"
    assert s.fields["street_type"].source == "reference:osm:street"
    assert s.get("district") == "Алатауский"
    assert s.fields["district"].source == "reference:osm:house"


def test_street_district_and_kazakh_alias(store: Store) -> None:
    s = pipeline(store).run("Алматы, Абай көшесі 10")
    assert s.get("street_name") == "Абай"  # в ответ идёт написание из строки
    assert s.get("district") == "Медеуский"


def test_city_restored_from_unique_street(store: Store) -> None:
    s = pipeline(store).run("Курильская 9")
    assert s.get("city") == "Алматы"
    assert s.fields["city"].source.startswith("reference:")


# ---------- привязки, посчитанные при сборке ----------
def test_levels_detected_from_data(meta: dict[str, Any]) -> None:
    assert meta["levels"]["province"] == 4
    assert meta["levels"]["oblast_district"] == 6
    assert meta["city_units"] == [{"city": "Алматы", "province": "Алматы", "level": 6, "n": 2, "coverage": 1.0}]


def test_settlement_in_oblast_district(meta: dict[str, Any]) -> None:
    by = {(c["name"], c["district"]): c for c in meta["cities"]}
    boraldai = by[("Боралдай", "Илийский")]
    assert boraldai["province"] == "Алматинская область"
    assert boraldai["district_method"] == "polygon"
    # село в полукилометре за границей полигона района: ближайший район
    assert by[("Ащибулак", "Илийский")]["district_method"] == "near"
    # одноимённые сёла одной области в разных районах не сливаются
    assert ("Акжар", "Илийский") in by and ("Акжар", "Талгарский") in by


def test_same_name_villages_are_separate(store: Store) -> None:
    found = store.lookup("Акжар", ("city",))
    names = {store.get("district", e.district_id).name for e in found}  # type: ignore[union-attr]
    assert names == {"Илийский", "Талгарский"}


def test_house_in_living_area_polygon(store: Store) -> None:
    s = pipeline(store).run("г. Алматы, пр. Достык 5")
    assert s.get("district") == "Медеуский"
    # дом и в мкр Самал-3, и в ЖК внутри него: мкр важнее ЖК
    assert s.get("living_area") == "Самал-3"
    assert s.fields["living_area"].source == "reference:osm:house"


def test_house_living_area_by_nearest_point(store: Store) -> None:
    s = pipeline(store).run("г. Алматы, ул. Жамбыла 7")
    assert s.get("living_area") == "Самал-2"
    assert s.fields["living_area"].source == "reference:osm:point"
    assert "living_area_by_point" in s.flags


def test_street_in_two_districts_takes_best_with_flag(store: Store) -> None:
    s = pipeline(store).run("г. Алматы, ул. Сатпаева 100")  # дома 100 в справочнике нет
    assert s.get("district") == "Алатауский"  # 2 дома из 3
    assert s.fields["district"].source == "reference:osm:street"
    assert "district_ambiguous" in s.flags


def test_old_street_name(store: Store) -> None:
    s = pipeline(store).run("г. Алматы, ул. Ленина 10")  # бывшая улица Абая
    assert s.get("street_name") == "Ленина"
    assert s.get("district") == "Медеуский"
    assert s.fields["district"].source == "reference:osm:house"


def test_street_type_by_dominant_type(store: Store) -> None:
    s = pipeline(store).run("г. Алматы, Жамбыла 7")  # есть улица и короткий переулок Жамбыла
    assert s.get("street_type") == "улица"
    assert "street_type_dominant" in s.flags


def test_village_district_from_polygon(store: Store) -> None:
    s = pipeline(store).run("с. Ынтымак, ул. Райымбека 12")
    assert s.get("province") == "Алматинская область"
    assert s.get("district") == "Илийский"
    assert s.fields["district"].source == "reference:osm:polygon"


def test_district_hint_from_landmark(store: Store) -> None:
    s = pipeline(store).run("г. Алматы, напротив Magnum")
    assert s.get("district") == "Медеуский"
    assert s.fields["district"].source == "reference:osm:poi"
    assert "district_by_landmark" in s.flags


def test_pois_lazy_lookup(store: Store) -> None:
    city = store.lookup("Алматы", ("city",))[0]
    assert [p.kind for p in store.pois("магнум", city.id)] == ["shop:supermarket"]  # транслит


def test_survey_report(tmp_path: Path) -> None:
    from scripts.build_reference import osm_survey

    out = tmp_path / "survey.md"
    assert osm_survey.main([str(FIX / "mini.osm"), "--out", str(out), "--idx-dir", str(tmp_path)]) == 0
    text = out.read_text(encoding="utf-8")
    assert "районы областей: admin_level **6**" in text
    assert "| Алматы | 4 | 6 | 2 | 100% |" in text
