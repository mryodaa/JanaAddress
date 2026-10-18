"""Защита при интеграции (docs/SECURITY.md): ключ, Origin, Host, лимиты входа, CSV без формул."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jana_address import config, sessions
from jana_address.api.app import create_app
from jana_address.api.security import host_allowed

BATCH = [{"id": "1", "raw_address": "г. Алматы, ул. Абая 10"}]


def make(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **env: str) -> Iterator[TestClient]:
    monkeypatch.setattr(config, "EDITS_DB", tmp_path / "edits.sqlite")
    for k in ("JANA_API_KEY", "JANA_ALLOWED_HOSTS", "JANA_ALLOWED_ORIGINS"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    with TestClient(create_app()) as c:
        yield c


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    yield from make(monkeypatch, tmp_path)


@pytest.fixture()
def keyed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    yield from make(monkeypatch, tmp_path, JANA_API_KEY="s3cret-key")


def test_default_open_for_batch(client: TestClient) -> None:
    # по умолчанию ничего не мешает вызову батча: ни ключа, ни Host
    r = client.post("/api/v1/parse/batch", json=BATCH, headers={"host": "jana-address:8000"})
    assert r.status_code == 200 and r.json()[0]["id"] == "1"
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
    assert client.get("/api/v1/auth").json() == {"required": False, "ok": True}


def test_cross_site_write_rejected(client: TestClient) -> None:
    evil = {"origin": "https://evil.example"}
    assert client.post("/api/v1/parse/batch", json=BATCH, headers=evil).status_code == 403
    assert client.post("/api/v1/sessions", json=BATCH, headers=evil).status_code == 403
    assert client.post("/api/v1/sessions", json=BATCH, headers={"origin": "null"}).status_code == 403
    # свой интерфейс (Origin = адрес сервиса) и клиенты без Origin проходят
    assert client.post("/api/v1/parse/batch", json=BATCH, headers={"origin": "http://testserver"}).status_code == 200
    # чтение не меняет данных: его закрывает CORS браузера
    assert client.get("/api/v1/sessions", headers=evil).status_code == 200


def test_allowed_origin_from_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for c in make(monkeypatch, tmp_path, JANA_ALLOWED_ORIGINS="https://crm.example"):
        r = c.post("/api/v1/parse/batch", json=BATCH, headers={"origin": "https://crm.example"})
        assert r.status_code == 200


def test_api_key(keyed: TestClient) -> None:
    assert keyed.post("/api/v1/parse/batch", json=BATCH).status_code == 401
    assert keyed.post("/api/v1/parse/batch", json=BATCH, headers={"x-api-key": "wrong"}).status_code == 401
    assert keyed.post("/api/v1/parse/batch", json=BATCH, headers={"x-api-key": "s3cret-key"}).status_code == 200
    bearer = {"authorization": "Bearer s3cret-key"}
    assert keyed.post("/api/v1/parse/batch", json=BATCH, headers=bearer).status_code == 200
    # проверка живости и страница UI без ключа: докер-healthcheck и форма входа
    assert keyed.get("/api/v1/health").status_code == 200
    assert keyed.get("/api/v1/auth").json() == {"required": True, "ok": False}


def test_ui_login_cookie(keyed: TestClient) -> None:
    assert keyed.post("/api/v1/auth", json={"key": "nope"}).status_code == 401
    r = keyed.post("/api/v1/auth", json={"key": "s3cret-key"})
    assert r.status_code == 200
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    # в cookie не сам ключ
    assert "s3cret-key" not in r.headers["set-cookie"]
    assert keyed.get("/api/v1/sessions").status_code == 200
    keyed.delete("/api/v1/auth")
    assert keyed.get("/api/v1/sessions").status_code == 401


def test_allowed_hosts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for c in make(monkeypatch, tmp_path, JANA_ALLOWED_HOSTS="localhost,*.trycloudflare.com"):
        assert c.get("/api/v1/health", headers={"host": "localhost:8000"}).status_code == 200
        assert c.get("/api/v1/health", headers={"host": "a-b.trycloudflare.com"}).status_code == 200
        # DNS rebinding: чужое имя, указывающее на 127.0.0.1
        assert c.get("/api/v1/sessions", headers={"host": "attacker.example"}).status_code == 400


def test_host_patterns() -> None:
    assert host_allowed("anything", ())
    assert host_allowed("[::1]:8000", ("[::1]",))
    assert host_allowed("LOCALHOST", ("localhost",))
    assert not host_allowed("trycloudflare.com.evil.example", ("*.trycloudflare.com",))
    assert not host_allowed("eviltrycloudflare.com", ("*.trycloudflare.com",))


def test_input_limits(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    # целое длиннее лимита Python: ошибка входа (422), а не сервера (500)
    body = '[{"id": ' + "1" * 5000 + ', "raw_address": "Абая 10"}]'
    r = client.post("/api/v1/parse/batch", content=body, headers={"content-type": "application/json"})
    assert r.status_code == 422
    # размер отсекается по Content-Length, до чтения тела
    monkeypatch.setattr(config, "MAX_UPLOAD_MB", 1)
    big = json.dumps([{"id": str(i), "raw_address": "x" * 100} for i in range(12000)])
    r = client.post("/api/v1/parse/batch", content=big, headers={"content-type": "application/json"})
    assert r.status_code == 413


def test_csv_formula_escaped() -> None:
    assert sessions._cell("=HYPERLINK(1)") == "'=HYPERLINK(1)"
    assert sessions._cell("@SUM(A1)") == "'@SUM(A1)"
    assert sessions._cell("ул. Абая 10") == "ул. Абая 10"
    assert sessions._cell(-5) == "-5"
