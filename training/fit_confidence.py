"""Подбор весов confidence (rules/confidence.yaml) логистической регрессией на dev-наборах.

    .venv/Scripts/python -m training.fit_confidence [--write]

Метка записи: все поля метрики, которые в ней считаются, совпали с эталоном (scripts/eval.py). Признаки берутся из
trace шага confidence (pipeline/confidence.features), разбор в режиме по умолчанию (hybrid).

Два этапа:
1) форма: логистическая регрессия на синтетике (--shape: dev_synth, dev_chaos, val), где записей и ошибок много;
   флаг реже MIN_COUNT раз в модель не входит (данных о нём нет, вес 0);
2) уровень: калибровка Платта (a*z + b) на почти реальном эталоне (--level: llm_dev, egov_dev). Доля верных записей
   на синтетике ниже (её эталон пишет город каноном, Q22), поэтому абсолютный уровень берём с живых строк,
   ближайших к набору жюри. Итог остаётся одной логистической регрессией: веса формы умножены на a.

Выбор схемы и L2: кросс-валидация на dev (по наборам и по записям realish). Отложенные наборы печатаются только
итогом, ошибки на них не смотрим.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from scripts.eval import calibration, evaluate, load  # noqa: E402

from jana_address import config, rules_loader  # noqa: E402
from jana_address.pipeline.runner import Pipeline, parse_records  # noqa: E402
from training.fit_arbiter import load_set  # noqa: E402

BASE = ("consumed", "street_name", "house", "admin", "unparsed", "no_street_house", "min_score")
MIN_COUNT = 30
L2_SHAPE = 10.0
SHAPE_SETS = ["dev_synth", "dev_chaos", "val"]
LEVEL_SETS = ["llm_dev", "egov_dev"]
CHECK_SETS = ["dev_synth_s2", "dev_chaos_holdout", "dev_chaos_v2_holdout", "dev_hard_holdout", "llm_holdout",
              "egov_holdout"]  # fmt: skip

Rows = list[tuple[dict[str, float], bool]]


def _load_any(name: str) -> list[dict[str, Any]]:
    realish = ROOT / "data" / "realish" / f"{name}.json"
    return load(realish if realish.exists() else ROOT / "data" / f"{name}.json")


def rows(pipe: Pipeline, gold: list[dict[str, Any]]) -> Rows:
    """(признаки, запись верна) по записям, где метрика что-то считает."""
    recs = [{"id": g.get("id"), "raw_address": g.get("raw_address")} for g in gold]
    outs = parse_records(pipe, recs, explain=True)
    rep = evaluate(outs, gold)
    res = []
    for o, r in zip(outs, rep["per_record"], strict=True):
        if not r["counted"]:
            continue
        step = next((t for t in o.get("trace") or [] if t.get("step") == "confidence"), None)
        feats = ((step or {}).get("changes") or {}).get("features")
        if feats is not None:  # строка без слов и чисел: confidence фиксирован
            res.append((feats, not r["wrong"]))
    return res


def fit(x: np.ndarray, y: np.ndarray, l2: float, iters: int = 50) -> np.ndarray:
    """Логистическая регрессия Ньютоном (IRLS), первый столбец x = 1 (свободный член, без штрафа)."""
    w = np.zeros(x.shape[1])
    reg = np.full(x.shape[1], l2)
    reg[0] = 0.0
    for _ in range(iters):
        p = 1 / (1 + np.exp(-(x @ w)))
        grad = x.T @ (p - y) + reg * w
        hess = (x * (p * (1 - p))[:, None]).T @ x + np.diag(reg + 1e-9)
        step = np.linalg.solve(hess, grad)
        w -= step
        if np.abs(step).max() < 1e-8:
            break
    return w


def design(data: Rows, names: list[str]) -> tuple[np.ndarray, np.ndarray]:
    x = np.array([[1.0, *(f.get(k, 0.0) for k in names)] for f, _ in data])
    return x, np.array([float(ok) for _, ok in data])


def ece(p: np.ndarray, y: np.ndarray) -> float:
    return float(calibration([(float(c), bool(ok)) for c, ok in zip(np.clip(p, 0.02, 0.99), y, strict=True)])["ece"])


def ece_of(pipe: Pipeline, name: str) -> tuple[float, float, int]:
    gold = _load_any(name)
    outs = parse_records(pipe, [{"id": g.get("id"), "raw_address": g.get("raw_address")} for g in gold])
    rep = evaluate(outs, gold)
    return rep["calibration"]["ece"], rep["score"], len(gold)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--shape", nargs="+", default=SHAPE_SETS, help="dev-наборы для формы (много записей)")
    ap.add_argument("--level", nargs="+", default=LEVEL_SETS, help="dev-наборы для уровня (живые строки)")
    ap.add_argument("--check", nargs="*", default=CHECK_SETS, help="наборы для итоговой проверки ECE (только итог)")
    ap.add_argument("--write", action="store_true", help="записать веса в rules/confidence.yaml")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

    pipe = Pipeline()
    sets: dict[str, Rows] = {}
    for s in [*args.shape, *args.level]:
        sets[s] = rows(pipe, load_set(s))
        ok = sum(ok for _, ok in sets[s]) / max(1, len(sets[s]))
        print(f"{s}: записей {len(sets[s])}, верных целиком {ok:.3f}")
    shape = [r for s in args.shape for r in sets[s]]
    level = [r for s in args.level for r in sets[s]]

    counts: dict[str, int] = {}
    for f, _ in shape:
        for k in f:
            if k.startswith("flag:"):
                counts[k] = counts.get(k, 0) + 1
    flags = sorted(k for k, c in counts.items() if c >= MIN_COUNT)
    rare = sorted(k for k, c in counts.items() if c < MIN_COUNT)
    names = [*BASE, *flags]

    xs, ys = design(shape, names)
    w = fit(xs, ys, L2_SHAPE)
    xl, yl = design(level, names)
    zl = xl @ w
    b, a = fit(np.c_[np.ones(len(zl)), zl], yl, 0.0)
    final = w * a
    final[0] += b
    print(f"\nуровень (Платт на {', '.join(args.level)}): z' = {a:.3f} * z {b:+.3f}")
    print(f"свободный член {final[0]:+.3f}")
    for k, v in zip(names, final[1:], strict=True):
        print(f"  {k:<36} {v:+.3f}   n={counts.get(k, len(shape))}")
    print(f"редкие флаги (< {MIN_COUNT} раз, вес 0): {', '.join(f'{k[5:]}={counts[k]}' for k in rare) or '-'}")
    sig = lambda z: 1 / (1 + np.exp(-z))  # noqa: E731
    ece_level = ece(sig(xl @ final), yl)
    print(f"ECE на {', '.join(args.level)}: {ece_level:.3f}; на синтетике формы: {ece(sig(xs @ final), ys):.3f}")

    if not args.write:
        return 0
    cfg = {
        "intercept": round(float(final[0]), 3),
        "features": {k: round(float(v), 3) for k, v in zip(BASE, final[1 : 1 + len(BASE)], strict=True)},
        "flags": {k[5:]: round(float(v), 3) for k, v in zip(flags, final[1 + len(BASE) :], strict=True)},
    }
    head = [
        "# Веса confidence (pipeline/confidence.py): p = sigmoid(intercept + сумма весов признаков), клип 0.02..0.99,",
        "# p = вероятность, что все поля метрики в записи верны; веса подбирает training/fit_confidence.py.",
        f"# форма: {', '.join(args.shape)} ({len(shape)} записей), уровень: {', '.join(args.level)} ({len(level)}),"
        f" ECE на уровне {ece_level:.3f}",
        f"# флаги реже {MIN_COUNT} раз не входят (вес 0): {', '.join(k[5:] for k in rare) or '-'}",
    ]
    cpath = config.RULES_DIR / "confidence.yaml"
    body = yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False)
    cpath.write_text("\n".join(head) + "\n\n" + body, "utf-8", newline="\n")  # LF и на Windows
    print(f"-> {cpath}")
    rules_loader.get_rules.cache_clear()
    pipe = Pipeline()
    print("\nПроверочные наборы (только итог):")
    for s in args.check:
        e, sc, n = ece_of(pipe, s)
        print(f"  {s:<24} n={n:<5} метрика {sc * 100:5.1f}%   ECE {e:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
