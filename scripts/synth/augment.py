"""Сильные искажения для обучения теггера (Builder(strong=True)). Dev-наборы их не используют.

Покрывает то, на чём правила ошибаются в docs/STATE.md: номерные улицы («2-й проезд Рахимова»), тип после
названия («Коммунальный пер»), литера через пробел перед маркером («17 А дом»), латиница и опечатки маркеров,
двуязычные улицы, ФИО, телефоны, служебные хвосты, мусорные префиксы, регистр.
"""

from __future__ import annotations

import re
from random import Random
from typing import Any

from .labeled import LText

APT = ["кв. {}", "кв.{}", "кв {}", "квартира {}", "{} кв", "{}кв", "кв{}", "kv {}", "flat {}", "{}квартира", "кв-ра {}"]
APT_X = ["kv{}", "kv.{}", "kv. {}", "flat{}", "apt {}", "кв-{}", "квартира{}", "кваритра {}", "квартра {}", "пәтер {}",
         "{} пәтер", "{} kv", "{}kv", "KB {}", "кв №{}", "кв.№ {}"]  # fmt: skip
ENTRANCE = ["подъезд {}", "подьезд {}", "под. {}", "{} подъезд", "{}подьезд", "{} подьезд", "п. {}"]
ENTRANCE_X = ["pod {}", "pod.{}", "podezd {}", "{} pod", "подьез {}", "подезд {}", "{}подъезд", "{} под.",
              "кіреберіс {}", "п-д {}", "{}-подъезд"]  # fmt: skip
FLOOR = ["этаж {}", "эт. {}", "{} этаж", "{}этаж", "{} эт"]
FLOOR_X = ["etazh {}", "{}etazh", "et.{}", "етаж {}", "{} етаж", "қабат {}", "{} қабат", "{}-этаж", "эт{}", "{} et"]
HOUSE = ["{}", "{}", "{}", "д. {}", "д.{}", "дом {}", "{}дом", "{} дом", "д {}"]
# нежилые помещения: номер как квартира (rules/markers.yaml, apartment)
UNITS = ["офис {}", "оф. {}", "оф {}", "бутик {}", "бутик №{}", "павильон {}", "каб. {}", "кабинет {}",
         "помещение {}", "пом. {}", "склад №{}", "бокс {}"]  # fmt: skip
ORG_NAMES = ["Сапа Трейд", "Альфа", "Нур Строй", "KazLogistic", "Береке Групп", "Жулдыз", "Astana Motors", "Медикер",
             "Темір Сервис", "Алтын Дала"]  # fmt: skip
# нынешняя область -> (прежняя каноническая, как пишут)
OLD_PROVINCE = {
    "Абайская область": (
        "Восточно-Казахстанская область",
        ["Восточно-Казахстанская область", "ВКО", "Восточно-Казахстанская обл."],
    ),
    "Жетысуская область": ("Алматинская область", ["Алматинская область", "Алматинская обл."]),
    "Улытауская область": ("Карагандинская область", ["Карагандинская область", "Карагандинская обл."]),
}
HOUSE_X = ["дом{}", "dom {}", "dom{}", "{} dom", "д-{}", "{} д.", "үй {}", "{} үй", "{}-дом", "д.№{}", "house {}"]

# тип улицы после названия: (маркер, канонический тип)
POSTFIX = {
    "улица": ["ул", "ул.", "улица", "көшесі", "көш.", "str."],
    "переулок": ["пер", "пер.", "переулок"],
    "проспект": ["пр.", "пр-т", "проспект", "даңғылы", "просп."],
    "проезд": ["пр-д", "проезд"],
    "бульвар": ["б-р", "бульвар"],
    "тупик": ["туп.", "тупик"],
    "шоссе": ["ш.", "шоссе"],
}
# опечатки и латиница маркера улицы перед названием
STREET_X = ["улциа", "уллица", "ули", "ул,", "Ул", "UL.", "ulitsa", "ulica", "ul", "street", "str.", "у.", "пр-кт",
            "прос.", "пркт", "проспек", "переул.", "пер-к"]  # fmt: skip
STREET_X_TYPE = {"пр-кт": "проспект", "прос.": "проспект", "пркт": "проспект", "проспек": "проспект",
                 "переул.": "переулок", "пер-к": "переулок"}  # fmt: skip
NUMBERED = [("проезд", "й"), ("переулок", "й"), ("тупик", "й"), ("линия", "я"), ("проулок", "й")]

SURNAMES = ["Ахметов", "Иванова", "Серикбаев", "Касымова", "Нурланов", "Петренко", "Жумабекова", "Оспанов", "Ким",
            "Абенова", "Смагулов", "Ли", "Токтарова", "Байжанов", "Сидоренко"]  # fmt: skip
NAMES = ["Нурлан", "Айгерим", "Ержан", "Асель", "Марат", "Динара", "Сергей", "Алия", "Дамир", "Мадина"]
PREFIX = ["Казахстан", "Kazakhstan", "Республика Казахстан", "Republic of Kazakhstan", "РК", "КЗ", "Қазақстан",
          "Адрес:", "Адрес доставки:", "адрес", "Address:", "Казахстан Республикасы"]  # fmt: skip
TAILS = ["оставить у двери", "доставка курьером", "позвонить заранее", "звонить за час", "не звонить", "до 18:00",
         "после 14.00", "с 9 до 18", "код домофона 45", "вход со двора", "домофон не работает", "оплачено",
         "хрупкое", "позвонить перед доставкой", "оставить у охраны", "в рабочее время"]  # fmt: skip


class Augment:
    def __init__(self, rnd: Random) -> None:
        self.rnd = rnd

    # ---- формы деталей ----
    def house_forms(self) -> list[str]:
        return HOUSE + HOUSE_X

    def forms(self, kind: str) -> list[str]:
        return {"apartment": APT + APT_X + UNITS, "entrance": ENTRANCE + ENTRANCE_X, "floor": FLOOR + FLOOR_X}[kind]

    def building(self, tags: list[str], g: dict[str, Any], attach: bool) -> LText:
        """Корпус/строение после дома. Сразу за номером входит в house как написано (Q10, разметка HOUSE, эталон
        «5 корп 2»); после маркера («5 дом корп 2») не поле: метка O, house без корпуса (как в шаге building)."""
        if self.rnd.random() >= 0.08:
            return LText()
        tags.append("building_part")
        n = str(self.rnd.randint(1, 9))
        text = self.rnd.choice([f" корп {n}", f" корп. {n}", f" корпус {n}", f"к{n}", f" к.{n}", f" стр. {n}",
                                f" строение {n}", f" блок {self.rnd.choice('АБВС')}", f"с{n}"])  # fmt: skip
        if not attach:
            return LText.of(" " + text.lstrip())  # после «дом»: «5 дом к2», а не слипшееся «5домк2»
        g["house"] = f"{g['house']}{text}"
        return LText.cont(text, "HOUSE")

    def old_province(self, prov: str, g: dict[str, Any], tags: list[str]) -> str:
        """Прежняя область после передела («ВКО, г. Семей»): эталон как написано (docs/QUESTIONS.md, Q18)."""
        old = OLD_PROVINCE.get(g["province"] or "")
        if old is None or self.rnd.random() >= 0.5:
            return prov
        name, written = old
        g["province"] = name
        tags.append("old_province")
        return self.rnd.choice(written)

    def org(self) -> str:
        rnd = self.rnd
        name = rnd.choice(ORG_NAMES)
        return rnd.choice([f"ТОО «{name}»", f'ТОО "{name}"', f"ТОО {name}", f"ИП {rnd.choice(SURNAMES)}",
                           f"АО «{name}»", f"АО {name}", f"ЖШС «{name}»", f"ООО {name}"])  # fmt: skip

    def city_last(self) -> bool:
        return self.rnd.random() < 0.3

    # ---- улица ----
    def street(self, name: str, typ: str | None, g: dict[str, Any], tags: list[str]) -> LText | None:
        rnd = self.rnd
        house = g["house"]
        if re.fullmatch(r"\d{1,3}", house) and rnd.random() < 0.12:
            # «17 А дом»: литера через пробел, часто прямо перед маркером
            letter = rnd.choice("АБВГабвгДЕЛМ")
            g["house"] = rnd.choice([f"{house} {letter}", f"{house} {letter}", f"{house}{letter}", f"{house}-{letter}"])
            tags.append("house_letter")
        nm = LText.of(name, "STREET_NAME")
        r = rnd.random()
        if r < 0.10:
            # «2-й проезд Рахимова», «4 переулок Садовой»: номер и тип внутри названия
            tw, end = rnd.choice(NUMBERED)
            n = str(rnd.randint(1, 12))
            num = rnd.choice([f"{n}-{end}", f"{n}-{end}", n, f"{n}-о{end}" if end == "й" else f"{n}-{end}"])
            full = rnd.choice([f"{num} {tw} {name}", f"{num} {tw} {name}", f"{name} {num} {tw}"])
            g["street_name"] = full
            g["street_type"] = tw if tw in POSTFIX or tw == "линия" else "переулок"
            tags.append("numbered_street")
            if rnd.random() < 0.4:
                g["street_type"] = "улица"
                return LText.of(rnd.choice(["ул.", "ул", "улица"]), "STREET_TYPE") + " " + LText.of(full, "STREET_NAME")
            return LText.of(full, "STREET_NAME")
        if r < 0.22 and typ in POSTFIX:
            # «Коммунальный пер»: тип после названия
            m = rnd.choice(POSTFIX[typ])
            g["street_type"] = typ
            tags.append("street_type_last")
            return nm + " " + LText.of(m, "STREET_TYPE")
        if r < 0.28:
            # «ул. Абая/Абай көшесі»: казахская половина дублирует
            m = rnd.choice(["ул.", "ул", "улица"])
            g["street_type"] = "улица"
            tags.append("bilingual_street")
            dup = rnd.choice([f"{name} көшесі", f"{name} к-сі", f"{name} көш."])
            return LText.of(m, "STREET_TYPE") + " " + nm + rnd.choice(["/", " / ", "/ "]) + LText.of(dup, "KZ_DUP")
        if r < 0.36:
            m = rnd.choice(STREET_X)
            g["street_type"] = STREET_X_TYPE.get(m, "улица")
            tags.append("street_marker_typo")
            return LText.of(m, "STREET_TYPE") + rnd.choice([" ", "", " "]) + nm
        return None

    # ---- мусор вокруг адреса ----
    def person(self) -> str:
        rnd = self.rnd
        s, n = rnd.choice(SURNAMES), rnd.choice(NAMES)
        ini = rnd.choice("АБДЕКМНСТ")
        return rnd.choice(
            [f"{s} {ini}.", f"{s} {ini}.{rnd.choice('АБЕКМ')}.", f"получатель {s} {ini}.", f"для {n}а",
             f"ИП {s}", f"{s} {n}", f"{n} {s}", f"{s}у {ini}.{rnd.choice('АБЕКМ')}."]
        )  # fmt: skip

    def phone(self) -> str:
        rnd = self.rnd
        d = [str(rnd.randint(0, 9)) for _ in range(10)]
        a, b, c, e = "".join(d[:2]), "".join(d[2:5]), "".join(d[5:7]), "".join(d[7:9])
        return rnd.choice(
            [f"+7 7{a} {b} {c} {e}", f"87{a}{b}{c}{e}", f"тел. 87{a}{b}{c}{e}", f"+7 (7{a}) {b}-{c}-{e}",
             f"моб: 87{a}{b}{c}{e}", f"тел: +77{a}{b}{c}{e}", f"8-7{a}-{b}-{c}-{e}"]
        )  # fmt: skip

    def parts(self, parts: list[LText], g: dict[str, Any], tags: list[str]) -> list[LText]:
        rnd = self.rnd
        parts = list(parts)
        if rnd.random() < 0.3:
            parts.insert(0, LText.of(rnd.choice(PREFIX), "NOISE"))
            tags.append("junk_prefix")
        if rnd.random() < 0.15:
            code = "0" + str(rnd.randint(10000, 99999))
            parts.insert(rnd.randint(0, len(parts)), LText.of(rnd.choice([code, f"индекс {code}"]), "NOISE"))
            tags.append("postcode")
        if rnd.random() < 0.2:
            parts.insert(rnd.choice([len(parts), len(parts), 0]), LText.of(self.phone(), "NOISE"))
            tags.append("phone")
        if rnd.random() < 0.18:
            parts.insert(rnd.choice([len(parts), len(parts), 0]), LText.of(self.person(), "NOISE"))
            tags.append("person")
        if rnd.random() < 0.08:
            parts.insert(rnd.choice([0, 1, len(parts)]), LText.of(self.org(), "NOISE"))
            tags.append("org")
        if rnd.random() < 0.18:
            parts.append(LText.of(rnd.choice(TAILS), "NOISE"))
            tags.append("junk_suffix")
        if rnd.random() < 0.1 and len(parts) > 2:
            rnd.shuffle(parts)
            tags.append("shuffled")
        if rnd.random() < 0.06:
            # регистр по частям: «ПАВШИХ БОРЦОВ көшесі 126»
            k = rnd.randrange(len(parts))
            up = rnd.random() < 0.6
            parts[k] = parts[k].upper() if up else parts[k].lower()
            tags.append("case_part")
            self._sync_case(parts[k], g)
        return parts

    @staticmethod
    def _sync_case(part: LText, g: dict[str, Any]) -> None:
        """Эталон строковых полей = текст их спанов после смены регистра части."""
        label_to_field = {
            "STREET_NAME": "street_name",
            "HOUSE": "house",
            "APARTMENT": "apartment",
            "ENTRANCE": "entrance",
            "FLOOR": "floor",
            "LANDMARK": "landmark",
            "LIVING_AREA": "living_area",
        }
        for s, e, lab in part.spans():
            f = label_to_field.get(lab)
            if f and g[f] and g[f].casefold() == part.text[s:e].casefold():
                g[f] = part.text[s:e]


__all__ = ["Augment"]
