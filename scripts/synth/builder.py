"""Сборка синтетических адресов: реальные топонимы из справочника + искажения из реальных данных.

Каждая запись несёт эталон полей и посимвольные спаны всех полей в raw (`_spans`). Порядок вызовов RNG в
базовом режиме совпадает с прежним gen_dev.py: dev-наборы с теми же seed воспроизводятся байт в байт
(tests/test_synth_spans.py). Новые искажения для обучения теггера включаются только флагом strong и
ветвятся до любых вызовов RNG базового режима.
"""

from __future__ import annotations

import re
import sqlite3
import zlib
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from random import Random
from typing import Any, Literal

from .labeled import LText, fmt

FIELDS = (
    "province",
    "city",
    "district",
    "living_area",
    "street_type",
    "street_name",
    "house",
    "apartment",
    "entrance",
    "floor",
    "landmark",
)
# поля, значение которых копируется из строки и меняется вместе с регистром строки
STRING_FIELDS = ("street_name", "house", "apartment", "entrance", "floor", "landmark", "living_area")

# справочник казахских форм пока не содержит, берём основные города вручную
KZ_CITY = {
    "Алматы": "Алматы",
    "Астана": "Астана",
    "Шымкент": "Шымкент",
    "Актобе": "Ақтөбе",
    "Караганда": "Қарағанды",
    "Костанай": "Қостанай",
    "Павлодар": "Павлодар",
    "Кызылорда": "Қызылорда",
    "Тараз": "Тараз",
    "Уральск": "Орал",
    "Усть-Каменогорск": "Өскемен",
    "Семей": "Семей",
    "Атырау": "Атырау",
    "Актау": "Ақтау",
    "Петропавловск": "Петропавл",
    "Талдыкорган": "Талдықорған",
    "Туркестан": "Түркістан",
    "Кокшетау": "Көкшетау",
    "Жезказган": "Жезқазған",
    "Экибастуз": "Екібастұз",
    "Темиртау": "Теміртау",
}

# маркер улицы: (текст, постфиксный ли). Опечатки и латиница входят как обычные варианты.
STREET_MARKERS: dict[str, list[tuple[str, bool]]] = {
    "улица": [
        ("ул.", False),
        ("ул. ", False),
        ("ул", False),
        ("улица", False),
        ("Ул .", False),
        ("УЛ.", False),
        ("ul.", False),
        ("көшесі", True),
        ("ул.", True),
    ],
    "проспект": [("пр.", False), ("пр-т", False), ("проспект", False), ("просп.", False), ("даңғылы", True)],
    "переулок": [("пер.", False), ("переулок", False), ("пер", False)],
    "проезд": [("пр-д", False), ("проезд", False)],
    "тупик": [("туп.", False), ("тупик", False)],
    "шоссе": [("ш.", False), ("шоссе", False)],
    "бульвар": [("б-р", False), ("бульвар", False)],
    "набережная": [("наб.", False), ("набережная", False)],
    "трасса": [("трасса", False)],
    "тракт": [("тракт", False)],
    "линия": [("линия", True)],
    "аллея": [("аллея", False)],
    "площадь": [("пл.", False), ("площадь", False)],
}
AREA_MARKERS: dict[str, list[tuple[str, bool]]] = {
    "микрорайон": [
        ("мкр", False),
        ("мкр.", False),
        ("Мкр", False),
        ("микрорайон", False),
        ("м-н", False),
        ("мкр", True),
        ("микрорайон", True),
        ("шағын ауданы", True),
    ],
    "квартал": [("квартал", False), ("кв-л", False), ("квартал", True)],
    "жилой массив": [("ж/м", False), ("жилой массив", False), ("ж.м.", False)],
    "жилой комплекс": [("ЖК", False), ("жк", False), ("жилой комплекс", False)],
}
NUMBERED_AREA = {"микрорайон": ["мкр", "микрорайон", "мкр."], "квартал": ["квартал", "кв-л"]}

APT = ["кв. {}", "кв.{}", "кв {}", "квартира {}", "{} кв", "{}кв", "кв{}", "kv {}", "flat {}", "{}квартира", "кв-ра {}"]
ENTRANCE = ["подъезд {}", "подьезд {}", "под. {}", "{} подъезд", "{}подьезд", "{} подьезд", "п. {}"]
FLOOR = ["этаж {}", "эт. {}", "{} этаж", "{}этаж", "{} эт"]
HOUSE = ["{}", "{}", "{}", "д. {}", "д.{}", "дом {}", "{}дом", "{} дом", "д {}"]
LANDMARKS = [
    "напротив ТЦ Мега",
    "возле школы 25",
    "магазин Береке",
    "рядом с аптекой",
    "Qazpost",
    "около рынка",
    "за ТЦ Достык",
    "напротив Magnum",
    "возле мечети",
    "рядом с остановкой",
]
INVISIBLE = ["\u200b", "\u00a0", "\u00ad", "\u2060", "\ufeff"]

# в OSM встречаются «улицы» и пункты с маркером внутри имени («посёлок Приозёрный-1», «станция Мерке»)
SETTLEMENT_WORD = re.compile(
    r"(?i)\b(посёлок|поселок|село|станция|разъезд|территория|имени|аул|ауыл|мкр|микрорайон|жк|квартал|массив)\b"
)
# --chaos: мусор вокруг адреса
JUNK_PREFIX = ["Адрес:", "адрес доставки", "РК", "Казахстан", "Республика Казахстан", "Kazakhstan", "КЗ", "Адрес -"]
JUNK_SUFFIX = ["доставка курьером", "позвонить заранее", "до 18:00", "оставить у двери", "домофон не работает"]
PHONES = ["+7 7{}{} {}{}{} {}{} {}{}", "8 7{}{}{}{}{}{}{}{}", "тел. 87{}{}{}{}{}{}{}{}", "+77{}{}{}{}{}{}{}{}"]
PERSONS = ["Иванову И.И.", "получатель Серикова А.", "для Нурлана", "Ахметов Б.", "ИП Касымов"]
TRANSLIT = dict(
    zip(
        "абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
        [
            *("a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p"),
            *("r", "s", "t", "u", "f", "kh", "ts", "ch", "sh", "sh", "", "y", "", "e", "yu", "ya"),
        ],
        strict=True,
    )
)
CLEAN_NAME = re.compile(r"^[A-Za-zА-Яа-яЁёӘәҒғҚқҢңӨөҰұҮүҺһІі0-9][A-Za-zА-Яа-яЁёӘәҒғҚқҢңӨөҰұҮүҺһІі0-9 .\-]{1,28}$")
HOUSE_NUM = re.compile(r"^\d{1,4}[А-Яа-яA-Za-z]?(/\d{1,3}[А-Яа-я]?)?$")
PROVINCE_MARKER = re.compile(r"^(.*?)(\s+(?:область|обл\.))$")

Split = Literal["all", "train", "unseen"]
# доля топонимов, которые теггер никогда не видит при обучении (проверка обобщения, а не запоминания)
HOLDOUT_STREET_PCT = 15
HOLDOUT_CITY_PCT = 10


def held_out(kind: str, eid: int, pct: int) -> bool:
    return zlib.crc32(f"{kind}:{eid}".encode()) % 100 < pct


@dataclass
class City:
    id: int
    name: str
    kind: str
    province: str | None
    district: str | None  # район области для поселений
    streets: list[tuple[int, str, str | None, int]] = field(default_factory=list)  # id, name, type, houses
    areas: list[tuple[str, str]] = field(default_factory=list)  # name, type
    aliases_lat: list[str] = field(default_factory=list)


class Ref:
    def __init__(self, path: Path, split: Split = "all") -> None:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        q = con.execute
        prov = {i: n for i, n in q("SELECT id, name FROM provinces")}
        self.districts = {i: n for i, n in q("SELECT id, name FROM districts")}
        self.cities: dict[int, City] = {}
        for i, n, k, p, d in q("SELECT id, name, kind, province_id, district_id FROM cities"):
            self.cities[i] = City(i, n, k, prov.get(p), self.districts.get(d))
        rows = q(
            "SELECT s.id, s.name, s.type, s.city_id, count(*) FROM houses h JOIN streets s ON s.id = h.street_id "
            "GROUP BY s.id"
        )
        for sid, name, typ, cid, cnt in rows:
            c = self.cities.get(cid)
            # площадные типы идут отдельной веткой (_area / numbered_area); «5-й» без маркера неразбираем
            if (
                c
                and typ not in ("микрорайон", "квартал")
                and CLEAN_NAME.match(name)
                and not SETTLEMENT_WORD.search(name)
                and not re.search(r"\d{3,}", name)
                and sum(ch.isalpha() for ch in name) >= 3
            ):
                c.streets.append((sid, name, typ, cnt))
        for name, typ, cid in q("SELECT name, type, city_id FROM living_areas"):
            c = self.cities.get(cid)
            if c and typ in AREA_MARKERS and CLEAN_NAME.match(name) and not re.search(r"[A-Za-z]{2}\s*[А-Яа-я]", name):
                c.areas.append((name, typ))
        for eid, alias in q("SELECT eid, alias FROM aliases WHERE etype = 'city'"):
            c = self.cities.get(eid)
            if c and alias.isascii() and alias.replace(" ", "").replace("-", "").isalpha():
                c.aliases_lat.append(alias)
        self.con = con
        if split != "all":
            self._apply_split(split)
        min_streets = 1 if split == "unseen" else 3
        self.by_kind: dict[str, list[City]] = defaultdict(list)
        for c in self.cities.values():
            if len(c.streets) >= min_streets and c.province and not SETTLEMENT_WORD.search(c.name):
                self.by_kind[c.kind].append(c)
        self.street_names = [s[1] for c in self.cities.values() for s in c.streets]

    def _apply_split(self, split: Split) -> None:
        """train: без отложенных городов и улиц; unseen: только отложенные (город целиком или улица)."""
        for c in self.cities.values():
            city_out = c.kind != "republican" and held_out("city", c.id, HOLDOUT_CITY_PCT)
            if split == "train":
                keep = [s for s in c.streets if not held_out("street", s[0], HOLDOUT_STREET_PCT)]
                c.streets = [] if city_out else keep
            elif not city_out:
                c.streets = [s for s in c.streets if held_out("street", s[0], HOLDOUT_STREET_PCT)]

    def houses(self, street_id: int) -> list[tuple[str, str | None]]:
        rows = self.con.execute("SELECT number, district_id FROM houses WHERE street_id = ?", (street_id,))
        return [(n, self.districts.get(d) if d else None) for n, d in rows if HOUSE_NUM.match(n)]


def district_phrase(rnd: Random, name: str) -> LText:
    """«Бостандыкский район» / «район Есиль»: прилагательное ставится перед словом, имя собственное после."""
    adjective = name.endswith(("ий", "ый", "ой"))
    marker = rnd.choice(["район", "р-н", "район", "р-он"])
    return fmt(f"{{}} {marker}" if adjective else f"{marker} {{}}", name, "DISTRICT")


def province_text(s: str) -> LText:
    """«Алматинская обл.»: название PROVINCE, маркер O."""
    m = PROVINCE_MARKER.match(s)
    return LText.of(m.group(1), "PROVINCE") + m.group(2) if m else LText.of(s, "PROVINCE")


def city_text(form: str, name: str, kz: str | None) -> LText:
    """Город по шаблону. Каз. половина двуязычной записи («/Ақтөбе қаласы») это KZ_DUP целиком."""
    if "/" in form:
        left, right = form.split("/")
        return fmt(left, name, "CITY") + "/" + LText.of(right.format(kz=kz), "KZ_DUP")
    if "{kz}" in form:
        pre, post = form.split("{kz}")
        return LText.of(pre) + LText.of(kz or "", "CITY") + post
    return fmt(form, name, "CITY")


class Builder:
    def __init__(self, ref: Ref, rnd: Random, chaos: bool = False, strong: bool = False) -> None:
        self.ref = ref
        self.rnd = rnd
        self.chaos = chaos
        self.strong = strong
        if strong:
            from .augment import Augment

            self.aug: Any = Augment(rnd)

    def pick_city(self) -> City:
        rnd = self.rnd
        kind = rnd.choices(["republican", "city", "town", "village"], weights=[45, 33, 10, 12])[0]
        pool = self.ref.by_kind[kind] or self.ref.by_kind["city"] or next(p for p in self.ref.by_kind.values() if p)
        weights = [len(c.streets) ** 0.5 for c in pool]
        return rnd.choices(pool, weights=weights)[0]

    def record(self, idx: int) -> dict[str, Any]:
        rnd = self.rnd
        city = self.pick_city()
        g: dict[str, Any] = dict.fromkeys(FIELDS)
        tags: list[str] = [f"city_kind:{city.kind}"]
        g["province"] = city.province
        g["city"] = city.name

        # ---- улица / микрорайон ----
        street_part, house_district = self._street_part(city, g, tags)

        # ---- дом и детали ----
        details = self._details(g, tags, street_part)

        # ---- административная часть ----
        admin = self._admin(city, g, tags, house_district)

        parts: list[LText] = [*admin["head"], *street_part["parts"], *details]
        if rnd.random() < 0.08:
            lm = rnd.choice(LANDMARKS)
            g["landmark"] = lm
            parts.append(LText.of(lm, "LANDMARK"))
            tags.append("landmark")
        parts += admin["tail"]
        if self.chaos:
            parts = self._chaos_parts(parts, tags)
        if self.strong:
            parts = self.aug.parts(parts, g, tags)

        if rnd.random() < (0.35 if self.strong else 0.2):
            raw = LText.join(" ", parts)
            tags.append("no_commas")
        elif self.chaos and rnd.random() < 0.3:
            sep = rnd.choice(["; ", " / ", " | ", ". ", " - ", ",", ";"])
            raw = LText.join(sep, parts)
            tags.append("odd_separator")
        else:
            raw = LText.join(", ", parts)
        raw = raw.sub(r"\s+", lambda _: " ").strip()
        raw = self._noise(raw, g, tags)

        g["district"] = g["district"] or house_district
        text = raw.text
        from_ref = [f for f in ("district", "living_area") if g[f] and g[f].lower() not in text.lower()]
        rec: dict[str, Any] = {"id": f"syn_{idx:05d}", "raw_address": text, **g, "confidence": None}
        rec["_from_reference"] = from_ref
        rec["_tags"] = sorted(set(tags))
        rec["_spans"] = [list(s) for s in raw.spans()]
        return rec

    # -------- части --------
    def _street_part(self, city: City, g: dict[str, Any], tags: list[str]) -> tuple[dict[str, Any], str | None]:
        rnd = self.rnd
        roll = rnd.random()
        if roll < 0.10 and city.areas:
            return self._area(city, g, tags, with_street=rnd.random() < 0.3), None
        if roll < 0.16:
            # «66квартал 12», «5 мкр 12 дом»
            typ = rnd.choice(list(NUMBERED_AREA))
            n = str(rnd.randint(1, 40))
            m = rnd.choice(NUMBERED_AREA[typ])
            glue = rnd.random() < 0.4
            num, mk = LText.of(n, "STREET_NAME"), LText.of(m, "STREET_TYPE")
            text = num + mk if glue else rnd.choice([num + " " + mk, mk + " " + num])
            g.update(street_type=typ, street_name=n, house=str(rnd.randint(1, 60)))
            tags += ["numbered_area", *(["glued_area"] if glue else [])]
            return {"parts": [text], "glue_house": False}, None

        sid, name, typ, _ = rnd.choices(city.streets, weights=[s[3] ** 0.5 for s in city.streets])[0]
        house_district: str | None = None
        if rnd.random() < 0.08:
            # улица, которой в этом городе нет: проверяет, что разбор не опирается на справочник
            names = {s[1] for s in city.streets}
            name = next(n for n in iter(lambda: rnd.choice(self.ref.street_names), None) if n not in names)
            typ = "улица"
            house = str(rnd.randint(1, 150))
            tags.append("street_unknown")
        else:
            houses = self.ref.houses(sid)
            if not houses:
                houses = [(str(rnd.randint(1, 150)), None)]
            house, house_district = rnd.choice(houses)
        house = self._house_variant(house, tags)
        if self.chaos:
            name = self._chaos_name(name, tags)
        g["house"] = house
        g["street_name"] = name
        if self.strong:
            special = self.aug.street(name, typ, g, tags)
            if special is not None:
                return {"parts": [special], "glue_house": True}, house_district

        markers = STREET_MARKERS.get(typ or "", [])
        if not markers or rnd.random() < 0.15:
            tags.append("street_no_marker")
            g["street_type"] = typ  # из справочника, в метрику не входит
            text = LText.of(name, "STREET_NAME")
        else:
            m, postfix = rnd.choice(markers)
            g["street_type"] = typ
            nm = LText.of(name, "STREET_NAME")
            if postfix:
                text = nm + " " + LText.of(m, "STREET_TYPE")
                tags.append("street_marker_postfix")
            else:
                sep = "" if m.endswith(".") and rnd.random() < 0.4 else " "
                text = _marker(m) + sep + nm
            if m in ("Ул .", "ul.", "УЛ."):
                tags.append("street_marker_odd")
        return {"parts": [text], "glue_house": True}, house_district

    def _area(self, city: City, g: dict[str, Any], tags: list[str], with_street: bool) -> dict[str, Any]:
        rnd = self.rnd
        name, typ = rnd.choice(city.areas)
        m, postfix = rnd.choice(AREA_MARKERS[typ])
        tags.append(f"area:{typ}")
        if postfix:
            tags.append("area_postfix")
        if with_street and city.streets:
            # мкр с отдельной улицей: название это living_area, маркер мкр не street_type
            text = LText.of(name, "LIVING_AREA") + " " + m if postfix else m + " " + LText.of(name, "LIVING_AREA")
            sid, sname, styp, _ = rnd.choice(city.streets)
            houses = self.ref.houses(sid) or [(str(rnd.randint(1, 150)), None)]
            house = self._house_variant(rnd.choice(houses)[0], tags)
            g.update(living_area=name, street_name=sname, street_type=styp or None, house=house)
            sm = STREET_MARKERS.get(styp or "", [("ул.", False)])[0][0] if styp else ""
            stext = _marker(sm) + " " + LText.of(sname, "STREET_NAME") if sm else LText.of(sname, "STREET_NAME")
            tags.append("area_with_street")
            return {"parts": [text, stext], "glue_house": True}
        nm, mk = LText.of(name, "STREET_NAME"), LText.of(m, "STREET_TYPE")
        text = nm + " " + mk if postfix else mk + " " + nm
        house = self._house_variant(str(rnd.randint(1, 80)), tags)
        g.update(street_type=typ, street_name=name, house=house)
        return {"parts": [text], "glue_house": False}

    def _house_variant(self, house: str, tags: list[str]) -> str:
        rnd = self.rnd
        m = re.match(r"^(\d+)([А-Яа-яA-Za-z])$", house)
        if m:
            tags.append("house_letter")
            num, letter = m.groups()
            letter = rnd.choice([letter, letter.lower(), letter.upper()])
            house = rnd.choice([f"{num}{letter}", f"{num}{letter}", f"{num} {letter}", f"{num}-{letter}"])
        elif "/" in house:
            tags.append("house_fraction")
        return house

    def _details(self, g: dict[str, Any], tags: list[str], street: dict[str, Any]) -> list[LText]:
        rnd = self.rnd
        house = g["house"]
        apt = str(rnd.randint(1, 300)) if rnd.random() < 0.55 else None
        out: list[LText] = []
        if apt and rnd.random() < 0.08 and re.fullmatch(r"\d+", house):
            # «Абая 150-23»
            street["parts"][-1] += " " + LText.of(house, "HOUSE") + "-" + LText.of(apt, "APARTMENT")
            g["apartment"] = apt
            tags.append("house_dash_apt")
            apt = None
        elif street["glue_house"] and house.isdigit() and rnd.random() < 0.1 and "street_no_marker" not in tags:
            street["parts"][-1] += LText.of(house, "HOUSE")  # «Назарбаева8»
            tags.append("glued_street_house")
        else:
            form = rnd.choice(self.aug.house_forms() if self.strong else HOUSE)
            if form != "{}":
                tags.append("house_marker")
            if form in ("{}дом",):
                tags.append("glued_detail")
            joiner = " " if rnd.random() < 0.6 else ", "
            street["parts"][-1] += joiner + fmt(form, house, "HOUSE")
            if self.strong:
                # «5 корп 2», «11к2»: сразу за номером корпус входит в house (Q10); после «дом» нет
                street["parts"][-1] += self.aug.building(tags, g, attach=form.endswith("{}"))
        if rnd.random() < 0.15:
            e = str(rnd.randint(1, 12))
            g["entrance"] = e
            out.append(self._detail(self.aug.forms("entrance") if self.strong else ENTRANCE, e, "ENTRANCE", tags))
        if rnd.random() < 0.12:
            f = str(rnd.randint(1, 16))
            g["floor"] = f
            out.append(self._detail(self.aug.forms("floor") if self.strong else FLOOR, f, "FLOOR", tags))
        if apt:
            g["apartment"] = apt
            a = self._detail(self.aug.forms("apartment") if self.strong else APT, apt, "APARTMENT", tags)
            if rnd.random() < 0.7:
                out.append(a)
            else:
                out.insert(0, a)
            if a.text.startswith(("kv", "flat")):
                tags.append("latin_detail")
        if out and rnd.random() < 0.5:
            return [LText.join(" ", out)]
        return out

    def _detail(self, forms: list[str], value: str, label: str, tags: list[str]) -> LText:
        form = self.rnd.choice(forms)
        if form.startswith("{}") and not form.startswith("{} "):
            tags.append("glued_detail")
        if form.endswith("{}") and not form.endswith(" {}"):
            tags.append("glued_detail")
        if "подьезд" in form:
            tags.append("typo_detail")
        return fmt(form, value, label)

    def _admin(
        self, city: City, g: dict[str, Any], tags: list[str], house_district: str | None
    ) -> dict[str, list[LText]]:
        rnd = self.rnd
        head: list[LText] = []
        tail: list[LText] = []
        name = city.name
        if city.kind == "village":
            if rnd.random() < 0.6:
                prov = rnd.choice([city.province, (city.province or "").replace("область", "обл.")])
                head.append(province_text(self.aug.old_province(prov, g, tags) if self.strong else prov))
                tags.append("province_written")
            if city.district and rnd.random() < 0.7:
                head.append(district_phrase(rnd, city.district))
                g["district"] = city.district
                tags.append("district_written")
            form = rnd.choice(["с. {}", "село {}", "п. {}", "пос. {}", "{} ауылы", "{}"])
            settlement = fmt(form, name, "CITY")
            if self.strong and self.aug.city_last():
                tail.append(settlement)
                tags.append("city_last")
            else:
                head.append(settlement)
            tags.append("settlement")
            return {"head": head, "tail": tail}

        if city.kind != "republican" and rnd.random() < 0.25:
            prov = rnd.choice([city.province, (city.province or "").replace("область", "обл.")])
            head.append(province_text(self.aug.old_province(prov, g, tags) if self.strong else prov))
            tags.append("province_written")

        if city.kind == "republican" and house_district and rnd.random() < 0.12:
            head.append(district_phrase(rnd, house_district))
            g["district"] = house_district
            tags.append("district_instead_city")
            return {"head": head, "tail": tail}

        kz = KZ_CITY.get(name)
        forms = ["г. {}", "г.{}", "город {}", "{}", "г {}", "{}"]
        if kz:
            forms += ["{kz} қаласы", "город {}/{kz} қаласы", "г. {}/{kz} қ."]
        form = rnd.choice(forms)
        text = city_text(form, name, kz)
        if city.aliases_lat and rnd.random() < 0.06:
            text = LText.of(rnd.choice(city.aliases_lat), "CITY")
            tags.append("latin_city")
        elif "{kz}" in form:
            tags.append("kz_city" if "/" not in form else "bilingual_city")
        city_last = rnd.random() < (0.3 if self.strong else 0.12)
        (tail if city_last else head).append(text)
        if city_last:
            tags.append("city_last")
        if rnd.random() < 0.08:
            # город повторяется: «г. Алматы, Алматы, ...» или в конце строки
            dup = fmt(rnd.choice(["{}", "г. {}"]), name, "CITY")
            (head if not city_last and rnd.random() < 0.5 else tail).append(dup)
            tags.append("dup_city")
        if city.kind == "republican" and house_district and rnd.random() < 0.2:
            head.append(district_phrase(rnd, house_district))
            g["district"] = house_district
            tags.append("district_written")
        return {"head": head, "tail": tail}

    # -------- хаос: то, что люди пишут в поле «адрес» помимо адреса --------
    def _chaos_name(self, name: str, tags: list[str]) -> str:
        """Опечатка или латиница в названии улицы. Эталон это написанное (значение режется из строки как есть)."""
        rnd = self.rnd
        r = rnd.random()
        if r < 0.2 and len(name) > 4:
            i = rnd.randrange(1, len(name) - 1)
            op = rnd.choice(["del", "dup", "swap", "sub"])
            if op == "del":
                name = name[:i] + name[i + 1 :]
            elif op == "dup":
                name = name[:i] + name[i] + name[i:]
            elif op == "swap":
                name = name[:i] + name[i + 1] + name[i] + name[i + 2 :]
            else:
                name = name[:i] + rnd.choice("аеиоуыя") + name[i + 1 :]
            tags.append("typo_street")
        elif r < 0.28 and re.fullmatch(r"[А-Яа-яЁё \-]+", name):
            name = "".join(
                TRANSLIT.get(ch.lower(), ch).capitalize() if ch.isupper() else TRANSLIT.get(ch, ch) for ch in name
            )
            tags.append("latin_street")
        return name

    def _chaos_parts(self, parts: list[LText], tags: list[str]) -> list[LText]:
        rnd = self.rnd
        parts = list(parts)
        if rnd.random() < 0.25:
            parts.insert(0, LText.of(rnd.choice(JUNK_PREFIX), "NOISE"))
            tags.append("junk_prefix")
        if rnd.random() < 0.15:
            parts.insert(rnd.randint(0, len(parts)), LText.of("0" + str(rnd.randint(10000, 99999)), "NOISE"))
            tags.append("postcode")
        if rnd.random() < 0.15:
            phone = rnd.choice(PHONES).format(*(rnd.randint(0, 9) for _ in range(10)))
            parts.append(LText.of(phone, "NOISE"))
            tags.append("phone")
        if rnd.random() < 0.12:
            parts.append(LText.of(rnd.choice(PERSONS), "NOISE"))
            tags.append("person")
        if rnd.random() < 0.1:
            parts.append(LText.of(rnd.choice(JUNK_SUFFIX), "NOISE"))
            tags.append("junk_suffix")
        if rnd.random() < 0.15 and len(parts) > 2:
            rnd.shuffle(parts)
            tags.append("shuffled")
        return parts

    def _noise(self, raw: LText, g: dict[str, Any], tags: list[str]) -> LText:
        rnd = self.rnd
        if rnd.random() < 0.08:
            raw = self._invisible(raw)
            tags.append("invisible")
        if rnd.random() < 0.1:
            raw = raw.sub(r",", lambda _: rnd.choice([" ,", " , ", ",  ", ","]))
            raw = raw.sub(r" ", lambda _: "  " if rnd.random() < 0.3 else " ")
            tags.append("extra_spaces")
        if rnd.random() < 0.06:
            up = rnd.random() < 0.5
            raw = raw.upper() if up else raw.lower()
            for f in STRING_FIELDS:
                if g[f]:
                    g[f] = g[f].upper() if up else g[f].lower()
            tags.append("case_upper" if up else "case_lower")
        return raw

    def _invisible(self, raw: LText) -> LText:
        rnd = self.rnd
        for _ in range(rnd.randint(1, 3)):
            ch = rnd.choice(INVISIBLE)
            chars = raw.text
            spaces = [i for i, c in enumerate(chars) if c == " "]
            if ch == "\u00a0" and spaces:
                raw.set_char(rnd.choice(spaces), ch)
                continue
            # внутрь слова, не внутрь числа: дробь и номер дома не должны распадаться
            pos = [i for i in range(1, len(chars)) if chars[i - 1].isalpha() and chars[i].isalpha()]
            if pos:
                raw.insert(rnd.choice(pos), ch)
        if rnd.random() < 0.3:
            raw.insert(0, "\ufeff")
        return raw


def _marker(m: str) -> LText:
    """Маркер улицы «Ул .» / «ул. »: STREET_TYPE без краевых пробелов, пробелы O."""
    core = m.strip()
    i = m.index(core)
    return LText.of(m[:i]) + LText.of(core, "STREET_TYPE") + LText.of(m[i + len(core) :])


__all__ = ["FIELDS", "STRING_FIELDS", "Builder", "LText", "Ref"]
