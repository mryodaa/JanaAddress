"""ТЗ, раздел 7: в репозитории и образе нет структуры, индексирующей целые строки из train.json.

Проверяем:
  1) справочник не содержит колонок raw_address/address и значений, похожих на целый адрес;
  2) если data/train.json есть локально, ни одна его строка (от 15 символов) не встречается подстрокой
     ни в одном файле репозитория, ни в текстовых значениях reference.sqlite;
  3) пайплайн не кэширует результат по целой строке (нет lru_cache на функциях разбора).
"""

from __future__ import annotations

import inspect
import re
import sqlite3
from pathlib import Path

import pytest

from jana_address import config, io_format
from jana_address.pipeline import runner

ROOT = Path(__file__).resolve().parents[1]
TRAIN = ROOT / "data" / "train.json"
SKIP_DIRS = {
    ".git",
    ".venv",
    "node_modules",
    "data",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "var",
    "cache",
}
TEXT_EXT = {".py", ".json", ".yaml", ".yml", ".md", ".txt", ".ts", ".tsx", ".js", ".html", ".css", ".sql", ".csv"}


def ref_text_values() -> list[str]:
    con = sqlite3.connect(f"file:{config.REFERENCE_DB.as_posix()}?mode=ro", uri=True)
    out: list[str] = []
    for (table,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name != 'meta'"):
        cols = [r[1] for r in con.execute(f"PRAGMA table_info({table})")]
        assert not {"raw_address", "address", "raw"} & set(cols), f"{table} хранит целые адреса"
        for row in con.execute(f"SELECT * FROM {table}"):
            out.extend(v for v in row if isinstance(v, str))
    return out


def test_reference_has_no_address_like_values() -> None:
    pattern = re.compile(r"\d.*,.*\d|кв\.?\s*\d|,.*,")  # два числа через запятую, «кв 5», две запятые
    bad = [v for v in ref_text_values() if pattern.search(v) and len(v) > 25]
    assert not bad, bad[:5]


def test_no_whole_string_cache() -> None:
    src = inspect.getsource(runner)
    assert "lru_cache" not in src and "cache" not in src.replace("cached", "")


def repo_files() -> list[Path]:
    files = []
    for p in ROOT.rglob("*"):
        if any(part in SKIP_DIRS for part in p.relative_to(ROOT).parts):
            continue
        if p.is_file() and p.suffix in TEXT_EXT:
            files.append(p)
    return files


@pytest.mark.skipif(not TRAIN.exists(), reason="data/train.json не выдан локально")
def test_train_strings_not_in_repo_or_reference() -> None:
    records, _ = io_format.loads(TRAIN.read_bytes())
    needles = {r["raw_address"].strip() for r in records if isinstance(r.get("raw_address"), str)}
    needles = {n for n in needles if len(n) >= 15}
    haystacks = [p.read_text(encoding="utf-8", errors="ignore") for p in repo_files()]
    haystacks.append("\n".join(ref_text_values()))
    leaked = [n for n in needles if any(n in h for h in haystacks)]
    assert not leaked, f"{len(leaked)} строк train.json найдено в репозитории: {leaked[:3]}"
