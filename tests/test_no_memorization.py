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
from collections.abc import Iterator
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


def ref_text_values() -> Iterator[str]:
    """Потоком: в справочнике > 1 млн домов, список всех строк не помещается в память рядом с Docker/WSL."""
    con = sqlite3.connect(f"file:{config.REFERENCE_DB.as_posix()}?mode=ro", uri=True)
    tables = [t for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name != 'meta'")]
    for table in tables:
        cols = [r[1] for r in con.execute(f"PRAGMA table_info({table})")]
        assert not {"raw_address", "address", "raw"} & set(cols), f"{table} хранит целые адреса"
        for row in con.execute(f"SELECT * FROM {table}"):
            yield from (v for v in row if isinstance(v, str))
    con.close()


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


# ---------- теггер: модель обобщает, а не запоминает; в артефактах нет строк входа ----------
TAGGER_SOURCES = (
    "tagger/runtime.py",
    "tagger/features.py",
    "tagger/crf.py",
    "pipeline/tagger.py",
    "pipeline/arbiter.py",
)
needs_model = pytest.mark.skipif(not config.TAGGER_MODEL.exists(), reason="models/tagger.onnx не собран")


def test_no_whole_string_cache_in_tagger() -> None:
    for rel in TAGGER_SOURCES:
        src = (config.PACKAGE_DIR / rel).read_text(encoding="utf-8")
        assert "lru_cache" not in src and "functools.cache" not in src, rel


@needs_model
def test_tagger_meta_has_only_chars_labels_numbers() -> None:
    """В tagger_meta.json только словарь символов, метки, числа и служебные строки: ни одной строки адреса."""
    import json

    meta = json.loads(config.TAGGER_META.read_text(encoding="utf-8"))
    assert all(len(c) == 1 for c in meta["chars"])
    strings: list[str] = []

    def walk(x: object) -> None:
        if isinstance(x, str):
            strings.append(x)
        elif isinstance(x, dict):
            for k, v in x.items():
                strings.append(str(k))
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk({k: v for k, v in meta.items() if k != "chars"})
    assert max(len(s) for s in strings) <= 80
    assert not [s for s in strings if re.search(r"\d.*,.*\d|кв\.?\s*\d|ул\.", s)]


@needs_model
def test_onnx_has_no_text() -> None:
    """В весах ONNX нет текста (ни одной кириллической строки длиннее 6 символов): только числа и имена узлов."""
    data = config.TAGGER_MODEL.read_bytes()
    assert not re.search(rb"(?:[\xd0\xd1][\x80-\xbf]){6,}", data)


@needs_model
def test_tagger_generalizes_to_unseen_toponyms() -> None:
    """Улицы и населённые пункты, которых не было в обучении (split=unseen по хешу id): span-F1 близок к val.
    Набор генерируется здесь же новым seed, поэтому модель не могла видеть ни строк, ни этих топонимов."""
    import random

    from scripts.synth.builder import Builder, Ref
    from training.data import span_f1

    from jana_address.tagger.runtime import load

    tagger = load(config.TAGGER_MODEL, config.TAGGER_META)
    assert tagger is not None
    b = Builder(Ref(config.SYNTH_DB, "unseen"), random.Random(777), chaos=True)
    recs = [b.record(i) for i in range(400)]
    preds = tagger.predict([r["raw_address"] for r in recs])
    gold = [[(s, min(e, tagger.max_len), lab) for s, e, lab in r["_spans"] if s < tagger.max_len] for r in recs]
    pred = [[(s.start, s.end, s.label) for s in p.spans] for p in preds]
    f1 = float(span_f1(gold, pred)["f1"])  # type: ignore[arg-type]
    val = float(tagger.meta["metrics"]["val_span_f1"])
    print(f"\nspan-F1 на невиданных топонимах {f1:.4f} (val {val:.4f})")
    assert f1 >= 0.95 and f1 >= val - 0.03
