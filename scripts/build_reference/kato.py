"""КАТО (классификатор административно-территориальных объектов) -> cache/kato.json.

    python scripts/build_reference/kato.py cache/kato.xlsx   # или .csv

Файл берётся с stat.gov.kz (раздел «Классификаторы» -> КАТО) или data.egov.kz; ссылка меняется,
поэтому скрипт принимает уже скачанный файл. Код КАТО AABBCCDDD: AA область, BB район / город областного
значения, CC сельский округ, DDD населённый пункт. Колонки ищутся по заголовкам (код, наименование рус/каз).
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
_SETTLEMENT_PREFIX = re.compile(r"^(г\.|город|пос\.|п\.|с\.|село|аул|а\.|ст\.|станция|пгт)\s*", re.I)
_DISTRICT = re.compile(r"\s*(район|р-н)\s*$", re.I)


def read_rows(path: Path) -> list[dict[str, str]]:
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        import openpyxl

        wb = openpyxl.load_workbook(path, read_only=True)
        ws = wb.active
        rows = [[("" if c is None else str(c)).strip() for c in r] for r in ws.iter_rows(values_only=True)]
    else:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=";,\t")
        rows = [[c.strip() for c in r] for r in csv.reader(text.splitlines(), dialect)]
    head_i = next(i for i, r in enumerate(rows) if any(re.search(r"код|te|kato", c, re.I) for c in r))
    head = [c.lower() for c in rows[head_i]]

    def col(*pats: str) -> int:
        for i, h in enumerate(head):
            if any(re.search(p, h) for p in pats):
                return i
        raise KeyError(pats)

    ci = col(r"^te$", r"код", r"kato", r"code")
    ri = col(r"рус", r"name_rus", r"ru")
    ki = next((i for i, h in enumerate(head) if re.search(r"каз|kaz|kk", h)), None)
    out = []
    for r in rows[head_i + 1 :]:
        if len(r) <= max(ci, ri) or not re.fullmatch(r"\d{9}", r[ci]):
            continue
        out.append({"code": r[ci], "ru": r[ri], "kk": r[ki] if ki is not None and ki < len(r) else ""})
    return out


def convert(rows: list[dict[str, str]]) -> dict[str, Any]:
    prov: dict[str, str] = {}
    dist: dict[str, str] = {}
    out: dict[str, list[dict[str, Any]]] = {"provinces": [], "districts": [], "cities": []}
    for r in rows:
        c = r["code"]
        aa, bb, cc, ddd = c[:2], c[2:4], c[4:6], c[6:]
        if bb == "00" and cc == "00" and ddd == "000":
            prov[aa] = r["ru"]
            kind = "city" if not re.search(r"област", r["ru"], re.I) else "oblast"
            out["provinces"].append({"name": r["ru"], "kind": kind, "kato": c, "aliases": [r["kk"]]})
        elif cc == "00" and ddd == "000" and aa in prov:
            if _DISTRICT.search(r["ru"]):
                name = _DISTRICT.sub("", r["ru"]).strip()
                dist[aa + bb] = name
                out["districts"].append(
                    {
                        "name": name,
                        "province": prov[aa],
                        "kato": c,
                        "aliases": [_DISTRICT.sub("", r["kk"]).replace("ауданы", "").strip()],
                    }
                )
            else:  # город областного значения
                out["cities"].append(
                    {
                        "name": _SETTLEMENT_PREFIX.sub("", r["ru"]).strip(),
                        "kind": "city",
                        "province": prov[aa],
                        "kato": c,
                        "aliases": [r["kk"]],
                    }
                )
        elif ddd != "000" and aa in prov:
            name = _SETTLEMENT_PREFIX.sub("", r["ru"]).strip()
            kind = "town" if re.match(r"^(г\.|город|пгт|пос)", r["ru"], re.I) else "village"
            out["cities"].append(
                {
                    "name": name,
                    "kind": kind,
                    "province": prov[aa],
                    "district": dist.get(aa + bb),
                    "kato": c,
                    "aliases": [_SETTLEMENT_PREFIX.sub("", r["kk"]).strip()],
                }
            )
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", type=Path)
    ap.add_argument("--out", type=Path, default=HERE / "cache" / "kato.json")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    data = convert(read_rows(args.file))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(f"{args.out}: " + ", ".join(f"{k}={len(v)}" for k, v in data.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
