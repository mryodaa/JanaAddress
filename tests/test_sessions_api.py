"""API сессий для UI: загрузка, прогресс, фильтры, правка, экспорт."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jana_address import config
from jana_address.api.app import create_app
from jana_address.models import OUTPUT_KEYS

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(config, "EDITS_DB", tmp_path / "edits.sqlite")
    with TestClient(create_app()) as c:
        yield c


def wait_done(c: TestClient, sid: str) -> dict:
    for _ in range(200):
        s = c.get(f"/api/v1/sessions/{sid}").json()
        if s["status"] != "processing":
            return s
        time.sleep(0.05)
    raise AssertionError("сессия не обработалась")


def test_session_flow(client: TestClient) -> None:
    raw = (FIX / "sample_input.json").read_bytes()
    r = client.post("/api/v1/sessions?name=sample.json", files={"file": ("sample.json", raw, "application/json")})
    assert r.status_code == 200
    sid, total = r.json()["id"], r.json()["total"]
    s = wait_done(client, sid)
    assert s["status"] == "done" and s["processed"] == total
    assert sum(s["summary"]["histogram"]) == total

    items = client.get(f"/api/v1/sessions/{sid}/records").json()["items"]
    assert len(items) == total and items[0]["fields"]
    unc = client.get(f"/api/v1/sessions/{sid}/records?uncertain=true").json()["total"]
    assert unc == s["summary"]["uncertain"]
    assert client.get(f"/api/v1/sessions/{sid}/records?q=Курильская").json()["total"] == 1

    rec = client.get(f"/api/v1/sessions/{sid}/records/2").json()
    assert rec["trace"]
    p = client.patch(f"/api/v1/sessions/{sid}/records/2", json={"fields": {"house": "9А", "landmark": None}})
    assert p.status_code == 200
    body = p.json()
    assert body["reviewed"] and body["record"]["house"] == "9А" and body["fields"]["house"]["source"] == "manual"

    exp = client.get(f"/api/v1/sessions/{sid}/export")
    out = json.loads(exp.content)
    assert [o["id"] for o in out] == [i["id"] for i in json.loads(raw)]
    assert all(tuple(o) == OUTPUT_KEYS for o in out)
    assert out[2]["house"] == "9А"


def test_patch_back_to_parsed_value_removes_edit(client: TestClient) -> None:
    sid = client.post("/api/v1/sessions", json=[{"id": "1", "raw_address": "ул Абая 10"}]).json()["id"]
    wait_done(client, sid)
    client.patch(f"/api/v1/sessions/{sid}/records/0", json={"fields": {"house": "11"}})
    r = client.patch(f"/api/v1/sessions/{sid}/records/0", json={"fields": {"house": "10"}}).json()
    assert r["edited"] == []
