"""Порядок шагов пайплайна (docs/ARCHITECTURE.md)."""

from __future__ import annotations

from .base import Step


def build_default() -> list[Step]:
    from ..reference.store import get_store
    from ..rules_loader import get_rules
    from .admin import Admin
    from .bilingual import SplitBilingual
    from .clean import Clean
    from .confidence import Confidence
    from .details import Details
    from .landmark import Landmark
    from .leftover import Leftover
    from .numbers import Numbers
    from .reference_step import Reference
    from .street import Street
    from .tokenize import Tokenize

    store, rules = get_store(), get_rules()
    return [
        Clean(),
        Tokenize(),
        SplitBilingual(),
        Admin(store, rules),
        Details(rules),
        Street(store, rules),
        Landmark(rules),
        Numbers(rules),
        Leftover(store),
        Reference(store),
        Confidence(rules),
    ]
