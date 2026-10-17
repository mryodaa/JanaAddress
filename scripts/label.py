"""Быстрая ручная разметка dev-набора в терминале.

    python scripts/label.py data/train.json data/dev_gold.json --n 300 [--seed 7] [--annotator имя]

Берёт случайные строки из train.json, показывает предразбор текущего пайплайна, оператор принимает
его (Enter) или правит поля. Результат дописывается в dev_gold.json (data/ в .gitignore).
Работу можно прерывать: уже размеченные id пропускаются. Команда может делить набор по --shard i/k: каждая доля
пишется в свой файл (dev_gold.shard-i-of-k.json), чтобы параллельная разметка не затирала чужую работу; потом
`--merge` собирает доли в dev_gold.json. --blank начинает с пустых полей: предразбор не подсказывает ответ
(иначе эталон тянется к ответу парсера и завышает его оценку).

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


def shard_path(gold: Path, si: int, sk: int) -> Path:
    return gold if sk == 1 else gold.with_name(f"{gold.stem}.shard-{si}-of-{sk}{gold.suffix}")


def merge(gold: Path) -> int:
    """Доли разметки в основной файл: по id, повторный id из доли заменяет прежний."""
    by_id = {str(g.get("id")): g for g in load_gold(gold)}
    parts = sorted(gold.parent.glob(f"{gold.stem}.shard-*-of-*{gold.suffix}"))
    for part in parts:
        for g in load_gold(part):
            by_id[str(g.get("id"))] = g
    save_gold(gold, list(by_id.values()))
    print(f"собрано {len(by_id)} записей из {len(parts)} долей -> {gold}")
    return 0


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
    ap.add_argument("--blank", action="store_true", help="начинать с пустых полей, без предразбора")
    ap.add_argument("--merge", action="store_true", help="собрать доли --shard в основной файл и выйти")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    if args.merge:
        return merge(args.gold)

    records, _ = io_format.loads(args.train.read_bytes())
    rng = random.Random(args.seed)
    sample = rng.sample(records, min(args.n, len(records)))
    si, sk = (int(x) for x in args.shard.split("/"))
    sample = [r for j, r in enumerate(sample) if j % sk == si]

    out = shard_path(args.gold, si, sk)
    gold = load_gold(out)
    # уже размеченное и в основном файле, и в своей доле
    done = {str(g.get("id")) for g in gold} | {str(g.get("id")) for g in load_gold(args.gold) if out != args.gold}
    todo = [r for r in sample if str(r.get("id")) not in done]
    print(f"Размечено: {len(done)}, осталось в выборке: {len(todo)}")

    for i, rec in enumerate(todo, 1):
        pred = engine.parse_one(rec, explain=True)
        if not args.blank:  # с --blank предразбор не показываем вовсе
            show(rec, pred, i, len(todo))
        item: dict[str, Any] = {"id": rec.get("id"), "raw_address": rec.get("raw_address")}
        for f in PARSED_FIELDS:
            item[f] = None if args.blank else pred.get(f)
        item["_from_reference"] = (
            []
            if args.blank
            else [f for f, v in pred.get("fields", {}).items() if v.get("source") not in (None, "string")]
        )
        if args.blank:
            pred = {**pred, **item}
            show(rec, pred, i, len(todo))
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
        save_gold(out, gold)
    save_gold(out, gold)
    print(f"Сохранено {len(gold)} записей в {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
