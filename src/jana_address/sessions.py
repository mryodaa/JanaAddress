"""Сессии UI: загруженный пакет, результаты разбора и ручные правки оператора.

Хранится в отдельной SQLite (config.EDITS_DB, в docker это volume /app/var). Справочник read-only и сюда
не пишется. Правки хранятся поверх результата разбора: экспорт = разбор + правки, источник поля "manual".

Разбор идёт одной фоновой очередью: пакеты по порядку, без потока на каждую загрузку. Записи ждут разбора
в самой базе (parsed IS NULL), поэтому после перезапуска сервиса незаконченные пакеты дорабатываются
(resume_pending), а не висят в «processing».
"""

from __future__ import annotations

import csv
import io
import json
import logging
import queue
import re
import sqlite3
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from . import config, engine, io_format
from .models import PARSED_FIELDS

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY, name TEXT, created_at REAL, status TEXT, total INTEGER, processed INTEGER,
    container TEXT, error TEXT, seconds REAL, threshold REAL
);
CREATE TABLE IF NOT EXISTS records (
    session_id TEXT NOT NULL, idx INTEGER NOT NULL, rec TEXT NOT NULL, parsed TEXT, edited TEXT,
    reviewed INTEGER NOT NULL DEFAULT 0, confidence REAL, updated_at REAL,
    n_added INTEGER, raw_key TEXT, search TEXT, meta TEXT, skipped INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (session_id, idx)
);
"""
# производные колонки записи: пишутся при разборе и правке, чтобы список, сортировка, поиск и сводка
# не декодировали весь parsed (с trace) на каждый запрос
DERIVED_COLS = {"n_added": "INTEGER", "raw_key": "TEXT", "search": "TEXT", "meta": "TEXT"}
CHUNK = 200
PAGE_MAX = 1000
# порог старой линейной модели confidence: сессии до перехода на логистическую (без threshold в строке)
# хранят её оценки, и мерить их новым порогом нельзя, шкалы разные
LEGACY_THRESHOLD = 0.6
# неуверенная и ещё не исправленная запись; ожидающая разбора (confidence NULL) тоже сюда
UNCERTAIN_SQL = "(confidence IS NULL OR confidence < ?) AND edited IS NULL"
# уверенность «сейчас» для сводки: исправленная или подтверждённая оператором запись уже не неуверенная
EFFECTIVE_SQL = "CASE WHEN edited IS NOT NULL OR reviewed = 1 THEN 1.0 ELSE confidence END"
# корзина гистограммы сводки (0..9 по 10%): фильтр «столбец графика» берёт ровно те записи, что в нём посчитаны
BUCKET_SQL = f"min(9, CAST(coalesce({EFFECTIVE_SQL}, 0) * 10 AS INTEGER))"
# запись без адреса (raw_address нет, не строка или пустой): разбирать нечего, в сводку и очередь проверки не идёт,
# в UI своя вкладка; raw_key пишется вместе с записью и пуст ровно тогда
NO_ADDR_SQL = "raw_key = ''"
# порядок списка: то же, что видно в таблице (у исправленной записи confidence 1.0, как в экспорте)
SortKey = Literal["idx", "confidence", "raw", "added"]
SORT_SQL: dict[str, str] = {
    "idx": "idx",
    "confidence": "CASE WHEN edited IS NOT NULL THEN 1.0 ELSE COALESCE(confidence, -1.0) END",
    "raw": "raw_key",
    "added": "n_added",
}

_lock = threading.Lock()
_ready: set[str] = set()  # базы, где уже добавлены колонки и включён WAL (раз на процесс)
_queue: queue.Queue[tuple[Path, str]] = queue.Queue()
_worker: threading.Thread | None = None
_worker_lock = threading.Lock()


class NotReady(Exception):
    """Пакет ещё разбирается: экспорт дал бы null на неразобранных записях."""


def _migrate(con: sqlite3.Connection) -> None:
    cols = {r[1] for r in con.execute("PRAGMA table_info(sessions)")}
    if "threshold" not in cols:
        con.execute("ALTER TABLE sessions ADD COLUMN threshold REAL")
    # сессии без порога: модель видна по trace (у логистической в шаге confidence есть logit)
    for (sid,) in con.execute("SELECT id FROM sessions WHERE threshold IS NULL").fetchall():
        row = con.execute(
            "SELECT parsed FROM records WHERE session_id = ? AND parsed IS NOT NULL LIMIT 1", (sid,)
        ).fetchone()
        trace = json.loads(row[0]).get("trace", []) if row else []
        logistic = any(t.get("step") == "confidence" and "logit" in t.get("changes", {}) for t in trace)
        th = config.UNCERTAIN_THRESHOLD if logistic else LEGACY_THRESHOLD
        con.execute("UPDATE sessions SET threshold = ? WHERE id = ?", (th, sid))


def _upgrade(con: sqlite3.Connection) -> None:
    """Один раз на процесс: WAL (чтение сводки не блокирует запись разбора) и производные колонки у старых баз."""
    con.execute("PRAGMA journal_mode=WAL")
    cols = {r[1] for r in con.execute("PRAGMA table_info(records)")}
    for name, typ in DERIVED_COLS.items():
        if name not in cols:
            con.execute(f"ALTER TABLE records ADD COLUMN {name} {typ}")
    # отложенные оператором записи (вне очереди «неуверенные», в своей вкладке)
    if "skipped" not in cols:
        con.execute("ALTER TABLE records ADD COLUMN skipped INTEGER NOT NULL DEFAULT 0")
    # сортировка списка без полного прохода по таблице
    con.execute("CREATE INDEX IF NOT EXISTS records_raw_key ON records (session_id, raw_key, idx)")
    con.execute("CREATE INDEX IF NOT EXISTS records_n_added ON records (session_id, n_added, idx)")
    con.execute(f"CREATE INDEX IF NOT EXISTS records_conf ON records (session_id, {SORT_SQL['confidence']}, idx)")
    rows = con.execute("SELECT session_id, idx, rec, parsed, edited FROM records WHERE raw_key IS NULL").fetchall()
    con.executemany(
        "UPDATE records SET n_added = ?, raw_key = ?, search = ?, meta = ? WHERE session_id = ? AND idx = ?",
        [(*_derived(*_decode(r)), r["session_id"], r["idx"]) for r in rows],
    )


@contextmanager
def connect(db: Path | None = None) -> Iterator[sqlite3.Connection]:
    path = db or config.EDITS_DB
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        con.executescript(SCHEMA)
        _migrate(con)
        key = str(path.resolve())
        if key not in _ready:
            _upgrade(con)
            _ready.add(key)
        yield con
        con.commit()
    finally:
        con.close()


def _container_json(c: io_format.Container) -> str:
    return io_format.dump_value({"kind": c.kind, "key": c.key, "extra": c.extra})


def _container(s: str) -> io_format.Container:
    d = io_format.parse_value(s)
    return io_format.Container(d["kind"], d.get("key"), d.get("extra") or {})


def _decode(row: sqlite3.Row) -> tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any]]:
    # исходная запись с дробными id как пришли (io_format.RawFloat): экспорт отдаёт их байт в байт
    rec = io_format.parse_value(row["rec"])
    parsed = json.loads(row["parsed"]) if row["parsed"] else None
    edited = json.loads(row["edited"]) if row["edited"] else {}
    return rec, parsed, edited


def _natural(s: str) -> str:
    """Ключ сортировки строки: без регистра, числа по значению («дом 9» раньше «дом 10»)."""
    return re.sub(r"\d+", lambda m: m.group().zfill(12), s.strip().casefold())


def _fields(parsed: dict[str, Any] | None, edited: dict[str, Any]) -> dict[str, Any]:
    fields = dict(parsed.get("fields", {})) if parsed else {}
    for k in edited:
        fields[k] = {"value": edited[k], "source": "manual", "span": None}
    return fields


def _derived(rec: dict[str, Any], parsed: dict[str, Any] | None, edited: dict[str, Any]) -> tuple[int, str, str, str]:
    """n_added, raw_key, search, meta для записи с учётом правок."""
    out = merged(rec, parsed, edited)
    fields = _fields(parsed, edited)
    raw = rec.get("raw_address")
    raw_s = raw if isinstance(raw, str) else ""
    # «Дополнено» в таблице: правки оператора и всё, чего нет в строке (справочник)
    added = sum(
        1
        for f in PARSED_FIELDS
        if f in edited or (out[f] is not None and (fields.get(f) or {}).get("source") not in (None, "string"))
    )
    fill = [f for f in PARSED_FIELDS if out[f]]
    src: dict[str, int] = {}
    if parsed is not None:
        for f in fill:
            s = ((fields.get(f) or {}).get("source") or "").split(":")[0]
            if s:
                src[s] = src.get(s, 0) + 1
    # поиск по строке и значениям полей, без ключей JSON и без регистра (SQLite LIKE не знает кириллицу)
    search = "\n".join([raw_s, *(str(out[f]) for f in fill)]).casefold()
    meta = json.dumps({"fill": fill, "src": src}, ensure_ascii=False, separators=(",", ":"))
    return added, _natural(raw_s), search, meta


def create(records: list[dict[str, Any]], container: io_format.Container, name: str) -> str:
    sid = uuid.uuid4().hex[:12]
    with _lock, connect() as con:
        con.execute(
            "INSERT INTO sessions (id, name, created_at, status, total, processed, container, threshold)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (
                sid,
                name,
                time.time(),
                "processing",
                len(records),
                0,
                _container_json(container),
                config.UNCERTAIN_THRESHOLD,
            ),
        )
        con.executemany(
            "INSERT INTO records (session_id, idx, rec, n_added, raw_key, search, meta) VALUES (?,?,?,?,?,?,?)",
            [(sid, i, io_format.dump_value(r), *_derived(r, None, {})) for i, r in enumerate(records)],
        )
    _enqueue(config.EDITS_DB, sid)
    return sid


def _enqueue(db: Path, sid: str) -> None:
    global _worker
    _queue.put((db, sid))
    with _worker_lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_work, name="jana-sessions", daemon=True)
            _worker.start()


def _work() -> None:
    while True:
        db, sid = _queue.get()
        try:
            _process(sid, db)
        except Exception:  # pragma: no cover - очередь не должна умирать из-за одного пакета
            log.exception("разбор пакета %s не удался", sid)
        finally:
            _queue.task_done()


def resume_pending() -> int:
    """Пакеты, прерванные перезапуском, ставятся в очередь заново: неразобранные записи лежат в базе."""
    with connect() as con:
        sids = [r[0] for r in con.execute("SELECT id FROM sessions WHERE status = 'processing' ORDER BY created_at")]
    for sid in sids:
        _enqueue(config.EDITS_DB, sid)
    return len(sids)


def wait_idle(timeout: float = 30.0) -> bool:
    """Для тестов: дождаться, пока очередь разберёт всё поставленное."""
    end = time.monotonic() + timeout
    while _queue.unfinished_tasks and time.monotonic() < end:
        time.sleep(0.02)
    return not _queue.unfinished_tasks


def _process(sid: str, db: Path | None = None) -> None:
    t0 = time.perf_counter()
    status, err = "done", None
    try:
        while True:
            with connect(db) as con:
                if con.execute("SELECT 1 FROM sessions WHERE id = ?", (sid,)).fetchone() is None:
                    return  # пакет удалили во время разбора: дальше разбирать некому
                rows = con.execute(
                    "SELECT idx, rec FROM records WHERE session_id = ? AND parsed IS NULL ORDER BY idx LIMIT ?",
                    (sid, CHUNK),
                ).fetchall()
            if not rows:
                break
            recs = [io_format.parse_value(r["rec"]) for r in rows]
            parsed = engine.parse_many(recs, explain=True)
            with _lock, connect(db) as con:
                con.executemany(
                    "UPDATE records SET parsed = ?, confidence = ?, n_added = ?, raw_key = ?, search = ?, meta = ?"
                    " WHERE session_id = ? AND idx = ?",
                    [
                        (json.dumps(p, ensure_ascii=False), p["confidence"], *_derived(rec, p, {}), sid, r["idx"])
                        for r, rec, p in zip(rows, recs, parsed, strict=True)
                    ],
                )
                con.execute(
                    "UPDATE sessions SET processed ="
                    " (SELECT count(*) FROM records WHERE session_id = ? AND parsed IS NOT NULL) WHERE id = ?",
                    (sid, sid),
                )
    except Exception as exc:
        log.exception("разбор пакета %s прерван", sid)
        status, err = "error", f"ошибка разбора: {type(exc).__name__}"
    try:
        with _lock, connect(db) as con:
            con.execute(
                "UPDATE sessions SET status = ?, error = ?, seconds = ? WHERE id = ?",
                (status, err, round(time.perf_counter() - t0, 3), sid),
            )
    except sqlite3.Error:  # pragma: no cover - иначе пакет навсегда остался бы «processing»
        log.exception("не удалось записать статус пакета %s", sid)


# ---------- чтение ----------
def _row_to_item(row: sqlite3.Row, full: bool = False) -> dict[str, Any]:
    rec, parsed, edited = _decode(row)
    item: dict[str, Any] = {
        "idx": row["idx"],
        "record": merged(rec, parsed, edited),
        "fields": _fields(parsed, edited),
        "edited": sorted(edited),
        "reviewed": bool(row["reviewed"]),
        "skipped": bool(row["skipped"]),
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


def get_session(sid: str, threshold: float | None = None) -> dict[str, Any] | None:
    with connect() as con:
        s = con.execute("SELECT * FROM sessions WHERE id = ?", (sid,)).fetchone()
        if s is None:
            return None
        th = _threshold(s, threshold)
        base = f"FROM records WHERE session_id = ? AND parsed IS NOT NULL AND NOT {NO_ADDR_SQL}"
        n, uncertain, mean = con.execute(
            f"SELECT count(*), coalesce(sum(({EFFECTIVE_SQL}) < ?), 0), avg({EFFECTIVE_SQL}) {base}", (th, sid)
        ).fetchone()
        reviewed = con.execute("SELECT count(*) FROM records WHERE session_id = ? AND reviewed = 1", (sid,)).fetchone()[
            0
        ]
        edited = con.execute(
            "SELECT count(*) FROM records WHERE session_id = ? AND edited IS NOT NULL", (sid,)
        ).fetchone()[0]
        # тот же предикат, что у фильтра «неуверенные» в UI (uncertain + reviewed=false + skipped=false)
        to_review = con.execute(
            f"SELECT count(*) FROM records WHERE session_id = ? AND {UNCERTAIN_SQL} AND reviewed = 0 AND skipped = 0"
            f" AND NOT {NO_ADDR_SQL}",
            (sid, th),
        ).fetchone()[0]
        skipped = con.execute("SELECT count(*) FROM records WHERE session_id = ? AND skipped = 1", (sid,)).fetchone()[0]
        no_address = con.execute(
            f"SELECT count(*) FROM records WHERE session_id = ? AND {NO_ADDR_SQL}", (sid,)
        ).fetchone()[0]
        # прогресс проверки: сколько из изначально неуверенных (по оценке разбора) оператор уже прошёл
        review_total, review_done = con.execute(
            f"SELECT count(*), coalesce(sum(reviewed = 1 OR edited IS NOT NULL), 0) {base} AND confidence < ?",
            (sid, th),
        ).fetchone()
        # корзина с порогом внутри делится: hist_uncertain = сколько в корзине ниже порога
        hist, hist_unc = [0] * 10, [0] * 10
        for b, cnt, unc in con.execute(
            f"SELECT {BUCKET_SQL} AS b, count(*), sum(coalesce({EFFECTIVE_SQL}, 0) < ?) {base} GROUP BY b",
            (th, sid),
        ):
            hist[b], hist_unc[b] = cnt, unc
        fill: dict[str, int] = dict.fromkeys(PARSED_FIELDS, 0)
        sources: dict[str, int] = {}
        for (m,) in con.execute(f"SELECT meta {base}", (sid,)):
            d = json.loads(m)
            for f in d["fill"]:
                fill[f] += 1
            for k, v in d["src"].items():
                sources[k] = sources.get(k, 0) + v
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
            "uncertain": uncertain,
            "confident": n - uncertain,
            "reviewed": reviewed,
            "edited": edited,
            "to_review": to_review,
            "skipped": skipped,
            "no_address": no_address,
            "review_total": review_total,
            "review_done": review_done,
            "mean_confidence": round(mean, 3) if mean is not None else None,
            "histogram": hist,
            "histogram_uncertain": hist_unc,
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


def _threshold(s: sqlite3.Row, override: float | None = None) -> float:
    """Порог сессии; override — порог из настроек UI (у каждого зрителя свой, в базе не хранится). Сессии старой
    линейной модели его не принимают: шкалы разные, 0.95 там значил бы почти всё."""
    stored = float(s["threshold"]) if s["threshold"] is not None else LEGACY_THRESHOLD
    if override is None or stored == LEGACY_THRESHOLD:
        return stored
    return override


def session_exists(sid: str) -> bool:
    with connect() as con:
        return con.execute("SELECT 1 FROM sessions WHERE id = ?", (sid,)).fetchone() is not None


def _session_threshold(con: sqlite3.Connection, sid: str, override: float | None = None) -> float:
    s = con.execute("SELECT threshold FROM sessions WHERE id = ?", (sid,)).fetchone()
    return _threshold(s, override) if s else (override if override is not None else config.UNCERTAIN_THRESHOLD)


def _like(q: str) -> str:
    esc = q.casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{esc}%"


def _where(
    con: sqlite3.Connection,
    sid: str,
    uncertain: bool,
    reviewed: bool | None,
    q: str,
    edited: bool | None,
    bucket: int | None = None,
    skipped: bool | None = None,
    no_address: bool | None = None,
    threshold: float | None = None,
) -> tuple[str, list[Any]]:
    where: list[str] = ["session_id = ?"]
    args: list[Any] = [sid]
    if uncertain:
        where.append(UNCERTAIN_SQL)
        args.append(_session_threshold(con, sid, threshold))
    if reviewed is not None:
        where.append("reviewed = ?")
        args.append(int(reviewed))
    if edited is not None:
        where.append("edited IS NOT NULL" if edited else "edited IS NULL")
    if q.strip():
        where.append("search LIKE ? ESCAPE '\\'")
        args.append(_like(q.strip()))
    if bucket is not None:
        where.append(f"parsed IS NOT NULL AND {BUCKET_SQL} = ?")
        args.append(bucket)
    if skipped is not None:
        where.append("skipped = ?")
        args.append(int(skipped))
    if no_address is not None:
        where.append(NO_ADDR_SQL if no_address else f"NOT {NO_ADDR_SQL}")
    return " AND ".join(where), args


def _order(sort: str, direction: str) -> str:
    d = "DESC" if direction == "desc" else "ASC"
    return f"{SORT_SQL.get(sort, 'idx')} {d}, idx {d if sort == 'idx' else 'ASC'}"


def list_records(
    sid: str,
    uncertain: bool = False,
    reviewed: bool | None = None,
    q: str = "",
    offset: int = 0,
    limit: int = 500,
    edited: bool | None = None,
    sort: str = "idx",
    direction: str = "asc",
    bucket: int | None = None,
    skipped: bool | None = None,
    no_address: bool | None = None,
    threshold: float | None = None,
) -> dict[str, Any]:
    with connect() as con:
        sql, args = _where(con, sid, uncertain, reviewed, q, edited, bucket, skipped, no_address, threshold)
        total = con.execute(f"SELECT count(*) FROM records WHERE {sql}", args).fetchone()[0]
        # сначала только номера страницы: сортировать строки целиком (rec/parsed с trace) на большом смещении
        # в разы дольше, чем короткие ключи; потом сами строки по номерам
        ids = [
            r[0]
            for r in con.execute(
                f"SELECT idx FROM records WHERE {sql} ORDER BY {_order(sort, direction)} LIMIT ? OFFSET ?",
                [*args, min(limit, PAGE_MAX), offset],
            )
        ]
        marks = ",".join("?" * len(ids))
        rows = {
            r["idx"]: r
            for r in con.execute(f"SELECT * FROM records WHERE session_id = ? AND idx IN ({marks})", [sid, *ids])
        }
        items = [_row_to_item(rows[i]) for i in ids if i in rows]
    return {"total": total, "offset": offset, "items": items}


def record_position(
    sid: str,
    idx: int,
    uncertain: bool = False,
    reviewed: bool | None = None,
    q: str = "",
    edited: bool | None = None,
    sort: str = "idx",
    direction: str = "asc",
    bucket: int | None = None,
    skipped: bool | None = None,
    no_address: bool | None = None,
    threshold: float | None = None,
) -> int | None:
    """Место записи в списке с этими фильтрами и порядком: UI держит выбор при смене сортировки."""
    with connect() as con:
        sql, args = _where(con, sid, uncertain, reviewed, q, edited, bucket, skipped, no_address, threshold)
        rows = con.execute(f"SELECT idx FROM records WHERE {sql} ORDER BY {_order(sort, direction)}", args)
        for pos, (i,) in enumerate(rows):
            if i == idx:
                return pos
    return None


def get_record(sid: str, idx: int) -> dict[str, Any] | None:
    with connect() as con:
        r = con.execute("SELECT * FROM records WHERE session_id = ? AND idx = ?", (sid, idx)).fetchone()
        return _row_to_item(r, full=True) if r else None


def patch_record(
    sid: str,
    idx: int,
    fields: dict[str, str | None],
    reviewed: bool | None,
    skipped: bool | None = None,
) -> dict[str, Any] | None:
    """Правка полей и статуса проверки. reviewed=True подтверждает (и снимает «отложено»), reviewed=False снимает
    подтверждение, skipped=True откладывает (запись уходит из очереди неуверенных и снова считается
    непроверенной), skipped=False возвращает в очередь. Правка поля без явного reviewed тоже подтверждение."""
    with _lock, connect() as con:
        r = con.execute("SELECT * FROM records WHERE session_id = ? AND idx = ?", (sid, idx)).fetchone()
        if r is None:
            return None
        rec, parsed_or_none, edited = _decode(r)
        parsed = parsed_or_none or {}
        for k, v in fields.items():
            if k not in PARSED_FIELDS:
                continue
            v = v.strip() if isinstance(v, str) else None
            v = v or None
            if v == parsed.get(k):
                edited.pop(k, None)  # вернули как было
            else:
                edited[k] = v
        rev = reviewed if reviewed is not None else bool(r["reviewed"]) or bool(fields)
        if skipped is not None:
            skip = skipped
        elif reviewed is True or (reviewed is None and fields):
            skip = False  # подтвердили или исправили: больше не отложена
        else:
            skip = bool(r["skipped"])
        if skipped:
            rev = False  # отложенная запись ещё не проверена
        con.execute(
            "UPDATE records SET edited = ?, reviewed = ?, skipped = ?, updated_at = ?, n_added = ?, raw_key = ?,"
            " search = ?, meta = ? WHERE session_id = ? AND idx = ?",
            (
                json.dumps(edited, ensure_ascii=False) if edited else None,
                int(rev),
                int(skip),
                time.time(),
                *_derived(rec, parsed_or_none, edited),
                sid,
                idx,
            ),
        )
    return get_record(sid, idx)


@dataclass
class ExportOptions:
    """Что выгружать. По умолчанию весь пакет в форме входа, все поля: это и есть ответ для жюри."""

    uncertain: bool = False
    reviewed: bool | None = None
    edited: bool | None = None
    q: str = ""
    bucket: int | None = None
    skipped: bool | None = None
    no_address: bool | None = None
    threshold: float | None = None  # порог для фильтра «неуверенные» из настроек UI
    sort: str = "idx"
    direction: str = "asc"
    fields: list[str] | None = None  # поля ответа (без id/raw_address), None = все + confidence
    fmt: str = "json"  # json | csv
    sources: bool = False  # добавить источник каждого непустого поля

    @property
    def filtered(self) -> bool:
        return (
            self.uncertain
            or self.reviewed is not None
            or self.edited is not None
            or bool(self.q.strip())
            or (self.bucket is not None)
            or self.skipped is not None
            or self.no_address is not None
        )


EXPORT_KEYS = (*PARSED_FIELDS, "confidence")


def export(sid: str, opts: ExportOptions | None = None) -> str | None:
    o = opts or ExportOptions()
    keys = ["id", "raw_address", *(o.fields if o.fields is not None else EXPORT_KEYS)]
    with connect() as con:
        s = con.execute("SELECT container, status FROM sessions WHERE id = ?", (sid,)).fetchone()
        if s is None:
            return None
        if s["status"] == "processing":
            raise NotReady(sid)
        sql, args = _where(
            con, sid, o.uncertain, o.reviewed, o.q, o.edited, o.bucket, o.skipped, o.no_address, o.threshold
        )
        out: list[dict[str, Any]] = []
        for r in con.execute(
            f"SELECT rec, parsed, edited FROM records WHERE {sql} ORDER BY {_order(o.sort, o.direction)}", args
        ):
            rec, parsed, edited = _decode(r)
            full = merged(rec, parsed, edited)
            row = {k: full[k] for k in keys}
            if o.sources:
                fields = _fields(parsed, edited)
                row["_sources"] = {
                    f: (fields.get(f) or {}).get("source") for f in PARSED_FIELDS if f in keys and full[f] is not None
                }
            out.append(row)
    if o.fmt == "csv":
        return _csv(out, keys, o.sources)
    container = _container(s["container"])
    # одиночная запись во входе, а выгружается не одна: отдаём массивом
    if container.kind == "single" and len(out) != 1:
        container = io_format.Container("list")
    return io_format.dumps(out, container, indent=2)


def _csv(rows: list[dict[str, Any]], keys: list[str], sources: bool) -> str:
    """CSV для Excel: BOM, разделитель «;» (так его открывает Excel с русской и казахской локалью), null пусто."""
    src_keys = [f for f in keys if f in PARSED_FIELDS] if sources else []
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    w.writerow([*keys, *(f"{f}_source" for f in src_keys)])
    for r in rows:
        cells = [_cell(r.get(k)) for k in keys]
        srcs = r.get("_sources") or {}
        w.writerow([*cells, *(srcs.get(f) or "" for f in src_keys)])
    return "\ufeff" + buf.getvalue()


# с этих символов Excel начинает формулу: адрес из чужой системы не должен выполниться при открытии CSV
FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def _cell(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, io_format.RawFloat):
        return v.text
    s = str(v)
    # только строки: числа (id) безопасны и должны остаться как есть
    if isinstance(v, str) and s.startswith(FORMULA_START):
        return "'" + s
    return s


def delete(sid: str) -> bool:
    with _lock, connect() as con:
        n = con.execute("DELETE FROM sessions WHERE id = ?", (sid,)).rowcount
        con.execute("DELETE FROM records WHERE session_id = ?", (sid,))
    return n > 0
