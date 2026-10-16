"""Загрузка словарей правил из rules/*.yaml в структуры для быстрого поиска фраз."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, TypeVar

import yaml

from . import config
from .reference.normalize import fold, keys

V = TypeVar("V")


class PhraseIndex[V]:
    """Словарь фраз (1..N слов) -> значение. Ключ это fold() фразы, слова через пробел."""

    def __init__(self) -> None:
        self._map: dict[str, V] = {}
        self.max_words = 1

    def add(self, phrase: str, value: V) -> None:
        for k in keys(phrase):
            if not k:
                continue
            self._map.setdefault(k, value)
            self.max_words = max(self.max_words, len(k.split(" ")))

    def get(self, phrase: str) -> V | None:
        for k in keys(phrase):
            if k in self._map:
                return self._map[k]
        return None

    def __contains__(self, phrase: str) -> bool:
        return self.get(phrase) is not None

    def match(self, folds: list[str], i: int) -> tuple[V, int] | None:
        """Самое длинное совпадение, начинающееся с folds[i]. Возвращает (значение, число токенов)."""
        best: tuple[V, int] | None = None
        words = 0
        for n in range(1, len(folds) - i + 1):
            words += len(folds[i + n - 1].split(" "))
            if words > self.max_words:
                break
            v = self._map.get(" ".join(folds[i : i + n]))
            if v is not None:
                best = (v, n)
        return best

    def words(self) -> set[str]:
        return {w for k in self._map for w in k.split(" ")}


@dataclass
class StreetType:
    canonical: str
    kind: str  # street | area


@dataclass
class Rules:
    street_types: PhraseIndex[StreetType]
    details: PhraseIndex[str]  # -> apartment | entrance | floor | house
    noise: PhraseIndex[bool]
    building_part: PhraseIndex[bool]
    needs_dot: set[str]
    needs_number: set[str]
    house_dash_apartment: bool
    province_markers: PhraseIndex[bool]
    district_markers: PhraseIndex[bool]
    district_blockers: set[str]
    city_prefix: PhraseIndex[bool]
    city_suffix: PhraseIndex[bool]
    settlement_prefix: PhraseIndex[bool]
    settlement_suffix: PhraseIndex[bool]
    weak_prefixes: set[str]
    rural_okrug: PhraseIndex[bool]
    lm_prepositions: PhraseIndex[bool]
    lm_objects: PhraseIndex[bool]
    lm_brands: PhraseIndex[bool]
    lm_numbered: set[str]
    confidence: dict[str, Any] = field(default_factory=dict)
    arbiter: dict[str, Any] = field(default_factory=dict)
    org_forms: set[str] = field(default_factory=set)
    org_forms_upper: set[str] = field(default_factory=set)
    number_name_words: set[str] = field(default_factory=set)
    historical_provinces: dict[str, set[str]] = field(default_factory=dict)


def _read(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    assert isinstance(data, dict), path
    return data


def _flag_index(items: list[str]) -> PhraseIndex[bool]:
    idx: PhraseIndex[bool] = PhraseIndex()
    for it in items:
        idx.add(str(it), True)
    return idx


def load_rules(rules_dir: Path | None = None) -> Rules:
    d = rules_dir or config.RULES_DIR
    st = _read(d / "street_types.yaml")
    mk = _read(d / "markers.yaml")
    ad = _read(d / "admin.yaml")
    lm = _read(d / "landmarks.yaml")
    conf = _read(d / "confidence.yaml")
    arb = _read(d / "arbiter.yaml") if (d / "arbiter.yaml").exists() else {}

    street_types: PhraseIndex[StreetType] = PhraseIndex()
    for canonical, spec in st.items():
        t = StreetType(canonical=canonical, kind=spec.get("kind", "street"))
        street_types.add(canonical, t)
        for a in spec.get("aliases", []):
            street_types.add(str(a), t)

    details: PhraseIndex[str] = PhraseIndex()
    for fname in ("apartment", "entrance", "floor", "house"):
        for a in mk.get(fname, []):
            details.add(str(a), fname)

    return Rules(
        street_types=street_types,
        details=details,
        noise=_flag_index(mk.get("noise", [])),
        building_part=_flag_index(mk.get("building_part", [])),
        needs_dot={fold(str(x)) for x in mk.get("needs_dot", [])},
        needs_number={fold(str(x)) for x in mk.get("needs_number", [])},
        house_dash_apartment=bool(mk.get("house_dash_apartment", True)),
        province_markers=_flag_index(ad.get("province_markers", [])),
        district_markers=_flag_index(ad.get("district_markers", [])),
        district_blockers={fold(str(x)) for x in ad.get("district_blockers", [])},
        city_prefix=_flag_index(ad.get("city_prefix", [])),
        city_suffix=_flag_index(ad.get("city_suffix", [])),
        settlement_prefix=_flag_index(ad.get("settlement_prefix", [])),
        settlement_suffix=_flag_index(ad.get("settlement_suffix", [])),
        weak_prefixes={fold(str(x)) for x in ad.get("weak_prefixes", [])},
        rural_okrug=_flag_index(ad.get("rural_okrug", [])),
        lm_prepositions=_flag_index(lm.get("prepositions", [])),
        lm_objects=_flag_index(lm.get("objects", [])),
        lm_brands=_flag_index(lm.get("brands", [])),
        lm_numbered={fold(str(x)) for x in lm.get("numbered_objects", [])},
        confidence=conf,
        arbiter=arb,
        org_forms={fold(str(x)) for x in mk.get("org_forms", [])},
        org_forms_upper={fold(str(x)) for x in mk.get("org_forms_upper", [])},
        number_name_words={fold(str(x)) for x in mk.get("number_name_words", [])},
        historical_provinces={str(k): {str(v) for v in vs} for k, vs in ad.get("historical_provinces", {}).items()},
    )


@lru_cache(maxsize=1)
def get_rules() -> Rules:
    return load_rules()


def all_marker_words() -> set[str]:
    r = get_rules()
    out: set[str] = set()
    for idx in (
        r.street_types,
        r.details,
        r.noise,
        r.building_part,
        r.province_markers,
        r.district_markers,
        r.city_prefix,
        r.city_suffix,
        r.settlement_prefix,
        r.settlement_suffix,
        r.rural_okrug,
        r.lm_prepositions,
        r.lm_objects,
        r.lm_brands,
    ):
        out |= idx.words()
    return out
