"""Порядок шагов пайплайна (docs/ARCHITECTURE.md)."""

from __future__ import annotations

from .base import Step


def build_default(tagger_mode: str | None = None) -> list[Step]:
    """tagger_mode: off | shadow | on | only (по умолчанию config.tagger_mode(), переменная JANA_TAGGER)."""
    from .. import config
    from ..reference.store import get_store
    from ..rules_loader import get_rules
    from .admin import Admin
    from .bilingual import SplitBilingual
    from .clean import Clean
    from .confidence import Confidence
    from .details import Details
    from .landmark import Landmark
    from .layout import Layout
    from .leftover import Leftover
    from .numbers import Numbers
    from .parts import AttachBuilding, Parts
    from .reference_step import Reference
    from .street import Street
    from .tokenize import Tokenize

    store, rules = get_store(), get_rules()
    mode = tagger_mode or config.tagger_mode()
    steps: list[Step] = [
        Layout(store, rules),
        Clean(),
        Tokenize(),
        SplitBilingual(),
        Parts(rules),
        Admin(store, rules),
        Details(rules),
        Street(store, rules),
        Landmark(rules),
        Numbers(rules),
        AttachBuilding(),
        Leftover(store),
    ]
    if mode != "off":
        from .arbiter import Arbiter
        from .tagger import ModelTag, get_tagger

        steps += [ModelTag(get_tagger(), mode), Arbiter(store, rules, mode)]
    return [*steps, Reference(store, rules), Confidence(rules)]
