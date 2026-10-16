"""Обучение char BiLSTM-CRF с ранней остановкой по span-F1 на val.

    .venv-train/Scripts/python -m training.train --train data/tagger/train.jsonl --val data/tagger/val.jsonl \
        --unseen data/tagger/unseen.jsonl [--extra data/tagger/silver.jsonl] --out training/runs/v1

Выбор эпохи только по val; unseen (топонимы, которых не было в обучении) печатается для контроля и в
выборе не участвует. Результат: <out>/best.pt (веса + словарь символов + метаданные), <out>/log.json.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

import numpy as np
import torch

from .data import MAX_LEN, Example, batches, build_vocab, decode, iter_jsonl, pad, sha256_files, span_f1, to_examples
from .model import Tagger


def tensors(exs: list[Example], device: torch.device) -> tuple[torch.Tensor, ...]:
    return tuple(torch.from_numpy(a).to(device) for a in pad(exs))


@torch.no_grad()
def evaluate(model: Tagger, exs: list[Example], device: torch.device, size: int = 512) -> dict[str, object]:
    model.eval()
    gold, pred = [], []
    for b in batches(exs, size, None):
        chars, case, cls, _, lengths = tensors(b, device)
        em = model.emissions(chars, case, cls, lengths)
        for e, path in zip(b, model.crf.decode(em, lengths), strict=True):
            gold.append(decode(e.tags))
            pred.append(decode(np.array(path)))
    model.train()
    return span_f1(gold, pred)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--train", type=Path, required=True)
    ap.add_argument("--val", type=Path, required=True)
    ap.add_argument("--unseen", type=Path)
    ap.add_argument("--extra", type=Path, action="append", default=[], help="серебряная разметка и т.п.")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--epochs", type=int, default=20)
    ap.add_argument("--patience", type=int, default=3)
    ap.add_argument("--batch", type=int, default=128)
    ap.add_argument("--lr", type=float, default=2e-3)
    ap.add_argument("--hidden", type=int, default=128)
    ap.add_argument("--emb", type=int, default=48)
    ap.add_argument("--seed", type=int, default=13)
    ap.add_argument("--limit", type=int, default=0, help="взять первые N строк train (отладка)")
    # на ноутбучной RTX 2050 под WDDM CUDA падает с OOM на выделениях в сотни МБ при свободных гигабайтах,
    # поэтому по умолчанию CPU: около 8 мин на эпоху 150k строк в 12 потоков
    ap.add_argument("--device", default="cpu", help="cpu | cuda")
    ap.add_argument("--threads", type=int, default=0)
    ap.add_argument("--resume", action="store_true", help="продолжить с <out>/last.pt (после падения)")
    args = ap.parse_args(argv)

    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    random.seed(args.seed)
    torch.manual_seed(args.seed)
    if args.threads:
        torch.set_num_threads(args.threads)
    device = torch.device(args.device)
    t0 = time.perf_counter()
    # потоком и компактно (uint8): 150k строк словарями Python занимают гигабайты, а на машине рядом с Docker
    # свободно около 3 ГБ; при нехватке памяти потоки torch падают с access violation, а не MemoryError
    files = [args.train, *args.extra]
    chars = build_vocab(iter_jsonl(files, args.limit))
    train = to_examples(iter_jsonl(files, args.limit), chars, keep_raw=False)
    val = to_examples(iter_jsonl([args.val]), chars)
    unseen = to_examples(iter_jsonl([args.unseen]), chars) if args.unseen else []
    print(f"данные: train {len(train)}, val {len(val)}, unseen {len(unseen)}, символов {len(chars)}, "
          f"{time.perf_counter() - t0:.0f} с, устройство {device}", flush=True)  # fmt: skip

    model = Tagger(len(chars) + 2, hidden=args.hidden, emb=args.emb).to(device)
    n_params = sum(p.numel() for p in model.parameters())
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
    steps_per_epoch = sum(1 for _ in batches(train, args.batch, None))
    sched = torch.optim.lr_scheduler.OneCycleLR(
        opt, max_lr=args.lr, total_steps=args.epochs * steps_per_epoch, pct_start=0.1
    )
    rnd = random.Random(args.seed)
    args.out.mkdir(parents=True, exist_ok=True)
    best, bad_epochs, log, start = -1.0, 0, [], 1
    last = args.out / "last.pt"
    if args.resume and last.exists():
        # продолжение после падения: веса, оптимизатор, расписание lr, RNG и счётчики ранней остановки
        st = torch.load(last, map_location=device, weights_only=False)
        model.load_state_dict(st["state"])
        opt.load_state_dict(st["opt"])
        sched.load_state_dict(st["sched"])
        sched.total_steps = args.epochs * steps_per_epoch  # --epochs при продолжении можно увеличить
        rnd.setstate(st["rnd"])
        torch.set_rng_state(st["torch_rng"])
        best, bad_epochs, log, start = st["best"], st["bad_epochs"], st["log"], st["epoch"] + 1
        print(f"продолжаем с эпохи {start}, лучший val F1 {best:.4f}", flush=True)
    for epoch in range(start, args.epochs + 1):
        te, total, nb = time.perf_counter(), 0.0, 0
        for b in batches(train, args.batch, rnd):
            chars_t, case_t, cls_t, tags_t, lengths_t = tensors(b, device)
            loss = model.crf.nll(model.emissions(chars_t, case_t, cls_t, lengths_t), tags_t, lengths_t)
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            opt.step()
            sched.step()
            total += loss.item()
            nb += 1
        v = evaluate(model, val, device)
        u = evaluate(model, unseen, device) if unseen else {"f1": float("nan")}
        rec = {"epoch": epoch, "loss": total / nb, "val_f1": v["f1"], "unseen_f1": u["f1"],
               "val_by_label": v["by_label"], "sec": round(time.perf_counter() - te, 1)}  # fmt: skip
        log.append(rec)
        print(f"эпоха {epoch}: loss {rec['loss']:.4f}, val F1 {v['f1']:.4f}, unseen F1 {u['f1']:.4f}, "
              f"{rec['sec']} с", flush=True)  # fmt: skip
        if float(v["f1"]) > best:  # type: ignore[arg-type]
            best, bad_epochs = float(v["f1"]), 0  # type: ignore[arg-type]
            torch.save(
                {
                    "state": model.state_dict(),
                    "chars": chars,
                    "hparams": {"hidden": args.hidden, "emb": args.emb},
                    "max_len": MAX_LEN,
                    "epoch": epoch,
                    "val": v,
                    "unseen": u,
                    "data_sha256": sha256_files([args.train, *args.extra]),
                    "data_files": [p.name for p in [args.train, *args.extra]],
                    "seed": args.seed,
                    "n_params": n_params,
                },
                args.out / "best.pt",
            )
        else:
            bad_epochs += 1
        (args.out / "log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
        state = {"state": model.state_dict(), "opt": opt.state_dict(), "sched": sched.state_dict(),
                 "rnd": rnd.getstate(), "torch_rng": torch.get_rng_state(), "best": best, "bad_epochs": bad_epochs,
                 "log": log, "epoch": epoch}  # fmt: skip
        torch.save(state, last.with_suffix(".tmp"))
        last.with_suffix(".tmp").replace(last)  # атомарно: падение во время записи не портит прошлый last.pt
        if bad_epochs >= args.patience:
            print(f"ранняя остановка: {args.patience} эпохи без улучшения", flush=True)
            break
    print(f"лучший val F1 {best:.4f}, параметров {n_params}, всего {time.perf_counter() - t0:.0f} с")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
