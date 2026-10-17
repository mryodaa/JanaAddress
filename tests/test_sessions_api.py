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
    summ = client.get(f"/api/v1/sessions/{sid}").json()["summary"]
    assert summ["confident"] + summ["uncertain"] == total and summ["edited"] == 1
    assert sum(summ["histogram_uncertain"]) == summ["uncertain"]
    # значок на вкладке = длина списка «неуверенные», убывает по мере проверки
    todo = client.get(f"/api/v1/sessions/{sid}/records?uncertain=true&reviewed=false").json()["total"]
    assert summ["to_review"] == todo
    fixed = client.get(f"/api/v1/sessions/{sid}/records?edited=true").json()
    assert fixed["total"] == 1 and fixed["items"][0]["idx"] == 2
    assert client.get(f"/api/v1/sessions/{sid}/records?edited=false").json()["total"] == total - 1

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


def test_session_without_threshold_gets_it_from_trace(client: TestClient) -> None:
    # сессия до сохранения порога: модель confidence видна по trace; старую линейную мерим старым порогом
    from jana_address import sessions

    sid = client.post("/api/v1/sessions", json=[{"id": "1", "raw_address": "ул Абая 10"}]).json()["id"]
    wait_done(client, sid)
    assert client.get(f"/api/v1/sessions/{sid}").json()["summary"]["threshold"] == config.UNCERTAIN_THRESHOLD

    with sessions.connect() as con:
        con.execute("UPDATE sessions SET threshold = NULL WHERE id = ?", (sid,))
    assert client.get(f"/api/v1/sessions/{sid}").json()["summary"]["threshold"] == config.UNCERTAIN_THRESHOLD

    with sessions.connect() as con:
        (parsed,) = con.execute("SELECT parsed FROM records WHERE session_id = ?", (sid,)).fetchone()
        p = json.loads(parsed)
        for t in p["trace"]:
            t["changes"].pop("logit", None)  # так выглядел trace линейной модели
        con.execute("UPDATE records SET parsed = ?, confidence = 0.9 WHERE session_id = ?", (json.dumps(p), sid))
        con.execute("UPDATE sessions SET threshold = NULL WHERE id = ?", (sid,))
    summ = client.get(f"/api/v1/sessions/{sid}").json()["summary"]
    assert summ["threshold"] == sessions.LEGACY_THRESHOLD and summ["uncertain"] == 0
    assert client.get(f"/api/v1/sessions/{sid}/records?uncertain=true").json()["total"] == 0


def test_old_db_without_threshold_column_migrates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import sqlite3

    from jana_address import sessions

    db = tmp_path / "old.sqlite"
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE sessions (id TEXT PRIMARY KEY, name TEXT, created_at REAL, status TEXT, total INTEGER,"
        " processed INTEGER, container TEXT, error TEXT, seconds REAL)"
    )
    con.execute("INSERT INTO sessions VALUES ('old', 'x', 0, 'done', 0, 0, '{}', NULL, NULL)")
    con.commit()
    con.close()
    monkeypatch.setattr(config, "EDITS_DB", db)
    s = sessions.get_session("old")
    assert s is not None and s["summary"]["threshold"] == sessions.LEGACY_THRESHOLD


def test_deleted_session_stops_processing(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from jana_address import engine, sessions

    calls: list[int] = []
    monkeypatch.setattr(engine, "parse_many", lambda chunk, explain=False: calls.append(len(chunk)) or [])
    recs = [{"id": str(i), "raw_address": "ул Абая 10"} for i in range(sessions.CHUNK * 3)]
    sessions._process("missing", recs)
    assert calls == []
