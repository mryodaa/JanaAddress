"""Общее для разведки (osm_survey.py), извлечения (osm_extract.py) и привязок (assign_districts.py).

Фильтры тегов OSM, алиасы с языком, геометрия в километрах и эмпирическое определение уровней admin_level
(какой уровень это области, районы областей, городские администрации, районы городов). Уровни не хардкодим:
в дампе Казахстана районы Алматы лежат на 6-м уровне, районы Тараза на 7-м, а сельские округа на 8-м.
© участники OpenStreetMap, ODbL 1.0.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

# ключ тега -> язык алиаса в aliases.lang (ru | kk | en | old | alt | official | short | loc)
NAME_KEYS: dict[str, str] = {
    "name": "ru",
    "name:ru": "ru",
    "name:kk": "kk",
    "name:en": "en",
    "old_name": "old",
    "old_name:ru": "old",
    "old_name:kk": "old",
    "alt_name": "alt",
    "alt_name:ru": "alt",
    "alt_name:kk": "alt",
    "official_name": "official",
    "official_name:ru": "official",
    "official_name:kk": "official",
    "short_name": "short",
    "short_name:ru": "short",
    "loc_name": "loc",
}

ADMIN_LEVELS = {"4", "5", "6", "7", "8", "9", "10"}
PLACE_POINTS = {
    "city",
    "town",
    "village",
    "hamlet",
    "suburb",
    "neighbourhood",
    "quarter",
    "city_block",
    "isolated_dwelling",
    "locality",
    "allotments",
}
AREA_PLACES = {"suburb", "neighbourhood", "quarter", "city_block", "city", "town", "village", "hamlet", "allotments"}
SETTLEMENT_PLACES = ("city", "town", "village", "hamlet", "isolated_dwelling")
LIVING_PLACES = ("suburb", "neighbourhood", "quarter", "city_block", "allotments")
HIGHWAYS = {
    "motorway",
    "trunk",
    "primary",
    "secondary",
    "tertiary",
    "unclassified",
    "residential",
    "living_street",
    "pedestrian",
    "service",
    "road",
    "track",
    "footway",
    "primary_link",
    "secondary_link",
    "tertiary_link",
}
# объекты-ориентиры: ключ -> значения (None = любое значение ключа)
POI_TAGS: dict[str, set[str] | None] = {
    "amenity": {
        "school",
        "kindergarten",
        "hospital",
        "clinic",
        "pharmacy",
        "post_office",
        "marketplace",
        "bank",
        "university",
        "college",
        "fuel",
    },
    "shop": None,
    "office": {"post"},
}

DIST_RE = re.compile(r"(^|\s)(район|ауданы|р-н|district)(\s|$)", re.I)
# сельские/поселковые округа (8-й и 10-й уровни, сотни штук): районом города они не являются
OKRUG_RE = re.compile(r"(округ|округі|с\.\s*о\.|а\.\s*о\.|(^|\s)со$|поселковая|кенттік)", re.I)
CITY_ADMIN_RE = re.compile(
    r"(городская администрация|г\.\s*а\.?|қалалық әкімдігі|қала әкімдігі|қ\.\s*ә\.?|қаласы|city administration)",
    re.I,
)
# «имени» остаётся в каноническом названии («имени Габита Мусрепова», как у ядра и КАТО), вариант без него алиас
STRIP_DIST_RE = re.compile(r"(^|\s)(район|ауданы|р-н)(?=\s|$)", re.I)
IMENI_RE = re.compile(r"(^|\s)(имени|им\.)(?=\s|$)", re.I)


def names(tags: Any) -> dict[str, str]:
    return {k: str(tags.get(k)).strip() for k in NAME_KEYS if tags.get(k) and str(tags.get(k)).strip()}


def ru_name(nm: dict[str, str]) -> str:
    return (nm.get("name:ru") or nm.get("name") or "").strip()


def aliases_with_lang(nm: dict[str, str], main: str | None = None) -> list[tuple[str, str]]:
    """Все написания кроме основного: [(текст, язык)], без повторов текста."""
    main = main if main is not None else ru_name(nm)
    out: dict[str, str] = {}
    # «name» последним: у казахских улиц name совпадает с name:kk, и язык должен быть kk, а не ru
    for k, v in sorted(nm.items(), key=lambda kv: kv[0] == "name"):
        if v and v != main and v not in out:
            out[v] = NAME_KEYS.get(k, "ru")
    return sorted(out.items())


def poi_kind(tags: Any) -> str | None:
    for key, values in POI_TAGS.items():
        v = tags.get(key)
        if v and (values is None or v in values):
            return f"{key}:{v}"
    return None


def strip_district(name: str) -> str:
    return re.sub(r"\s+", " ", STRIP_DIST_RE.sub(" ", name)).strip()


def without_imeni(name: str) -> str:
    return re.sub(r"\s+", " ", IMENI_RE.sub(" ", name)).strip()


def strip_city_admin(name: str) -> str:
    return re.sub(r"\s+", " ", CITY_ADMIN_RE.sub(" ", name)).strip(" .")


# ---------- геометрия ----------
def km(a: tuple[float, float], b: tuple[float, float]) -> float:
    dx = (a[0] - b[0]) * 111.32 * math.cos(math.radians((a[1] + b[1]) / 2))
    dy = (a[1] - b[1]) * 110.57
    return math.hypot(dx, dy)


def km_scale(lat: float) -> tuple[float, float]:
    """Километров в градусе долготы и широты на широте lat (локальная равнопромежуточная проекция)."""
    return 111.32 * math.cos(math.radians(lat)), 110.57


def area_km2(geom: Any) -> float:
    c = geom.centroid
    sx, sy = km_scale(c.y)
    return float(geom.area) * sx * sy


def length_m(geom: Any) -> float:
    """Длина линии в метрах: градусы по осям масштабируются на широте центра (ошибка < 1% в пределах города)."""
    if geom.is_empty:
        return 0.0
    import shapely

    c = geom.centroid
    sx, sy = km_scale(c.y)
    scaled = shapely.transform(geom, lambda xy: xy * [sx * 1000.0, sy * 1000.0])
    return float(scaled.length)


# ---------- уровни ----------
@dataclass
class Boundary:
    osm: str
    level: int
    names: dict[str, str]
    geom: Any
    kato: str | None = None
    area: float = 0.0  # км²
    rp: tuple[float, float] = (0.0, 0.0)

    @property
    def name(self) -> str:
        return ru_name(self.names)

    def any_name(self, rx: re.Pattern[str]) -> bool:
        return any(rx.search(v) for v in self.names.values())

    @property
    def is_district(self) -> bool:
        return self.any_name(DIST_RE) and not self.any_name(OKRUG_RE)


@dataclass
class CityUnit:
    """Город с районами: город респ. значения (полигон области) или городская администрация."""

    container: Boundary
    city: str
    republican: bool
    district_level: int | None = None
    districts: list[Boundary] = field(default_factory=list)
    coverage: float = 0.0
    per_level: dict[int, int] = field(default_factory=dict)


@dataclass
class Levels:
    province_level: int
    oblast_district_level: int | None
    provinces: list[Boundary]
    republican: list[Boundary]
    oblast_districts: list[Boundary]
    city_units: list[CityUnit]
    counts: dict[int, int]


def prepare(boundaries: list[Boundary]) -> None:
    for b in boundaries:
        b.area = area_km2(b.geom)
        p = b.geom.representative_point()
        b.rp = (p.x, p.y)


def detect_levels(boundaries: list[Boundary], republican_max_km2: float = 5000.0) -> Levels:
    """Уровни определяются по данным:
    * область: самый мелкий номер admin_level, где не меньше 14 полигонов (17 областей + 3 города);
    * город респ. значения: полигон уровня области площадью меньше republican_max_km2 (Алматы ~700 км²,
      а самая маленькая область больше 90 тыс. км²);
    * район области: уровень глубже области, где больше всего полигонов «... район/ауданы» вне городов;
    * районы города: для каждого города респ. значения и каждой городской администрации («Г.А.», «қ.ә.»)
      выбирается уровень, где внутри контейнера больше всего полигонов с маркером района (не меньше двух).
    """
    import shapely

    counts = Counter(b.level for b in boundaries)
    prov_level = min((lv for lv, n in counts.items() if n >= 14), default=min(counts) if counts else 4)
    provinces = [b for b in boundaries if b.level == prov_level]
    republican = [b for b in provinces if b.area < republican_max_km2]
    rep_ids = {b.osm for b in republican}

    def inside(child: Boundary, parent: Boundary) -> bool:
        return child.osm != parent.osm and bool(shapely.contains_xy(parent.geom, *child.rp))

    by_level: dict[int, list[Boundary]] = defaultdict(list)
    for b in boundaries:
        by_level[b.level].append(b)
    oblast_dist_counts: Counter[int] = Counter()
    for lv, items in by_level.items():
        if lv <= prov_level:
            continue
        for b in items:
            if b.is_district and not any(inside(b, r) for r in republican):
                oblast_dist_counts[lv] += 1
    oblast_level = oblast_dist_counts.most_common(1)[0][0] if oblast_dist_counts else None
    oblast_districts = [
        b for b in by_level.get(oblast_level or -1, []) if b.is_district and not any(inside(b, r) for r in republican)
    ]

    containers: list[tuple[Boundary, str, bool]] = [(b, b.name, True) for b in republican]
    for b in boundaries:
        if b.level > prov_level and b.osm not in rep_ids and b.any_name(CITY_ADMIN_RE) and not b.is_district:
            containers.append((b, strip_city_admin(b.name), False))
    units: list[CityUnit] = []
    for cont, city, rep in containers:
        unit = CityUnit(cont, city, rep)
        best: tuple[int, int] | None = None
        for lv, items in by_level.items():
            # районы Актобе лежат на том же 6-м уровне, что и «Актобе Г.А.»: уровень не мельче контейнера
            if lv < cont.level:
                continue
            kids = [b for b in items if b.is_district and b.area < cont.area * 0.95 and inside(b, cont)]
            unit.per_level[lv] = len(kids)
            if len(kids) >= 2 and (best is None or len(kids) > best[1]):
                best = (lv, len(kids))
        if best is not None:
            unit.district_level = best[0]
            unit.districts = [
                b for b in by_level[best[0]] if b.is_district and b.area < cont.area * 0.95 and inside(b, cont)
            ]
            covered = sum(float(b.geom.intersection(cont.geom).area) for b in unit.districts)
            unit.coverage = covered / max(float(cont.geom.area), 1e-12)
        units.append(unit)
    in_city = {b.osm for u in units for b in u.districts}
    oblast_districts = [b for b in oblast_districts if b.osm not in in_city]
    return Levels(prov_level, oblast_level, provinces, republican, oblast_districts, units, dict(counts))
