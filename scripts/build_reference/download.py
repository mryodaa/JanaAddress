"""Скачивание публичных источников справочника в scripts/build_reference/cache/ (с докачкой).

    python scripts/build_reference/download.py osm         # Geofabrik: kazakhstan-latest.osm.pbf (~220 МБ)
    python scripts/build_reference/download.py kato --url <ссылка на КАТО xlsx/csv с stat.gov.kz>

Рантайм сервиса в сеть не ходит: сеть нужна только этому скрипту при сборке справочника.
Лицензии: OSM ODbL 1.0 (© участники OpenStreetMap), КАТО открытые данные АСПиР РК (см. docs/REFERENCE.md).
"""

from __future__ import annotations

import argparse
import sys
import time
import urllib.request
from pathlib import Path

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
        except (OSError, TimeoutError) as exc:
            pause = min(60, 5 * attempt)  # сеть может пропадать на минуты
            print(f"попытка {attempt}: {exc!r}, повтор через {pause} с", file=sys.stderr, flush=True)
            time.sleep(pause)
    raise RuntimeError(f"не удалось скачать {url}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("what", choices=["osm", "kato"])
    ap.add_argument("--url", help="переопределить адрес источника")
    args = ap.parse_args(argv)
    if args.what == "osm":
        url = resolve(args.url or SOURCES["osm"])
        print(f"источник: {url}", flush=True)
        fetch(url, CACHE / "kazakhstan-latest.osm.pbf")
    else:
        if not args.url:
            ap.error("для КАТО укажите --url (адрес файла меняется на stat.gov.kz) или положите файл в cache/ вручную")
        fetch(args.url, CACHE / ("kato" + Path(args.url).suffix))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
