from __future__ import annotations

import json
from pathlib import Path

from jana_address import cli

FIX = Path(__file__).parent / "fixtures"


def test_cli_roundtrip(tmp_path: Path) -> None:
    out = tmp_path / "out.json"
    assert cli.main([str(FIX / "sample_input.json"), str(out)]) == 0
    inp = json.loads((FIX / "sample_input.json").read_text(encoding="utf-8"))
    res = json.loads(out.read_text(encoding="utf-8"))
    assert [r["id"] for r in res] == [r["id"] for r in inp]
    assert [r["raw_address"] for r in res] == [r["raw_address"] for r in inp]
