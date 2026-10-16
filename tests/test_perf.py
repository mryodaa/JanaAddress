"""ТЗ: не больше 5 минут на 1000 записей (целимся в секунды), старт контейнера меньше 3 минут."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

import pytest
from fastapi.testclient import TestClient
from scripts.benchmark import synthetic_records

from jana_address import config, engine

needs_model = pytest.mark.skipif(not config.TAGGER_MODEL.exists(), reason="models/tagger.onnx не собран")


@pytest.mark.perf
def test_1000_records_fast() -> None:
    records = synthetic_records(1000, seed=1)
    engine.get_pipeline()  # загрузка справочника не входит в замер
    t0 = time.perf_counter()
    out = engine.parse_many(records)
    dt = time.perf_counter() - t0
    assert len(out) == 1000
    print(f"\n1000 записей: {dt:.2f} с")
    assert dt < 30, f"1000 записей за {dt:.1f} с"


@pytest.fixture
def hybrid(monkeypatch: pytest.MonkeyPatch) -> object:
    monkeypatch.setenv("JANA_TAGGER", "on")
    engine.reset()
    yield
    engine.reset()


@pytest.mark.perf
@needs_model
def test_startup_with_model() -> None:
    """Холодный старт в отдельном процессе: справочник + модель + прогрев. Регламент 3 минуты, у нас бюджет 60 с."""
    code = (
        "import time, json; t0 = time.perf_counter(); from jana_address import engine; engine.get_pipeline(); "
        "print(json.dumps({'sec': time.perf_counter() - t0, 'tagger': engine.info()['tagger']}))"
    )
    env = {**os.environ, "JANA_TAGGER": "on", "PYTHONPATH": str(config.PACKAGE_DIR.parent)}
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=180, check=True)
    info = json.loads(out.stdout.strip().splitlines()[-1])
    print(f"\nхолодный старт со справочником и моделью: {info['sec']:.1f} с, прогрев {info['tagger']['warmup_ms']} мс")
    assert info["tagger"]["loaded"] and info["tagger"]["mode"] == "on"
    assert info["sec"] < 60


@pytest.mark.perf
@needs_model
def test_1000_records_hybrid_via_api(hybrid: object) -> None:
    from jana_address.api.app import create_app

    records = synthetic_records(1000, seed=2)
    with TestClient(create_app()) as client:
        t0 = time.perf_counter()
        r = client.post("/api/v1/parse/batch", content=json.dumps(records, ensure_ascii=False).encode("utf-8"))
        dt = time.perf_counter() - t0
    assert r.status_code == 200 and len(r.json()) == 1000
    assert os.environ["JANA_TAGGER"] == "on"
    print(f"\n1000 записей hybrid через API: {dt:.2f} с")
    assert dt < 30, f"1000 записей hybrid за {dt:.1f} с"


@pytest.mark.perf
def test_1000_latin_and_layout_records_fast() -> None:
    """Латиница и английская раскладка идут через шаг layout (поиск слов в справочнике): тоже секунды."""
    raws = ["Fkvfns ek f,fz 150 rd 5", "Almaty, ul. Abaya 150, kv 5", "Astana, Mangilik El 55, flat 191", "ue/ Fcnfyf"]
    records = [{"id": i, "raw_address": raws[i % len(raws)]} for i in range(1000)]
    engine.get_pipeline()
    t0 = time.perf_counter()
    out = engine.parse_many(records)
    dt = time.perf_counter() - t0
    assert len(out) == 1000 and out[0]["street_name"] == "абая"
    print(f"\n1000 записей латиницей и в раскладке: {dt:.2f} с")
    assert dt < 30
