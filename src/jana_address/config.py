"""Настройки через переменные окружения (префикс JANA_)."""

from __future__ import annotations

import os
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
REPO_DIR = PACKAGE_DIR.parent.parent


def _path(env: str, default: Path) -> Path:
    return Path(os.environ[env]) if os.environ.get(env) else default


REFERENCE_DB = _path("JANA_REFERENCE_DB", REPO_DIR / "reference" / "reference.sqlite")
EDITS_DB = _path("JANA_EDITS_DB", REPO_DIR / "var" / "edits.sqlite")
RULES_DIR = _path("JANA_RULES_DIR", PACKAGE_DIR / "rules")
STATIC_DIR = _path("JANA_STATIC_DIR", PACKAGE_DIR / "static")

# записи с confidence ниже порога считаются «неуверенными» (фильтр в UI, сводка)
UNCERTAIN_THRESHOLD = float(os.environ.get("JANA_UNCERTAIN_THRESHOLD", "0.6"))
MAX_UPLOAD_MB = int(os.environ.get("JANA_MAX_UPLOAD_MB", "100"))

# посимвольный теггер (docs/ARCHITECTURE.md, «Гибридный разбор»)
MODELS_DIR = _path("JANA_MODELS_DIR", REPO_DIR / "models")
TAGGER_MODEL = MODELS_DIR / "tagger.onnx"
TAGGER_META = MODELS_DIR / "tagger_meta.json"
TAGGER_MODES = ("off", "shadow", "on", "only")
DEFAULT_TAGGER_MODE = "on"  # решение по scripts/compare_modes.py, docs/hybrid_results.md


def tagger_mode() -> str:
    """off: без модели; shadow: модель только в explain/логах; on: арбитраж с правилами;
    only: поля только из модели (для оценки eval --mode tagger). Читается при сборке пайплайна."""
    mode = os.environ.get("JANA_TAGGER", DEFAULT_TAGGER_MODE).strip().lower()
    return mode if mode in TAGGER_MODES else DEFAULT_TAGGER_MODE
