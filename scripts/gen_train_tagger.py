"""Обучающие данные посимвольного теггера: синтетические адреса с посимвольными спанами полей.

    python scripts/gen_train_tagger.py --n 150000 --seed 1001 --split train --out data/tagger/train.jsonl
    python scripts/gen_train_tagger.py --n 5000 --seed 2001 --split train --out data/tagger/val.jsonl
    python scripts/gen_train_tagger.py --n 3000 --seed 3001 --split unseen --out data/tagger/unseen.jsonl

Строка JSONL: {"raw", "spans": [[s, e, LABEL]], "tags", поля эталона}. Метки: scripts/synth/labeled.py.
split=train исключает отложенные топонимы (около 15% улиц и 10% населённых пунктов по хешу id), split=unseen
состоит только из них: метрика на unseen показывает обобщение, а не запоминание улиц.
Смесь режимов: strong (+chaos) для разнообразия и базовый режим dev-генератора, чтобы не уйти от него.
Seed обучения не должен совпадать с seed dev- и отложенных наборов (1, 2, 11, 99 и новый отложенный).
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jana_address import config  # noqa: E402
from scripts.synth.builder import Builder, Ref  # noqa: E402

DB = config.SYNTH_DB  # снапшот: пересборка справочника не двигает наборы и split unseen
RESERVED_SEEDS = {1, 2, 11, 99, 4242, 4343}  # dev и отложенные (4242: dev_chaos_v2_holdout, 4343: dev_hard_holdout)
# доли режимов (chaos, strong)
MIX = [((True, True), 0.5), ((False, True), 0.3), ((True, False), 0.2)]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=150_000)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--split", choices=["all", "train", "unseen"], default="train")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--db", type=Path, default=DB)
    args = ap.parse_args(argv)
    if args.seed in RESERVED_SEEDS:
        ap.error(f"seed {args.seed} занят dev/отложенным набором")
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    rnd = random.Random(args.seed)
    ref = Ref(args.db, args.split)
    builders = [(Builder(ref, rnd, chaos=c, strong=s), w) for (c, s), w in MIX]
    tags: Counter[str] = Counter()
    labels: Counter[str] = Counter()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    with args.out.open("w", encoding="utf-8") as fh:
        for i in range(args.n):
            b = rnd.choices([b for b, _ in builders], weights=[w for _, w in builders])[0]
            rec = b.record(i + 1)
            rec.pop("id", None)
            rec.pop("confidence", None)
            row = {"raw": rec.pop("raw_address"), "spans": rec.pop("_spans"), "tags": rec.pop("_tags"), **rec}
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            tags.update(row["tags"])
            labels.update(s[2] for s in row["spans"])
            if (i + 1) % 20000 == 0:
                print(f"  {i + 1} за {time.perf_counter() - t0:.0f} с", flush=True)
    print(f"{args.n} строк -> {args.out} за {time.perf_counter() - t0:.0f} с")
    print("  метки: " + ", ".join(f"{k}={v}" for k, v in labels.most_common()))
    print("  теги: " + ", ".join(f"{k}={v}" for k, v in tags.most_common(25)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
