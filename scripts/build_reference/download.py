"""Скачивание публичных источников справочника в scripts/build_reference/cache/ (с докачкой).

    python scripts/build_reference/download.py osm         # Geofabrik: kazakhstan-latest.osm.pbf (~220 МБ)
    python scripts/build_reference/download.py kato --url <ссылка на КАТО xlsx/csv с stat.gov.kz>
    python scripts/build_reference/download.py egov [--max-rows 400]   # адресные строки открытых наборов -> cache/egov/

Рантайм сервиса в сеть не ходит: сеть нужна только этому скрипту при сборке справочника.
Лицензии: OSM ODbL 1.0 (© участники OpenStreetMap), КАТО открытые данные АСПиР РК (см. docs/REFERENCE.md).
"""

from __future__ import annotations

import argparse
import concurrent.futures
import http.cookiejar
import json
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

CACHE = Path(__file__).resolve().parent / "cache"
SOURCES = {
    "osm": "https://download.geofabrik.de/asia/kazakhstan-latest.osm.pbf",
}
UA = "jana-address-reference-builder/0.1 (hackathon; offline runtime)"


def resolve(url: str) -> str:
    """«latest» у Geofabrik редиректит на датированный файл: докачиваем именно его, чтобы файл не сменился."""
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return str(resp.url)
    except OSError:
        return url


def fetch(url: str, dest: Path, retries: int = 500) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    for attempt in range(1, retries + 1):
        have = part.stat().st_size if part.exists() else 0
        req = urllib.request.Request(url, headers={"User-Agent": UA, **({"Range": f"bytes={have}-"} if have else {})})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                total = resp.headers.get("Content-Length")
                full = int(total) + have if total else None
                if have and resp.status != 206:  # сервер не поддержал докачку
                    have = 0
                    part.unlink(missing_ok=True)
                mode = "ab" if have else "wb"
                t0, got = time.time(), 0
                with part.open(mode) as fh:
                    while chunk := resp.read(1 << 16):
                        fh.write(chunk)
                        got += len(chunk)
                        if got % (1 << 22) < (1 << 16):
                            size = have + got
                            speed = got / max(1e-6, time.time() - t0) / 1024
                            pct = f"{size / full * 100:5.1f}%" if full else ""
                            print(f"  {size / 1e6:8.1f} МБ {pct} {speed:7.0f} КБ/с", flush=True)
            part.rename(dest)
            print(f"готово: {dest} ({dest.stat().st_size / 1e6:.1f} МБ)")
            return dest
        except urllib.error.HTTPError as exc:
            # 416 на докачке: .part уже целиком, сервер отдавать нечего
            if exc.code == 416 and have:
                part.rename(dest)
                print(f"готово (докачано ранее): {dest}")
                return dest
            # адреса нет или доступ закрыт: повторы ничего не дадут
            if exc.code in (401, 403, 404, 410):
                raise RuntimeError(f"{url}: HTTP {exc.code}") from exc
            pause = min(60, 5 * attempt)
            print(f"попытка {attempt}: {exc!r}, повтор через {pause} с", file=sys.stderr, flush=True)
            time.sleep(pause)
        except (OSError, TimeoutError) as exc:
            pause = min(60, 5 * attempt)  # сеть может пропадать на минуты
            print(f"попытка {attempt}: {exc!r}, повтор через {pause} с", file=sys.stderr, flush=True)
            time.sleep(pause)
    raise RuntimeError(f"не удалось скачать {url}")


EGOV = "https://data.egov.kz"
# колонка с адресом: по имени ключа или по доле значений, похожих на адрес
EGOV_ADDR_KEY = re.compile(r"addr|adres|adress|mekenzh|mekenjai|mekenzai|location", re.I)
EGOV_ADDR_VALUE = re.compile(
    r"(^|[\s,.(])(ул\.|улица|көшесі|мкр|микрорайон|пр-т|проспект|даңғылы|переулок|шағын аудан|д\.\s*\d|дом\s*№?\s*\d)",
    re.I,
)
# в первую очередь: списки объектов, где адрес почти наверняка есть
EGOV_PRIORITY = re.compile(
    r"школ|мектеп|детск|сад|балабақша|аптек|дәріхана|поликлин|больниц|нотариус|адрес|мекенжай|список|перечень|"
    r"тізім|тізбе|реестр|тізілім|контакт|отделен|ЦОН|КСК|ОСИ|общежит|объект",
    re.I,
)
# наборы, где бывает адрес объекта: школы, сады, аптеки, организации... (остальное в основном статистика)
EGOV_NAME = re.compile(
    r"школ|мектеп|сад|балабақша|аптек|дәрі|поликлин|больниц|аурухан|медицин|организац|ұйым|объект|нысан|учрежд|"
    r"мекеме|библиотек|кітапхан|спорт|клуб|музе|театр|рын|базар|магазин|торгов|сауда|нотариус|адвокат|почт|пошта|"
    r"отделен|филиал|центр|орталы|кондоминиум|ОСИ|КСК|общежит|жатақ|гостиниц|қонақ|кафе|предприят|кәсіпор|"
    r"стоматолог|колледж|лицей|гимназ|университет|училищ|ЦОН|акимат|әкімд|адрес|мекенжай|список|тізім|перечень|"
    r"тізбе|реестр|тізілім|контакт|байланыс|пункт|станц|парк|кладбищ|зират|приют|интернат|дом",
    re.I,
)


class Egov:
    """Внутренние JSON-эндпоинты страниц data.egov.kz (публичный API v4 требует ключ). 20 строк на страницу."""

    def __init__(self, pause: float) -> None:
        self.pause = pause
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def get(self, path: str, referer: str | None = None) -> str:
        headers = {"User-Agent": UA, "X-Requested-With": "XMLHttpRequest", **({"Referer": referer} if referer else {})}
        for attempt in range(1, 6):
            try:
                with self.opener.open(urllib.request.Request(EGOV + path, headers=headers), timeout=60) as resp:
                    time.sleep(self.pause)
                    return str(resp.read().decode("utf-8", "replace"))
            except (OSError, TimeoutError) as exc:
                print(f"  {path[:80]}: {exc!r}, попытка {attempt}", file=sys.stderr, flush=True)
                time.sleep(5 * attempt)
        return ""

    def datasets(self) -> list[dict[str, Any]]:
        q = "byGovAgencyId=&categoryId=&statusType=&datasetSortSelect=&status=PUBLISHED"
        out: dict[str, dict[str, Any]] = {}
        page = 1
        while True:
            text = self.get(f"/datasets/getdatasetsre?page={page}&count=10&{q}")
            if not text:
                # страница не скачалась после всех попыток: неполный список не кэшируем, иначе он навсегда
                raise RuntimeError(f"egov: не удалось получить страницу {page} списка наборов")
            items = json.loads(text).get("datasets") if text.startswith("{") else None
            before = len(out)
            out.update({d["apiUri"]: d for d in items or []})
            # за последней страницей сервер отдаёт её повтор: выходим, когда новых наборов нет
            if len(out) == before:
                return list(out.values())
            if page % 50 == 0:
                print(f"  список: страница {page}, наборов {len(out)}", flush=True)
            page += 1

    def rows(self, index: str, max_rows: int) -> tuple[str, list[str], list[dict[str, Any]]]:
        """Первая страница определяет колонки адреса; без них дальше не листаем."""
        view = f"{EGOV}/datasets/view?index={urllib.parse.quote(index)}"
        m = re.search(r"currentVersion = '([^']+)'", self.get(f"/datasets/view?index={urllib.parse.quote(index)}"))
        if not m:
            return "", [], []
        version, page = m.group(1), 1
        rows: list[dict[str, Any]] = []
        keys: list[str] = []
        while len(rows) < max_rows:
            text = self.get(
                f"/datasets/getdata?index={urllib.parse.quote(index)}&version={version}&page={page}&count=20", view
            )
            data = json.loads(text) if text.startswith("{") else {}
            rows.extend(data.get("elements") or [])
            if page == 1:
                keys = egov_address_keys(rows)
                if not keys:
                    break
            if not data.get("elements") or page >= int(data.get("totalPages") or 0):
                break
            page += 1
        return version, keys, rows[:max_rows]


def egov_address_keys(rows: list[dict[str, Any]]) -> list[str]:
    keys: list[str] = []
    for k in {k for r in rows for k in r}:
        vals = [str(r.get(k) or "") for r in rows if r.get(k)]
        if not vals:
            continue
        hit = sum(bool(EGOV_ADDR_VALUE.search(v)) and 10 <= len(v) <= 200 for v in vals) / len(vals)
        if hit >= 0.4 or (EGOV_ADDR_KEY.search(k) and hit >= 0.2):
            keys.append(k)
    return sorted(keys)


def safe_name(name: str) -> str:
    """apiUri приходит с сервера: в имя файла только буквы, цифры, точка, дефис и подчёркивание (без ../)."""
    s = re.sub(r"[^\w.-]", "_", name).strip(".")
    return s or "_"


def fetch_egov(max_rows: int, pause: float, workers: int = 4) -> None:
    """Открытые наборы data.egov.kz с колонкой адреса -> cache/egov/<index>.json (строки для почти реального эталона,
    не для справочника и не для образа). Сначала самые вероятные по названию (школы, сады, аптеки, адреса)."""
    out_dir = CACHE / "egov"
    out_dir.mkdir(parents=True, exist_ok=True)
    listing = out_dir / "_datasets.json"
    if not listing.exists():  # список наборов это ~400 запросов: кэшируем
        listing.write_text(json.dumps(Egov(pause).datasets(), ensure_ascii=False), encoding="utf-8")
    all_sets = json.loads(listing.read_text(encoding="utf-8"))

    def name(d: dict[str, Any]) -> str:
        return f"{d.get('nameRu') or ''} {d.get('nameKk') or ''}"

    sets = sorted((d for d in all_sets if EGOV_NAME.search(name(d))), key=lambda d: not EGOV_PRIORITY.search(name(d)))
    todo = [
        d
        for d in sets
        if not (out_dir / f"{safe_name(d['apiUri'])}.json").exists()
        and not (out_dir / f"{safe_name(d['apiUri'])}.skip").exists()
    ]
    print(f"наборов: {len(all_sets)}, по названию {len(sets)}, осталось {len(todo)}", flush=True)
    local = threading.local()

    def work(d: dict[str, Any]) -> str | None:
        if not hasattr(local, "eg"):
            local.eg = Egov(pause)  # своя сессия (cookie) на поток
        version, keys, rows = local.eg.rows(d["apiUri"], max_rows)
        if not keys:
            (out_dir / f"{safe_name(d['apiUri'])}.skip").touch()
            return None
        payload = {"index": d["apiUri"], "version": version, "name": d.get("nameRu"), "keys": keys, "rows": rows}
        out = out_dir / f"{safe_name(d['apiUri'])}.json"
        out.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return f"{d['apiUri']}: {len(rows)} строк, колонки {keys}"

    found = 0
    with concurrent.futures.ThreadPoolExecutor(workers) as pool:
        for i, msg in enumerate(pool.map(work, todo), 1):
            if msg:
                found += 1
                print(f"[{i}/{len(todo)}] {msg}", flush=True)
    print(f"наборов с адресом: {found} (новых), каталог {out_dir}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("what", choices=["osm", "kato", "egov"])
    ap.add_argument("--url", help="переопределить адрес источника")
    ap.add_argument("--max-rows", type=int, default=400, help="egov: строк на набор")
    ap.add_argument("--pause", type=float, default=0.2, help="egov: пауза между запросами, с")
    ap.add_argument("--workers", type=int, default=4, help="egov: параллельных сессий")
    args = ap.parse_args(argv)
    if args.what == "egov":
        fetch_egov(args.max_rows, args.pause, args.workers)
    elif args.what == "osm":
        url = resolve(args.url or SOURCES["osm"])
        print(f"источник: {url}", flush=True)
        fetch(url, CACHE / "kazakhstan-latest.osm.pbf")
    else:
        if not args.url:
            ap.error("для КАТО укажите --url (адрес файла меняется на stat.gov.kz) или положите файл в cache/ вручную")
        # расширение по пути адреса, без ?query
        fetch(args.url, CACHE / ("kato" + Path(urllib.parse.urlparse(args.url).path).suffix))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
