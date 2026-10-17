"""Почти реальный эталон (train.json не выдадут): компактная разметка -> JSON, проверка по правилам ТЗ, сплит.

    python scripts/realish.py lines data/realish/llm/*.txt --tag src:llm --out data/realish/llm.json
    python scripts/realish.py egov --out data/realish/egov_raw.txt [--n 400]   # строки из cache/egov/ для разметки
    python scripts/realish.py validate data/realish/llm.json [--drop]
    python scripts/realish.py split data/realish/llm.json        # -> llm_dev.json + llm_holdout.json (по хешу id)

Формат строки разметки (одна запись на строку, # комментарий):
    сырой адрес ||| city=Алматы; street_type=микрорайон; street_name=Аксай-3а; house=59; apartment=70
Не указанное поле = null. ref=district,living_area: поля подняты не из строки (`_from_reference`).
tags=a,b: теги для разбивки eval.py. Строка без «|||» = только raw (для разметки потом).

Эталон пишется по правилам слайда 08 и решениям docs/QUESTIONS.md: city без «город», district без «район»,
street_name/landmark/house как в строке. district/living_area/province/city, которых нет в строке, не размечаем.
Всё лежит в data/ (в .gitignore и .dockerignore): в тесты, фикстуры и образ не попадает.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from jana_address.models import PARSED_FIELDS  # noqa: E402
from jana_address.reference.normalize import fold  # noqa: E402
from scripts.eval import in_string, norm  # noqa: E402

SEP = "|||"
NUMERIC = ("house", "apartment", "entrance", "floor")
# поля, которые должны быть срезом строки (сравнение как у жюри: регистр, пунктуация, пробелы);
# city и district тоже как в строке, без перевода (Q22), каноном справочника только province
AS_WRITTEN = ("city", "district", "street_name", "house", "apartment", "entrance", "floor", "landmark")
# служебные слова, которых не должно быть в значении (слайд 08)
FORBIDDEN = {
    "city": re.compile(r"(^|\s)(г\.|город|қаласы|пос\.|поселок|посёлок|с\.|село|ауылы)(\s|$)", re.I),
    "district": re.compile(r"(^|\s)(район|р-н|ауданы)(\s|$)", re.I),
    "street_name": re.compile(r"^(ул\.?|улица|пр\.|проспект|мкр\.?|микрорайон|көшесі|даңғылы)(\s|$)", re.I),
    "apartment": re.compile(r"[а-яa-z]{2,}", re.I),
    "entrance": re.compile(r"[а-яa-z]{2,}", re.I),
    "floor": re.compile(r"[а-яa-z]{2,}", re.I),
}


def parse_line(line: str, rid: str, tags: list[str]) -> dict[str, Any] | None:
    line = line.rstrip("\n")
    if not line.strip() or line.lstrip().startswith("#"):
        return None
    raw, _, ann = line.partition(SEP)
    rec: dict[str, Any] = {"id": rid, "raw_address": raw.strip(), **dict.fromkeys(PARSED_FIELDS)}
    rec["_tags"] = list(tags)
    for part in ann.split(";"):
        key, eq, val = part.partition("=")
        key, val = key.strip(), val.strip()
        if not eq:
            if key:
                raise ValueError(f"{rid}: нет «=» в «{part}»")
            continue
        if key == "ref":
            rec["_from_reference"] = [v.strip() for v in val.split(",") if v.strip()]
        elif key == "tags":
            rec["_tags"] += [v.strip() for v in val.split(",") if v.strip()]
        elif key in PARSED_FIELDS:
            rec[key] = val or None
        else:
            raise ValueError(f"{rid}: неизвестное поле {key}")
    if not ann.strip():
        rec["_unlabeled"] = True
    return rec


def tokens_match(value: str, raw: str) -> bool:
    """Каждое слово значения узнаётся в строке по началу: «Актюбинская область» ~ «Актюбинская обл»."""
    raw_toks = re.findall(r"\w+", fold(raw))
    for tok in re.findall(r"\w+", fold(value)):
        pre = tok[: min(len(tok), 4)]
        if not any(r.startswith(pre) or (tok.startswith(r[:4]) and len(r) >= 3) for r in raw_toks):
            return False
    return True


def problems(rec: dict[str, Any]) -> list[str]:
    out: list[str] = []
    raw = rec.get("raw_address") or ""
    from_ref = set(rec.get("_from_reference") or [])
    for f in PARSED_FIELDS:
        v = rec.get(f)
        if v == "":
            out.append(f"{f}: пустая строка вместо null")
            continue
        if v is None or f in from_ref:
            continue
        if f in AS_WRITTEN and not in_string(v, raw):
            out.append(f"{f}={v!r}: нет в строке")
        if f in NUMERIC and not re.search(r"\d", v) and f != "house":
            out.append(f"{f}={v!r}: нет номера")
        if f in FORBIDDEN and FORBIDDEN[f].search(v):
            out.append(f"{f}={v!r}: служебное слово в значении")
        if f == "living_area" and not (in_string(v, raw) or tokens_match(v, raw)):
            out.append(f"{f}={v!r}: нет в строке (если поднято из справочника, укажите ref=)")
    return out


def warnings(rec: dict[str, Any]) -> list[str]:
    """Область пишется каноном справочника (слайд 08), поэтому может не совпадать со строкой: «Ақтөбе облысы»."""
    raw, from_ref = rec.get("raw_address") or "", set(rec.get("_from_reference") or [])
    return [
        f"{f}={rec[f]!r}: не узнаётся в строке (канонический перевод или забыт ref=)"
        for f in ("province",)
        if rec.get(f) and f not in from_ref and not tokens_match(rec[f], raw)
    ]


def cmd_lines(args: argparse.Namespace) -> int:
    recs: list[dict[str, Any]] = []
    for path in args.files:
        stem = Path(path).stem
        for i, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
            rec = parse_line(line, f"{args.prefix}{stem}_{i:04d}", args.tag)
            if rec:
                recs.append(rec)
    seen: set[str] = set()
    uniq = [r for r in recs if not (norm(r["raw_address"]) in seen or seen.add(norm(r["raw_address"])))]  # type: ignore[func-returns-value]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(uniq, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(uniq)} записей ({len(recs) - len(uniq)} дублей убрано) -> {args.out}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    recs = json.loads(args.file.read_text(encoding="utf-8"))
    bad = {r["id"]: p for r in recs if (p := problems(r))}
    warn = {r["id"]: w for r in recs if (w := warnings(r))}
    raws = {r["id"]: r["raw_address"] for r in recs}
    for rid, ps in bad.items():
        print(f"{rid}  {raws[rid]}\n    " + "\n    ".join(ps))
    if args.warnings:
        for rid, ws in warn.items():
            print(f"[warn] {rid}  {raws[rid]}\n    " + "\n    ".join(ws))
    print(f"\nзаписей {len(recs)}, с замечаниями {len(bad)}, предупреждений {len(warn)} (--warnings)")
    if args.drop and bad:
        args.file.write_text(
            json.dumps([r for r in recs if r["id"] not in bad], ensure_ascii=False, indent=1), encoding="utf-8"
        )
        print(f"убрано {len(bad)} -> {args.file}")
    return 1 if bad and not args.drop else 0


def is_holdout(rid: str) -> bool:
    return hashlib.sha1(rid.encode()).digest()[0] % 2 == 1


def cmd_split(args: argparse.Namespace) -> int:
    recs = [r for r in json.loads(args.file.read_text(encoding="utf-8")) if not r.get("_unlabeled")]
    stem = args.file.with_suffix("")
    for name, part in (
        ("dev", [r for r in recs if not is_holdout(r["id"])]),
        ("holdout", [r for r in recs if is_holdout(r["id"])]),
    ):
        dest = Path(f"{stem}_{name}.json")
        dest.write_text(json.dumps(part, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{name}: {len(part)} -> {dest}")
    return 0


def cmd_egov(args: argparse.Namespace) -> int:
    """Адресные строки из скачанных наборов egov: без дублей, не больше --per-set с набора, разнообразно по наборам."""
    cache = ROOT / "scripts" / "build_reference" / "cache" / "egov"
    pools: list[list[str]] = []
    for path in sorted(p for p in cache.glob("*.json") if not p.name.startswith("_")):  # _datasets.json: список
        d = json.loads(path.read_text(encoding="utf-8"))
        vals = {
            " ".join(str(r.get(k) or "").split())
            for r in d["rows"]
            for k in d["keys"]
            if re.search(r"\d", str(r.get(k) or "")) and 10 <= len(str(r.get(k) or "")) <= 160
        }
        if vals:
            pools.append(sorted(vals))
    rnd = random.Random(args.seed)
    for p in pools:
        rnd.shuffle(p)
    picked: list[str] = []
    # уже размеченные пачки не повторяем
    seen = {norm(ln.split(SEP)[0]) for f in args.skip for ln in Path(f).read_text(encoding="utf-8").splitlines()}
    for depth in range(args.per_set):
        for p in pools:
            if depth < len(p) and norm(p[depth]) not in seen:
                seen.add(norm(p[depth]))
                picked.append(p[depth])
    rnd.shuffle(picked)
    picked = picked[: args.n]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(s.replace(SEP, "/") for s in picked) + "\n", encoding="utf-8")
    print(f"наборов {len(pools)}, строк {len(picked)} -> {args.out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("lines")
    p.add_argument("files", nargs="+")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--tag", action="append", default=[])
    p.add_argument("--prefix", default="")
    p.set_defaults(func=cmd_lines)
    p = sub.add_parser("validate")
    p.add_argument("file", type=Path)
    p.add_argument("--drop", action="store_true", help="убрать записи с замечаниями")
    p.add_argument("--warnings", action="store_true", help="показать предупреждения по admin-полям")
    p.set_defaults(func=cmd_validate)
    p = sub.add_parser("split")
    p.add_argument("file", type=Path)
    p.set_defaults(func=cmd_split)
    p = sub.add_parser("egov")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--n", type=int, default=400)
    p.add_argument("--per-set", type=int, default=15)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--skip", nargs="*", default=[], help="файлы уже размеченных пачек")
    p.set_defaults(func=cmd_egov)
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
