"""Быстрая ручная разметка dev-набора в терминале.

    python scripts/label.py data/train.json data/dev_gold.json --n 300 [--seed 7] [--annotator имя]

Берёт случайные строки из train.json, показывает предразбор текущего пайплайна, оператор принимает
его (Enter) или правит поля. Результат дописывается в dev_gold.json (data/ в .gitignore).
Работу можно прерывать: уже размеченные id пропускаются. Команда может делить набор по --shard i/k.

Команды в строке ввода:
  Enter                         принять всё как есть
  поле=значение [поле=значение] исправить (значение «-» = null), напр.  house=12а apartment=-
  ref=district,living_area      отметить поля, которые НЕ написаны в строке (подняты из справочника)
  s                             пропустить запись
  q                             сохранить и выйти
"""

from __future__ import annotations

import argparse
import json
import random
import shlex
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jana_address import engine, io_format
from jana_address.models import PARSED_FIELDS


def load_gold(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return io_format.loads(path.read_bytes())[0]


def save_gold(path: Path, gold: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(gold, ensure_ascii=False, indent=1), encoding="utf-8")


def show(rec: dict[str, Any], pred: dict[str, Any], i: int, total: int) -> None:
    print("\n" + "=" * 80)
    print(f"[{i}/{total}] id={rec.get('id')}  conf={pred['confidence']}")
    print(f"  {rec.get('raw_address')!r}")
    sources = {k: v.get("source") for k, v in pred.get("fields", {}).items()}
    for f in PARSED_FIELDS:
        src = sources.get(f)
        mark = "" if src in (None, "string") else f"   <- {src}"
        print(f"  {f:<12} {pred.get(f)!r}{mark}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("train", type=Path)
    ap.add_argument("gold", type=Path)
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--shard", default="0/1", help="i/k: размечать только свою долю")
    ap.add_argument("--annotator", default="")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

    records, _ = io_format.loads(args.train.read_bytes())
    rng = random.Random(args.seed)
    sample = rng.sample(records, min(args.n, len(records)))
    si, sk = (int(x) for x in args.shard.split("/"))
    sample = [r for j, r in enumerate(sample) if j % sk == si]

    gold = load_gold(args.gold)
    done = {str(g.get("id")) for g in gold}
    todo = [r for r in sample if str(r.get("id")) not in done]
    print(f"Размечено: {len(done)}, осталось в выборке: {len(todo)}")

    for i, rec in enumerate(todo, 1):
        pred = engine.parse_one(rec, explain=True)
        show(rec, pred, i, len(todo))
        item: dict[str, Any] = {"id": rec.get("id"), "raw_address": rec.get("raw_address")}
        for f in PARSED_FIELDS:
            item[f] = pred.get(f)
        item["_from_reference"] = [
            f for f, v in pred.get("fields", {}).items() if v.get("source") not in (None, "string")
        ]
        while True:
            cmd = input("> ").strip()
            if cmd in ("q", "s", ""):
                break
            try:
                for part in shlex.split(cmd):
                    key, _, val = part.partition("=")
                    if key == "ref":
                        item["_from_reference"] = [x for x in val.split(",") if x]
                    elif key in PARSED_FIELDS:
                        item[key] = None if val == "-" else val
                    else:
                        print(f"  неизвестное поле {key}")
            except ValueError as exc:
                print(f"  ошибка: {exc}")
            show(rec, {**pred, **item}, i, len(todo))
        if cmd == "q":
            break
        if cmd == "s":
            continue
        if args.annotator:
            item["_annotator"] = args.annotator
        gold.append(item)
        save_gold(args.gold, gold)
    save_gold(args.gold, gold)
    print(f"Сохранено {len(gold)} записей в {args.gold}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
