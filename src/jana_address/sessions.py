"""Сессии UI: загруженный пакет, результаты разбора и ручные правки оператора.

Хранится в отдельной SQLite (config.EDITS_DB, в docker это volume /app/var). Справочник read-only и сюда
не пишется. Правки хранятся поверх результата разбора: экспорт = разбор + правки, источник поля "manual".
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from . import config, engine, io_format
from .models import PARSED_FIELDS

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY, name TEXT, created_at REAL, status TEXT, total INTEGER, processed INTEGER,
    container TEXT, error TEXT, seconds REAL
);
CREATE TABLE IF NOT EXISTS records (
    session_id TEXT NOT NULL, idx INTEGER NOT NULL, rec TEXT NOT NULL, parsed TEXT, edited TEXT,
    reviewed INTEGER NOT NULL DEFAULT 0, confidence REAL, updated_at REAL,
    PRIMARY KEY (session_id, idx)
);
"""
CHUNK = 200
_lock = threading.Lock()


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    config.EDITS_DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(config.EDITS_DB, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        con.executescript(SCHEMA)
        yield con
        con.commit()
    finally:
        con.close()


def _container_json(c: io_format.Container) -> str:
    return json.dumps({"kind": c.kind, "key": c.key, "extra": c.extra}, ensure_ascii=False)


def _container(s: str) -> io_format.Container:
    d = json.loads(s)
    return io_format.Container(d["kind"], d.get("key"), d.get("extra") or {})


def create(records: list[dict[str, Any]], container: io_format.Container, name: str) -> str:
    sid = uuid.uuid4().hex[:12]
    with _lock, connect() as con:
        con.execute(
            "INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?)",
            (sid, name, time.time(), "processing", len(records), 0, _container_json(container), None, None),
        )
        con.executemany(
            "INSERT INTO records (session_id, idx, rec) VALUES (?,?,?)",
            [(sid, i, json.dumps(r, ensure_ascii=False)) for i, r in enumerate(records)],
        )
    threading.Thread(target=_process, args=(sid, records), daemon=True).start()
    return sid


def _process(sid: str, records: list[dict[str, Any]]) -> None:
    t0 = time.perf_counter()
    try:
        for start in range(0, len(records), CHUNK):
            chunk = records[start : start + CHUNK]
            parsed = engine.parse_many(chunk, explain=True)
            with _lock, connect() as con:
                con.executemany(
                    "UPDATE records SET parsed = ?, confidence = ? WHERE session_id = ? AND idx = ?",
                    [
                        (json.dumps(p, ensure_ascii=False), p["confidence"], sid, start + i)
                        for i, p in enumerate(parsed)
                    ],
                )
                con.execute("UPDATE sessions SET processed = ? WHERE id = ?", (start + len(chunk), sid))
        status, err = "done", None
    except Exception as exc:  # pragma: no cover - на случай сбоя справочника
        status, err = "error", repr(exc)
    with _lock, connect() as con:
        con.execute(
            "UPDATE sessions SET status = ?, error = ?, seconds = ? WHERE id = ?",
            (status, err, round(time.perf_counter() - t0, 3), sid),
        )


# ---------- чтение ----------
def _row_to_item(row: sqlite3.Row, full: bool = False) -> dict[str, Any]:
    rec = json.loads(row["rec"])
    parsed = json.loads(row["parsed"]) if row["parsed"] else None
    edited = json.loads(row["edited"]) if row["edited"] else {}
    out = merged(rec, parsed, edited)
    fields = dict(parsed.get("fields", {})) if parsed else {}
    for k in edited:
        fields[k] = {"value": edited[k], "source": "manual", "span": None}
    item: dict[str, Any] = {
        "idx": row["idx"],
        "record": out,
        "fields": fields,
        "edited": sorted(edited),
        "reviewed": bool(row["reviewed"]),
        "unparsed": parsed.get("unparsed", []) if parsed else [],
        "pending": parsed is None,
    }
    if full and parsed:
        item["trace"] = parsed.get("trace", [])
        item["parsed"] = {k: parsed.get(k) for k in PARSED_FIELDS} | {"confidence": parsed.get("confidence")}
    return item


def merged(rec: dict[str, Any], parsed: dict[str, Any] | None, edited: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"id": rec.get("id"), "raw_address": rec.get("raw_address")}
    for f in PARSED_FIELDS:
        out[f] = edited[f] if f in edited else (parsed.get(f) if parsed else None)
    out["confidence"] = parsed.get("confidence", 0.0) if parsed else 0.0
    if edited:
        out["confidence"] = 1.0  # проверено человеком
    return out


def get_session(sid: str) -> dict[str, Any] | None:
    with connect() as con:
        s = con.execute("SELECT * FROM sessions WHERE id = ?", (sid,)).fetchone()
        if s is None:
            return None
        confs = [
            r[0]
            for r in con.execute("SELECT confidence FROM records WHERE session_id = ? AND parsed IS NOT NULL", (sid,))
        ]
        reviewed = con.execute("SELECT count(*) FROM records WHERE session_id = ? AND reviewed = 1", (sid,)).fetchone()[
            0
        ]
        fill: dict[str, int] = dict.fromkeys(PARSED_FIELDS, 0)
        sources: dict[str, int] = {}
        for (p,) in con.execute("SELECT parsed FROM records WHERE session_id = ? AND parsed IS NOT NULL", (sid,)):
            d = json.loads(p)
            for f in PARSED_FIELDS:
                if d.get(f):
                    fill[f] += 1
            for fv in d.get("fields", {}).values():
                src = (fv.get("source") or "").split(":")[0]
                sources[src] = sources.get(src, 0) + 1
    hist = [0] * 10
    for c in confs:
        hist[min(9, int((c or 0) * 10))] += 1
    th = config.UNCERTAIN_THRESHOLD
    return {
        "id": s["id"],
        "name": s["name"],
        "created_at": s["created_at"],
        "status": s["status"],
        "total": s["total"],
        "processed": s["processed"],
        "seconds": s["seconds"],
        "error": s["error"],
        "summary": {
            "threshold": th,
            "uncertain": sum(1 for c in confs if (c or 0) < th),
            "reviewed": reviewed,
            "mean_confidence": round(sum(confs) / len(confs), 3) if confs else None,
            "histogram": hist,
            "fill": fill,
            "sources": sources,
        },
    }


def list_sessions() -> list[dict[str, Any]]:
    with connect() as con:
        rows = con.execute(
            "SELECT id, name, created_at, status, total, processed FROM sessions ORDER BY created_at DESC"
        )
        return [dict(r) for r in rows]


def list_records(
    sid: str, uncertain: bool = False, reviewed: bool | None = None, q: str = "", offset: int = 0, limit: int = 20000
) -> dict[str, Any]:
    where: list[str] = ["session_id = ?"]
    args: list[Any] = [sid]
    if uncertain:
        where.append("(confidence IS NULL OR confidence < ?) AND edited IS NULL")
        args.append(config.UNCERTAIN_THRESHOLD)
    if reviewed is not None:
        where.append("reviewed = ?")
        args.append(int(reviewed))
    if q:
        where.append("(rec LIKE ? OR parsed LIKE ? OR edited LIKE ?)")
        like = f"%{q}%"
        args += [like, like, like]
    sql = " AND ".join(where)
    with connect() as con:
        total = con.execute(f"SELECT count(*) FROM records WHERE {sql}", args).fetchone()[0]
        rows = con.execute(f"SELECT * FROM records WHERE {sql} ORDER BY idx LIMIT ? OFFSET ?", [*args, limit, offset])
        items = [_row_to_item(r) for r in rows]
    return {"total": total, "items": items}


def get_record(sid: str, idx: int) -> dict[str, Any] | None:
    with connect() as con:
        r = con.execute("SELECT * FROM records WHERE session_id = ? AND idx = ?", (sid, idx)).fetchone()
        return _row_to_item(r, full=True) if r else None


def patch_record(sid: str, idx: int, fields: dict[str, str | None], reviewed: bool | None) -> dict[str, Any] | None:
    with _lock, connect() as con:
        r = con.execute("SELECT * FROM records WHERE session_id = ? AND idx = ?", (sid, idx)).fetchone()
        if r is None:
            return None
        parsed = json.loads(r["parsed"]) if r["parsed"] else {}
        edited = json.loads(r["edited"]) if r["edited"] else {}
        for k, v in fields.items():
            if k not in PARSED_FIELDS:
                continue
            v = v.strip() if isinstance(v, str) else None
            v = v or None
            if v == parsed.get(k):
                edited.pop(k, None)  # вернули как было
            else:
                edited[k] = v
        con.execute(
            "UPDATE records SET edited = ?, reviewed = ?, updated_at = ? WHERE session_id = ? AND idx = ?",
            (
                json.dumps(edited, ensure_ascii=False) if edited else None,
                int(reviewed if reviewed is not None else bool(r["reviewed"]) or bool(fields)),
                time.time(),
                sid,
                idx,
            ),
        )
    return get_record(sid, idx)


def export(sid: str) -> str | None:
    with connect() as con:
        s = con.execute("SELECT container FROM sessions WHERE id = ?", (sid,)).fetchone()
        if s is None:
            return None
        out = []
        for r in con.execute("SELECT rec, parsed, edited FROM records WHERE session_id = ? ORDER BY idx", (sid,)):
            rec = json.loads(r["rec"])
            parsed = json.loads(r["parsed"]) if r["parsed"] else None
            edited = json.loads(r["edited"]) if r["edited"] else {}
            out.append(merged(rec, parsed, edited))
    return io_format.dumps(out, _container(s["container"]), indent=2)


def delete(sid: str) -> bool:
    with _lock, connect() as con:
        n = con.execute("DELETE FROM sessions WHERE id = ?", (sid,)).rowcount
        con.execute("DELETE FROM records WHERE session_id = ?", (sid,))
    return n > 0
