"""Схема OpenAPI в openapi.json (из неё фронт генерирует типы: cd frontend && npm run gen:api)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jana_address.api.app import create_app  # noqa: E402

if __name__ == "__main__":
    out = ROOT / "openapi.json"
    out.write_text(json.dumps(create_app().openapi(), ensure_ascii=False, indent=1), encoding="utf-8")
    print(out)
