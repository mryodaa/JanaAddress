from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jana_address.api.app import create_app
from jana_address.models import OUTPUT_KEYS

FIX = Path(__file__).parent / "fixtures"


def client() -> TestClient:
    return TestClient(create_app())


def test_health() -> None:
    with client() as c:
        r = c.get("/api/v1/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


def test_batch_json_body_as_is() -> None:
    raw = (FIX / "sample_input.json").read_bytes()
    with client() as c:
        r = c.post("/api/v1/parse/batch", content=raw, headers={"content-type": "application/json"})
    assert r.status_code == 200
    out = r.json()
    inp = json.loads(raw)
    assert [o["id"] for o in out] == [i["id"] for i in inp]
    assert [o["raw_address"] for o in out] == [i["raw_address"] for i in inp]
    assert all(tuple(o.keys()) == OUTPUT_KEYS for o in out)


def test_batch_multipart_file() -> None:
    raw = (FIX / "sample_input.json").read_bytes()
    with client() as c:
        r = c.post("/api/v1/parse/batch", files={"file": ("sample_input.json", raw, "application/json")})
    assert r.status_code == 200
    assert len(r.json()) == len(json.loads(raw))


def test_batch_explain_adds_fields() -> None:
    with client() as c:
        r = c.post("/api/v1/parse/batch?explain=true", json=[{"id": "1", "raw_address": "ул Абая 1"}])
    assert r.status_code == 200
    rec = r.json()[0]
    assert "trace" in rec and "fields" in rec


def test_batch_bad_payload() -> None:
    with client() as c:
        r = c.post("/api/v1/parse/batch", content=b"{not json", headers={"content-type": "application/json"})
    assert r.status_code == 422


def test_parse_one() -> None:
    with client() as c:
        r = c.post("/api/v1/parse", json={"raw_address": "ул Абая 1"})
    assert r.status_code == 200
    assert r.json()["raw_address"] == "ул Абая 1"


def test_openapi_available() -> None:
    with client() as c:
        r = c.get("/openapi.json")
    assert r.status_code == 200
    assert "/api/v1/parse/batch" in r.json()["paths"]


def test_batch_lone_surrogate_answers_every_record() -> None:
    body = '[{"id":"s","raw_address":"\\ud800 Абая 1"},{"id":"t","raw_address":"x"}]'.encode()
    with client() as c:
        r = c.post("/api/v1/parse/batch", content=body, headers={"content-type": "application/json"})
    assert r.status_code == 200
    out = r.json()
    assert [o["id"] for o in out] == ["s", "t"]
    assert out[0]["raw_address"] == json.loads(body)[0]["raw_address"]


def test_unknown_tagger_mode_fails_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    """Опечатка в JANA_TAGGER не должна молча давать режим по умолчанию."""
    from jana_address import config

    monkeypatch.setenv("JANA_TAGGER", "of")
    with pytest.raises(ValueError, match="JANA_TAGGER"):
        config.tagger_mode()
    monkeypatch.setenv("JANA_TAGGER", "OFF ")
    assert config.tagger_mode() == "off"


def test_unknown_api_path_is_json_404() -> None:
    with client() as c:
        r = c.get("/api/v1/nonexistent")
        assert r.status_code == 404 and r.json() == {"detail": "Not Found"}
        assert c.post("/api/v1/nonexistent").status_code in (404, 405)


def test_deeply_nested_json_is_422() -> None:
    with client() as c:
        r = c.post("/api/v1/parse/batch", content=b"[" * 100_000, headers={"content-type": "application/json"})
    assert r.status_code == 422


def test_jsonl_batch_is_ndjson() -> None:
    body = '{"id":"1","raw_address":"ул Абая 1"}\n{"id":"2","raw_address":"ул Абая 2"}\n'.encode()
    with client() as c:
        r = c.post("/api/v1/parse/batch", content=body, headers={"content-type": "application/json"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/x-ndjson")
    assert [json.loads(x)["id"] for x in r.text.splitlines()] == ["1", "2"]
