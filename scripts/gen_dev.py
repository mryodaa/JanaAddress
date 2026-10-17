"""Синтетический dev-набор: реальные топонимы из справочника + искажения, которые встречаются в реальных данных
(слитное написание, литеры и дроби, латиница, рус/каз через слэш, дубли города, район вместо города, опечатки
маркеров, невидимые символы, ориентиры).

    python scripts/gen_dev.py --n 1000 [--seed 1] [--out data/dev_synth.json]
    python -m jana_address.cli data/dev_synth.json out.json && python scripts/eval.py out.json data/dev_synth.json

Эталон известен по построению: значения строковых полей это ровно тот фрагмент, который записан в строку.
В каждой записи `_tags` (какие варианты применены, eval.py печатает точность по тегам) и `_spans`
(посимвольные спаны всех полей в raw: [start, end, LABEL], см. scripts/synth/labeled.py).

Ограничения (поэтому это ориентир, а не замена ручной разметке живых строк):
* улицы и дома взяты из того же справочника, что использует парсер, поэтому восстановление по справочнику
  выглядит лучше, чем будет на живых данных; тег street_unknown даёт улицы, которых в этом городе нет;
* шаблоны написаны нами: парсер, подогнанный под генератор, может не обобщаться.
Маркеры здесь собраны вручную, а не из rules/*.yaml, чтобы не проверять словарь самим собой.
Сама сборка в scripts/synth/builder.py (общая с генератором обучающих данных теггера).
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jana_address import config  # noqa: E402
from scripts.synth.builder import Builder, Ref  # noqa: E402

DB = config.SYNTH_DB  # снапшот: пересборка справочника не двигает наборы и split unseen


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "dev_synth.json")
    ap.add_argument("--db", type=Path, default=DB)
    ap.add_argument("--chaos", action="store_true", help="опечатки в названиях, мусор, телефоны, ФИО, перемешивание")
    ap.add_argument("--strong", action="store_true", help="искажения обучения теггера (synth/augment.py)")
    ap.add_argument("--split", choices=["all", "train", "unseen"], default="all", help="разбиение топонимов")
    ap.add_argument("--force", action="store_true", help="перезаписать существующий --out")
    args = ap.parse_args(argv)
    # по умолчанию --out это data/dev_synth.json: новый seed не должен молча затереть dev-набор
    if args.out.exists() and not args.force:
        ap.error(f"{args.out} уже есть: укажите другой --out или --force")
    rnd = random.Random(args.seed)
    b = Builder(Ref(args.db, args.split), rnd, chaos=args.chaos, strong=args.strong)
    recs = [b.record(i + 1) for i in range(args.n)]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(recs, ensure_ascii=False, indent=1), encoding="utf-8")
    tags: dict[str, int] = defaultdict(int)
    for r in recs:
        for t in r["_tags"]:
            tags[t] += 1
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    print(f"{len(recs)} записей -> {args.out}")
    print("  " + ", ".join(f"{k}={v}" for k, v in sorted(tags.items(), key=lambda kv: -kv[1])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
