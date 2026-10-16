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
