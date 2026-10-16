"""Сквозные кейсы: обязательные из ТЗ (раздел 11) и типичные варианты из реальных адресов.

Проверяются только перечисленные поля. Ожидания для справочных полей (district/province из справочника)
отмечены комментарием: их метрика не считает, но на защите они показываются.
"""

from __future__ import annotations

from typing import Any

import pytest

from jana_address import engine

N = None
CASES: list[tuple[str, dict[str, Any]]] = [
    # --- обязательные кейсы ТЗ ---
    ("66квартал 12дом 69квартира", dict(street_type="квартал", street_name="66", house="12", apartment="69")),
    ("Ул .Курильская 9 кв 1", dict(street_type="улица", street_name="Курильская", house="9", apartment="1")),
    (
        "Туран 55/6 магазин береке 4подьезд 9этаж",
        dict(street_name="Туран", house="55/6", entrance="4", floor="9", landmark="магазин береке"),
    ),
    (
        "город Алматы/Алматы қаласы, Мкр Аксай 3а, 59, кв 70",
        dict(
            province="Алматы",
            city="Алматы",
            district="Ауэзовский",
            living_area=N,
            street_type="микрорайон",
            street_name="Аксай 3а",
            house="59",
            apartment="70",
            entrance=N,
            floor=N,
            landmark=N,
        ),
    ),
    (
        "Нурсити 2 микрорайон 11дом 5 подьезд 239 кв",
        dict(street_type="микрорайон", street_name="Нурсити 2", house="11", entrance="5", apartment="239"),
    ),
    (
        "Турксибский район, Рыбинский переулок, дом 4",
        dict(
            district="Турксибский",
            street_type="переулок",
            street_name="Рыбинский",
            house="4",
            city="Алматы",
            province="Алматы",
        ),  # город и область из справочника по району
    ),
    (
        "город Актобе/Ақтөбе қаласы, проспект Абилкайыр хана 52, кв 14",
        dict(
            province="Актюбинская область",
            city="Актобе",
            street_type="проспект",
            street_name="Абилкайыр хана",
            house="52",
            apartment="14",
        ),
    ),
    ("Кулманова 133", dict(street_name="Кулманова", house="133")),
    ("жуалы 19", dict(street_name="жуалы", house="19")),
    ("ул Абая 10 flat 191", dict(street_name="Абая", house="10", apartment="191")),
    ("Сатпаева 5 kv 12", dict(street_name="Сатпаева", house="5", apartment="12")),
    (
        "ул.\u00a0Абая\u200b 150, кв\u200b 23",
        dict(street_type="улица", street_name="Абая", house="150", apartment="23"),
    ),
    (
        "Илийский район, Боралдай, ул. Ленина 1/2",
        dict(
            province="Алматинская область",
            city="Боралдай",
            district="Илийский",
            street_type="улица",
            street_name="Ленина",
            house="1/2",
        ),
    ),
    # --- слитное написание, дроби, литеры ---
    ("Назарбаева8 кв 5", dict(street_name="Назарбаева", house="8", apartment="5")),
    ("ул Абая 12 А, кв 5", dict(street_name="Абая", house="12 А", apartment="5")),
    ("ул Абая 12-а", dict(street_name="Абая", house="12-а")),
    ("ул. Ерубаева 33/1 кв 7", dict(street_name="Ерубаева", house="33/1", apartment="7")),
    ("Абая 150-23", dict(street_name="Абая", house="150", apartment="23")),
    ("кв 5 д 12 ул Абая", dict(street_name="Абая", house="12", apartment="5")),
    # --- латиница ---
    ("ul Abaya 10 kv 5", dict(street_type="улица", street_name="Abaya", house="10", apartment="5")),
    ("mkr Aksay 4, dom 12, kv 7", dict(street_type="микрорайон", street_name="Aksay 4", house="12", apartment="7")),
    ("Abaya 10 apt 3 pod 2 etazh 4", dict(street_name="Abaya", house="10", apartment="3", entrance="2", floor="4")),
    # --- казахские формы ---
    ("Абай көшесі 10, 5 пәтер", dict(street_type="улица", street_name="Абай", house="10", apartment="5")),
    (
        "Ақтөбе облысы, Ақтөбе қаласы, Санкібай батыр даңғылы 1",
        dict(
            province="Актюбинская область",
            city="Актобе",
            street_type="проспект",
            street_name="Санкібай батыр",
            house="1",
        ),
    ),
    ("Алматы қ., Абай даңғылы, 52", dict(city="Алматы", street_type="проспект", street_name="Абай", house="52")),
    # --- города, области, районы ---
    (
        "г. Астана, пр. Кабанбай батыра 53, кв. 12",
        dict(
            province="Астана",
            city="Астана",
            street_type="проспект",
            street_name="Кабанбай батыра",
            house="53",
            apartment="12",
        ),
    ),
    (
        "Алматы, ул.Толе би 123а, кв.45, подъезд 3, этаж 5",
        dict(
            city="Алматы",
            street_type="улица",
            street_name="Толе би",
            house="123а",
            apartment="45",
            entrance="3",
            floor="5",
        ),
    ),
    (
        "Шымкент, мкр Нурсат, д 15, кв 30",
        dict(
            city="Шымкент",
            province="Шымкент",
            street_type="микрорайон",
            street_name="Нурсат",
            house="15",
            apartment="30",
        ),
    ),
    (
        "Алматинская обл., Карасайский р-н, г. Каскелен, ул. Абылай хана 5",
        dict(
            province="Алматинская область",
            district="Карасайский",
            city="Каскелен",
            street_type="улица",
            street_name="Абылай хана",
            house="5",
        ),
    ),
    (
        "Алматы, мкр Самал-2, ул. Жолдасбекова 97, кв 10",
        dict(
            living_area="Самал-2",
            street_type="улица",
            street_name="Жолдасбекова",
            house="97",
            apartment="10",
            city="Алматы",
            district="Медеуский",
        ),  # район из справочника по микрорайону в найденном городе
    ),
    (
        "ЖК Томирис, ул. Сарайшык 5, кв 12",
        dict(living_area="Томирис", street_type="улица", street_name="Сарайшык", house="5", apartment="12"),
    ),
    (
        "Алматы, Бостандыкский район, ул. Тимирязева 42",
        dict(city="Алматы", district="Бостандыкский", street_name="Тимирязева", house="42"),
    ),
    (
        "г.Шымкент, Абайский р-н, ул. Байтурсынова 20",
        dict(city="Шымкент", district="Абайский", street_name="Байтурсынова", house="20"),
    ),
    ("Алматы Абая 1", dict(city="Алматы", street_name="Абая", house="1")),
    ("Алматы, Алматы, ул. Абая, 1", dict(city="Алматы", street_name="Абая", house="1")),
    ("г Алматы ул Абая 1", dict(city="Алматы", street_name="Абая", house="1")),
    (
        "Нур-Султан, Есильский район, ул. Сыганак 10",
        dict(city="Астана", district="Есильский", street_name="Сыганак", house="10"),
    ),
    (
        "ВКО, г. Усть-Каменогорск, ул. Казахстан 70",
        dict(province="Восточно-Казахстанская область", city="Усть-Каменогорск", street_name="Казахстан", house="70"),
    ),
    ("РК, г. Алматы, ул. Абая 1", dict(city="Алматы", street_name="Абая", house="1")),
    (
        "с. Узынагаш, ул. Абая 1",
        dict(city="Узынагаш", province="Алматинская область", district="Жамбылский", street_name="Абая", house="1"),
    ),
    (
        "Мангистауская область, Актау, 12 мкр, 5 дом, 34 кв",
        dict(
            province="Мангистауская область",
            city="Актау",
            street_type="микрорайон",
            street_name="12",
            house="5",
            apartment="34",
        ),
    ),
    (
        "Алматы, мкр. Аксай-4, д. 87, кв. 15",
        dict(street_type="микрорайон", street_name="Аксай-4", house="87", apartment="15", district="Ауэзовский"),
    ),
    ("пос. Боралдай, 5 линия, 12", dict(city="Боралдай", street_type="линия", street_name="5", house="12")),
    # «Самал-2» есть и в Алматы, и в Шымкенте: без города район не угадываем (null лучше неверного)
    (
        "мкр Самал-2, ул. Жолдасбекова 97",
        dict(living_area="Самал-2", street_name="Жолдасбекова", house="97", district=N),
    ),
    # --- ориентиры ---
    ("Qazpost Солнечный", dict(landmark="Qazpost Солнечный", street_name=N, house=N)),
    ("напротив школы 25, ул. Ленина 3", dict(landmark="напротив школы 25", street_name="Ленина", house="3")),
    (
        "пр-т Райымбека 200/1, 2 подъезд, 3 этаж",
        dict(street_type="проспект", street_name="Райымбека", house="200/1", entrance="2", floor="3"),
    ),
    # --- регистр не нормализуется ---
    ("казибек би 5", dict(street_name="казибек би", house="5")),
    # --- мусор ---
    ("", dict(street_name=N, house=N)),
    (",,, ??? --- ...", dict(street_name=N, house=N, city=N)),
    ("\u200b\u200b\u00a0", dict(street_name=N, house=N)),
]


# Типичные форматы доставочных адресов: районы, пригороды, ЖК, офисы, индексы, смешанная ориентация маркеров
CASES += [
    (
        "г.Алматы, Ауэзовский район, мкр.Жетысу-2, д.73, кв.15",
        dict(
            city="Алматы",
            district="Ауэзовский",
            street_type="микрорайон",
            street_name="Жетысу-2",
            house="73",
            apartment="15",
        ),
    ),
    (
        "Астана, Есильский район, пр. Туран 37/9, кв 120",
        dict(
            city="Астана",
            district="Есильский",
            street_type="проспект",
            street_name="Туран",
            house="37/9",
            apartment="120",
        ),
    ),
    (
        "Алматинская область, Талгарский район, с.Бесагаш, ул.Шоссейная 12",
        dict(
            province="Алматинская область", district="Талгарский", city="Бесагаш", street_name="Шоссейная", house="12"
        ),
    ),
    ("ул. Жандосова 98, оф. 305", dict(street_name="Жандосова", house="98", apartment="305")),
    ("мкр. 8, д. 4а, кв. 20", dict(street_type="микрорайон", street_name="8", house="4а", apartment="20")),
    (
        "Актау 14 мкр 5 дом 34 кв",
        dict(city="Актау", street_type="микрорайон", street_name="14", house="5", apartment="34"),
    ),
    (
        "Алматы, Наурызбайский район, мкр. Шугыла, ул. Жуалы 19",
        dict(city="Алматы", district="Наурызбайский", living_area="Шугыла", street_name="Жуалы", house="19"),
    ),
    (
        "Нур-Султан, ЖК Хайвил, Кабанбай батыра 58Б, кв. 120",
        dict(city="Астана", living_area="Хайвил", street_name="Кабанбай батыра", house="58Б", apartment="120"),
    ),
    ("Uralsk, Abaya 12-34", dict(city="Уральск", street_name="Abaya", house="12", apartment="34")),
    ("050000 Алматы ул. Абая 1", dict(city="Алматы", street_name="Абая", house="1")),
    (
        "Алматы, проспект Аль-Фараби, 77/8, БЦ Нурлы Тау, офис 1205",
        dict(
            city="Алматы",
            street_type="проспект",
            street_name="Аль-Фараби",
            house="77/8",
            apartment="1205",
            landmark="БЦ Нурлы Тау",
        ),
    ),
    ("дом 5 кв 3 ул Сейфуллина г Алматы", dict(city="Алматы", street_name="Сейфуллина", house="5", apartment="3")),
    ("Алматы г., ул. Абая 10", dict(city="Алматы", street_name="Абая", house="10")),
    ("АЛМАТЫ, УЛ. АБАЯ 10", dict(city="Алматы", street_type="улица", street_name="АБАЯ", house="10")),
    ("ул.Абая,д.10,кв.5", dict(street_name="Абая", house="10", apartment="5")),
    ("мкр Айнабулак-3, 105-34", dict(street_type="микрорайон", street_name="Айнабулак-3", house="105", apartment="34")),
    ("Шанырак-2 мкр, ул. Жанкожа батыра 202", dict(living_area="Шанырак-2", street_name="Жанкожа батыра", house="202")),
    ("с.Отеген батыр, ул. Титова 5", dict(city="Отеген батыр", street_name="Титова", house="5", district="Илийский")),
    ("Есик г., ул. Абая 5", dict(city="Есик", street_name="Абая", house="5")),
    (
        "Шымкент, Туранский район, ул. Рашидова 10",
        dict(city="Шымкент", district="Туранский", street_name="Рашидова", house="10"),
    ),
    (
        "г. Караганда, ул. Ерубаева, д. 50, кв. 3, 2 подъезд, 1 этаж",
        dict(
            city="Караганда",
            province="Карагандинская область",
            street_name="Ерубаева",
            house="50",
            apartment="3",
            entrance="2",
            floor="1",
        ),
    ),
    ("Петропавловск ул Конституции 15", dict(city="Петропавловск", street_name="Конституции", house="15")),
    ("Алматы, ул. Сатпаева, 30А/1, кв 14", dict(street_name="Сатпаева", house="30А/1", apartment="14")),
    (
        "Алматы, мкр Кокжиек 45, кв 12",
        dict(street_type="микрорайон", street_name="Кокжиек", house="45", apartment="12"),
    ),
    (
        "Алматы, мкр. Орбита-3, 23, кв. 41",
        dict(street_type="микрорайон", street_name="Орбита-3", house="23", apartment="41", district="Бостандыкский"),
    ),
    ("Алматы, 1 мкр, 32", dict(street_type="микрорайон", street_name="1", house="32")),
    (
        "г. Тараз, ул. Толе би 55, возле рынка",
        dict(city="Тараз", street_name="Толе би", house="55", landmark="возле рынка"),
    ),
    ("ул. 8 Марта 12", dict(street_name="8 Марта", house="12")),
    ("Атырау, мкр Нурсая, ул. 5, д. 7", dict(city="Атырау", living_area="Нурсая", street_name="5", house="7")),
]


@pytest.mark.parametrize("raw,expected", CASES, ids=[c[0][:40] or "<empty>" for c in CASES])
def test_e2e(raw: str, expected: dict[str, Any]) -> None:
    out = engine.parse_one({"id": "x", "raw_address": raw}, explain=False)
    got = {k: out[k] for k in expected}
    assert got == expected, f"{raw!r}"
    assert out["raw_address"] == raw
