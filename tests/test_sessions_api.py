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
    # запись с пустым raw_address (t_012) не разбирается: вне сводки, в своём фильтре
    assert s["summary"]["no_address"] == 1
    assert sum(s["summary"]["histogram"]) == total - 1
    blank = client.get(f"/api/v1/sessions/{sid}/records?no_address=true").json()
    assert blank["total"] == 1 and blank["items"][0]["record"]["id"] == "t_012"

    items = client.get(f"/api/v1/sessions/{sid}/records").json()["items"]
    assert len(items) == total and items[0]["fields"]
    unc = client.get(f"/api/v1/sessions/{sid}/records?uncertain=true&no_address=false").json()["total"]
    assert unc == s["summary"]["uncertain"]
    assert client.get(f"/api/v1/sessions/{sid}/records?q=Курильская").json()["total"] == 1

    rec = client.get(f"/api/v1/sessions/{sid}/records/2").json()
    assert rec["trace"]
    p = client.patch(f"/api/v1/sessions/{sid}/records/2", json={"fields": {"house": "9А", "landmark": None}})
    assert p.status_code == 200
    body = p.json()
    assert body["reviewed"] and body["record"]["house"] == "9А" and body["fields"]["house"]["source"] == "manual"
    summ = client.get(f"/api/v1/sessions/{sid}").json()["summary"]
    assert summ["confident"] + summ["uncertain"] == total - 1 and summ["edited"] == 1
    assert sum(summ["histogram_uncertain"]) == summ["uncertain"]
    # значок на вкладке = длина списка «неуверенные», убывает по мере проверки
    todo = client.get(f"/api/v1/sessions/{sid}/records?uncertain=true&reviewed=false&no_address=false").json()["total"]
    assert summ["to_review"] == todo
    fixed = client.get(f"/api/v1/sessions/{sid}/records?edited=true").json()
    assert fixed["total"] == 1 and fixed["items"][0]["idx"] == 2
    assert client.get(f"/api/v1/sessions/{sid}/records?edited=false").json()["total"] == total - 1

    exp = client.get(f"/api/v1/sessions/{sid}/export")
    out = json.loads(exp.content)
    assert [o["id"] for o in out] == [i["id"] for i in json.loads(raw)]
    assert all(tuple(o) == OUTPUT_KEYS for o in out)
    assert out[2]["house"] == "9А"


def test_threshold_override(client: TestClient) -> None:
    # порог из настроек UI: сводка и фильтр «неуверенные» считаются по нему, сохранённый в сессии не меняется
    raw = (FIX / "sample_input.json").read_bytes()
    sid = client.post("/api/v1/sessions", files={"file": ("s.json", raw, "application/json")}).json()["id"]
    base = wait_done(client, sid)["summary"]
    low = client.get(f"/api/v1/sessions/{sid}?threshold=0").json()["summary"]
    high = client.get(f"/api/v1/sessions/{sid}?threshold=1").json()["summary"]
    assert low["threshold"] == 0 and low["uncertain"] == 0
    assert high["uncertain"] >= base["uncertain"] >= low["uncertain"]
    unc = client.get(f"/api/v1/sessions/{sid}/records?uncertain=true&no_address=false&threshold=1").json()["total"]
    assert unc == high["uncertain"]
    assert client.get(f"/api/v1/sessions/{sid}").json()["summary"]["threshold"] == base["threshold"]
    assert client.get(f"/api/v1/sessions/{sid}?threshold=1.5").status_code == 422


def test_upload_without_addresses_rejected(client: TestClient) -> None:
    # не тот файл: записи есть, адресов нет ни в одной; пакет из пустых записей не создаётся
    r = client.post("/api/v1/sessions", json=[{"id": "1", "address": "ул Абая 10"}, {"id": "2", "raw_address": " "}])
    assert r.status_code == 422
    assert "raw_address" in r.json()["detail"] and "address" in r.json()["detail"]
    assert client.get("/api/v1/sessions").json() == []


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
    sessions._process("missing")
    assert calls == []


def _upload(c: TestClient, raws: list[str]) -> str:
    sid = c.post("/api/v1/sessions", json=[{"id": str(i), "raw_address": r} for i, r in enumerate(raws)]).json()["id"]
    wait_done(c, sid)
    return sid


def test_uncertain_counter_follows_review(client: TestClient) -> None:
    """Плитка «неуверенные» и список, который она открывает, показывают одно число и убывают по мере проверки."""
    sid = _upload(client, ["ул Абая 10", "xyz qwe", "zz 1 2 3 абв", "г. Алматы, ул. Абая 150, кв 23"])
    s = client.get(f"/api/v1/sessions/{sid}").json()["summary"]
    assert s["uncertain"] == s["to_review"] >= 1
    first = client.get(f"/api/v1/sessions/{sid}/records?uncertain=true&reviewed=false").json()["items"][0]
    client.patch(f"/api/v1/sessions/{sid}/records/{first['idx']}", json={"reviewed": True})
    s2 = client.get(f"/api/v1/sessions/{sid}").json()["summary"]
    assert s2["uncertain"] == s2["to_review"] == s["uncertain"] - 1
    assert s2["confident"] + s2["uncertain"] == 4
    assert sum(s2["histogram_uncertain"]) == s2["uncertain"]
    # исправленное поле считается как manual
    client.patch(f"/api/v1/sessions/{sid}/records/0", json={"fields": {"house": "11"}})
    assert client.get(f"/api/v1/sessions/{sid}").json()["summary"]["sources"].get("manual") == 1


def test_records_paging_sort_and_position(client: TestClient) -> None:
    raws = [f"ул Абая {n}" for n in (5, 30, 7, 100, 1, 12)]
    sid = _upload(client, raws)
    page = client.get(f"/api/v1/sessions/{sid}/records?limit=2&offset=2").json()
    assert page["total"] == 6 and page["offset"] == 2 and [i["idx"] for i in page["items"]] == [2, 3]
    # по исходной строке: числа по значению, не по символам
    order = [i["idx"] for i in client.get(f"/api/v1/sessions/{sid}/records?sort=raw").json()["items"]]
    assert order == [4, 0, 2, 5, 1, 3]
    desc = [i["idx"] for i in client.get(f"/api/v1/sessions/{sid}/records?sort=raw&dir=desc").json()["items"]]
    assert desc == order[::-1]
    pos = client.get(f"/api/v1/sessions/{sid}/records/position?idx=5&sort=raw").json()
    assert pos == {"position": 3}
    assert client.get(f"/api/v1/sessions/{sid}/records/position?idx=99").json() == {"position": None}
    assert client.get(f"/api/v1/sessions/{sid}/records?sort=bogus").status_code == 422
    assert client.get(f"/api/v1/sessions/{sid}/records?limit=100000").status_code == 422


def test_search_is_case_insensitive_and_literal(client: TestClient) -> None:
    sid = _upload(client, ["ул Абая 10", "ул Сейфуллина 5"])
    assert client.get(f"/api/v1/sessions/{sid}/records?q=АБАЯ").json()["total"] == 1
    # % и _ ищутся как символы, а не как шаблон LIKE; ключи JSON не совпадают
    assert client.get(f"/api/v1/sessions/{sid}/records?q=%25").json()["total"] == 0
    assert client.get(f"/api/v1/sessions/{sid}/records?q=street_name").json()["total"] == 0


def test_session_errors(client: TestClient) -> None:
    assert client.get("/api/v1/sessions/nope/records").status_code == 404
    assert client.get("/api/v1/sessions/nope/export").status_code == 404
    sid = _upload(client, ["ул Абая 10"])
    r = client.patch(f"/api/v1/sessions/{sid}/records/0", json={"fields": {"hous": "1"}})
    assert r.status_code == 422


def test_export_waits_for_processing(client: TestClient) -> None:
    from jana_address import sessions

    sid = _upload(client, ["ул Абая 10"])
    with sessions.connect() as con:
        con.execute("UPDATE sessions SET status = 'processing' WHERE id = ?", (sid,))
    assert client.get(f"/api/v1/sessions/{sid}/export").status_code == 409


def test_interrupted_session_resumes(client: TestClient) -> None:
    """Перезапуск посреди разбора: незаконченный пакет дорабатывается, а не висит в processing."""
    from jana_address import sessions

    sid = _upload(client, ["ул Абая 10", "ул Абая 11"])
    with sessions.connect() as con:
        con.execute("UPDATE records SET parsed = NULL, confidence = NULL WHERE session_id = ? AND idx = 1", (sid,))
        con.execute("UPDATE sessions SET status = 'processing', processed = 1 WHERE id = ?", (sid,))
    assert sessions.resume_pending() == 1
    s = wait_done(client, sid)
    assert s["status"] == "done" and s["processed"] == 2
    assert client.get(f"/api/v1/sessions/{sid}/records/1").json()["record"]["house"] == "11"


def test_bucket_filter_matches_histogram(client: TestClient) -> None:
    """Клик по столбцу графика: в списке ровно столько записей, сколько в столбце."""
    sid = _upload(client, ["ул Абая 10", "xyz qwe", "zz 1 2 3 абв", "г. Алматы, ул. Абая 150, кв 23", "Абая"])
    hist = client.get(f"/api/v1/sessions/{sid}").json()["summary"]["histogram"]
    for b, n in enumerate(hist):
        r = client.get(f"/api/v1/sessions/{sid}/records?bucket={b}").json()
        assert r["total"] == n, (b, n, r["total"])
    assert client.get(f"/api/v1/sessions/{sid}/records?bucket=10").status_code == 422


def test_export_default_is_full_batch_unchanged(client: TestClient) -> None:
    """Без параметров экспорт прежний: весь пакет, все ключи ответа жюри, форма входа."""
    raws = ["ул Абая 10", "г. Алматы, ул. Абая 150, кв 23"]
    sid = _upload(client, raws)
    r = client.get(f"/api/v1/sessions/{sid}/export")
    out = json.loads(r.content)
    assert [o["id"] for o in out] == ["0", "1"] and all(tuple(o) == OUTPUT_KEYS for o in out)
    assert r.headers["content-disposition"].endswith(f'jana_address_{sid}.json"')


def test_export_filtered_fields_and_csv(client: TestClient) -> None:
    sid = _upload(client, ["ул Абая 10", "xyz qwe", "г. Алматы, ул. Абая 150, кв 23"])
    client.patch(f"/api/v1/sessions/{sid}/records/0", json={"fields": {"house": "11"}})
    # только исправленные, выбранные поля, с источником
    r = client.get(f"/api/v1/sessions/{sid}/export?edited=true&fields=house,street_name&sources=true")
    out = json.loads(r.content)
    assert len(out) == 1 and list(out[0]) == ["id", "raw_address", "street_name", "house", "_sources"]
    assert out[0]["house"] == "11" and out[0]["_sources"]["house"] == "manual"
    assert "_filtered.json" in r.headers["content-disposition"]
    # поиск + CSV для Excel
    c = client.get(f"/api/v1/sessions/{sid}/export?q=АБАЯ&format=csv&fields=house")
    assert c.headers["content-type"].startswith("text/csv")
    text = c.content.decode("utf-8")
    assert text.startswith("\ufeff")
    lines = text.lstrip("\ufeff").splitlines()
    assert lines[0] == "id;raw_address;house" and len(lines) == 3
    assert client.get(f"/api/v1/sessions/{sid}/export?fields=hous").status_code == 422


def test_skip_confirm_undo_and_progress(client: TestClient) -> None:
    """Отложить: запись уходит из очереди «неуверенные» в отложенные; подтвердить снимает «отложено»;
    подтверждение и откладывание снимаются; прогресс проверки считается по изначально неуверенным."""
    sid = _upload(client, ["xyz qwe", "zz 1 2 3 абв", "ул Абая 10"])
    base = f"/api/v1/sessions/{sid}"
    s0 = client.get(base).json()["summary"]
    queue = client.get(f"{base}/records?uncertain=true&reviewed=false&skipped=false").json()["items"]
    assert s0["to_review"] == len(queue) >= 2 and s0["review_total"] == len(queue) and s0["review_done"] == 0
    a, b = queue[0]["idx"], queue[1]["idx"]

    r = client.patch(f"{base}/records/{a}", json={"skipped": True}).json()
    assert r["skipped"] and not r["reviewed"]
    s1 = client.get(base).json()["summary"]
    assert s1["to_review"] == s0["to_review"] - 1 and s1["skipped"] == 1 and s1["review_done"] == 0
    assert [i["idx"] for i in client.get(f"{base}/records?skipped=true").json()["items"]] == [a]

    # подтверждение отложенной: снимает «отложено», идёт в прогресс
    r = client.patch(f"{base}/records/{a}", json={"reviewed": True}).json()
    assert r["reviewed"] and not r["skipped"]
    s2 = client.get(base).json()["summary"]
    assert s2["skipped"] == 0 and s2["review_done"] == 1

    # снять подтверждение: снова в очереди
    r = client.patch(f"{base}/records/{a}", json={"reviewed": False}).json()
    assert not r["reviewed"]
    assert client.get(base).json()["summary"]["to_review"] == s0["to_review"]

    # отложить подтверждённую: она снова непроверенная; вернуть в очередь
    client.patch(f"{base}/records/{b}", json={"reviewed": True})
    r = client.patch(f"{base}/records/{b}", json={"skipped": True}).json()
    assert r["skipped"] and not r["reviewed"]
    r = client.patch(f"{base}/records/{b}", json={"skipped": False}).json()
    assert not r["skipped"] and not r["reviewed"]
    assert client.get(base).json()["summary"]["to_review"] == s0["to_review"]
