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
_SETTLEMENT_PREFIX = re.compile(
    r"^(г\.|город|пос\.|п\.|с\.|село|аул|а\.|ст\.|станция|пгт|рзд\.)\s*|\s+(қ\.|а\.|ауылы|кенті)$", re.I
)
_CTRL = re.compile(r"[\x00-\x1f\x7f]+")
_DISTRICT = re.compile(r"\s*(район|р-н|ауданы)\s*$", re.I)
_DISTRICT_PREFIX = re.compile(r"^\s*(район|ауданы)\s+", re.I)  # «район Есиль», «район Алматы» (Астана)
_OKRUG = re.compile(r"(с\.\s*о\.?|п\.\s*о\.?|а\.\s*о\.?|сельский округ|ауылдық округ)", re.I)
_CITY_ADMIN = re.compile(r"(г\.\s*а\.|қ\.\s*ә\.)\s*$", re.I)


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
        kk = r[ki] if ki is not None and ki < len(r) else ""
        # в выгрузке встречаются управляющие символы вместо пробела («Район\x01имени Габита Мусрепова»)
        out.append({"code": r[ci], "ru": _CTRL.sub(" ", r[ri]).strip(), "kk": _CTRL.sub(" ", kk).strip()})
    return out


def _parent(code: str, codes: set[str]) -> str | None:
    """Ближайший существующий предок: код с самым длинным общим началом и нулями в хвосте. Разбиение кода
    AABBCCDDD не всегда по парам: районы Тараза («район Әулиеата» 311011100) лежат под «г.Тараз» (311010000)."""
    for cut in range(8, 1, -1):
        p = code[:cut] + "0" * (9 - cut)
        if p != code and p in codes:
            return p
    return None


def _kind(ru: str) -> str:
    if _OKRUG.search(ru):
        return "okrug"
    if _CITY_ADMIN.search(ru):
        return "city_admin"
    if _DISTRICT.search(ru) or _DISTRICT_PREFIX.match(ru):
        return "district"
    if re.match(r"^г\.", ru, re.I):
        return "city"
    if re.match(r"^(п\.|пгт|пос\.)", ru, re.I):
        return "town"
    return "village"


def _bare(name: str) -> str:
    return re.sub(r"\s+", " ", _SETTLEMENT_PREFIX.sub("", name)).strip()


def _district_name(name: str) -> str:
    name = re.sub(r"(^|\s)им\.\s*", r"\1имени ", name)  # «им.Казыбек би» -> «имени Казыбек би», как у ядра
    return re.sub(r"\s+", " ", _DISTRICT_PREFIX.sub("", _DISTRICT.sub("", name))).replace("ауданы", "").strip()


def convert(rows: list[dict[str, str]]) -> dict[str, Any]:
    """Дерево КАТО -> области, районы (областей и городов), населённые пункты с районом области.
    Сельские округа и городские администрации («Г.А.») сами в справочник не идут: это контейнеры."""
    by = {r["code"]: r for r in rows}
    codes = set(by)
    out: dict[str, list[dict[str, Any]]] = {"provinces": [], "districts": [], "cities": []}
    prov_name: dict[str, str] = {}
    for c, r in by.items():
        if c[2:] == "0000000":
            name = _bare(r["ru"])
            kind = "oblast" if re.search(r"област", r["ru"], re.I) else "city"
            prov_name[c[:2]] = name
            out["provinces"].append({"name": name, "kind": kind, "kato": c, "aliases": [[r["kk"], "kk"]]})
    rep = {aa for aa, _ in prov_name.items() if not re.search(r"област", by[aa + "0000000"]["ru"], re.I)}

    def ancestors(c: str) -> list[dict[str, str]]:
        chain = []
        p = _parent(c, codes)
        while p is not None:
            chain.append(by[p])
            p = _parent(p, codes)
        return chain

    for c, r in sorted(by.items()):
        aa = c[:2]
        if c[2:] == "0000000" or aa not in prov_name:
            continue
        kind = _kind(r["ru"])
        chain = ancestors(c)
        city_anc = next((a for a in chain if _kind(a["ru"]) == "city"), None)
        dist_anc = next((a for a in chain if _kind(a["ru"]) == "district"), None)
        if kind == "district":
            item: dict[str, Any] = {
                "name": _district_name(r["ru"]),
                "province": prov_name[aa],
                "kato": c,
                "aliases": [[_district_name(r["kk"]), "kk"]],
            }
            if aa in rep:
                item["city"] = prov_name[aa]
            elif city_anc is not None:
                item["city"] = _bare(city_anc["ru"])
            out["districts"].append(item)
        elif kind in ("city", "town", "village"):
            if aa in rep and kind == "city":
                continue  # сам город респ. значения уже есть как область-город
            out["cities"].append(
                {
                    "name": _bare(r["ru"]),
                    "kind": kind,
                    "province": prov_name[aa],
                    "district": _district_name(dist_anc["ru"]) if dist_anc is not None and aa not in rep else None,
                    "district_method": "kato",
                    "kato": c,
                    "aliases": [[_bare(r["kk"]), "kk"]],
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
