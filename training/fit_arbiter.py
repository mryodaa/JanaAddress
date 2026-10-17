"""Подбор весов арбитра (rules/arbiter.yaml). Confidence подбирает training/fit_confidence.py.

    .venv/Scripts/python -m training.fit_arbiter [--sets dev_synth dev_chaos val] [--write]

Только dev-наборы: dev_synth.json, dev_chaos.json и val-синтетика теггера (после выдачи данных: dev_gold.json).
Отложенные наборы (dev_synth_s2, dev_chaos_holdout, dev_chaos_v2_holdout, dev_hard_holdout, unseen) не трогаются.

1) Арбитр: пайплайн в режиме shadow отдаёт по каждому полю кандидатов правил и модели с проверками (explain).
   Метка кандидата: его значение совпадает с эталоном по правилам метрики. Логистическая регрессия на признаках
   [источник, p по источнику, проверки] даёт веса прямо в шкале счёта арбитра (логит): prior, w_p, checks.
   Порог принятия поля «только модели» = логит 0.8.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from scripts.eval import load, norm  # noqa: E402

from jana_address import config  # noqa: E402
from jana_address.pipeline.runner import Pipeline, parse_records  # noqa: E402

CHECKS = ("ref_exists", "ref_consistent", "ref_conflict", "street_in_city", "street_fuzzy", "house_on_street",
          "area_in_city", "grammar_ok", "grammar_bad", "noise_overlap", "marker_only", "city_status")  # fmt: skip
FEATURES = ("src_rules", "src_model", "p_rules", "p_model", *CHECKS)
HOLDOUT = {"dev_synth_s2", "dev_chaos_holdout", "dev_chaos_v2_holdout", "dev_hard_holdout", "unseen"}
ACCEPT_P = 0.8


def load_set(name: str) -> list[dict[str, Any]]:
    # не assert: под python -O проверка исчезла бы, а подбор на отложенных портит оценку
    if name in HOLDOUT or name.endswith("_holdout"):
        raise SystemExit(f"{name} отложенный: подбор весов на нём запрещён")
    if name == "val":
        rows = [json.loads(line) for line in (ROOT / "data" / "tagger" / "val.jsonl").open(encoding="utf-8")]
        return [{"id": f"v{i}", "raw_address": r["raw"], **{k: v for k, v in r.items() if k not in ("raw", "spans")}}
                for i, r in enumerate(rows)]  # fmt: skip
    realish = ROOT / "data" / "realish" / f"{name}.json"  # почти реальный эталон (scripts/realish.py)
    return load(realish if realish.exists() else ROOT / "data" / f"{name}.json")


def candidate_rows(gold: list[dict[str, Any]], outs: list[dict[str, Any]]) -> tuple[np.ndarray, np.ndarray]:
    xs, ys = [], []
    for g, o in zip(gold, outs, strict=True):
        model = o.get("model") or {}
        from_ref = set(g.get("_from_reference") or [])
        for f, d in (model.get("fields") or {}).items():
            if f in from_ref:
                continue
            for src in ("rules", "model"):
                c = d.get(src)
                if not c:
                    continue
                x = dict.fromkeys(FEATURES, 0.0)
                x[f"src_{src}"] = 1.0
                x[f"p_{src}"] = float(c["p"])
                for k in c.get("checks", {}):
                    if k in x:
                        x[k] = 1.0
                xs.append([x[k] for k in FEATURES])
                ys.append(float(g.get(f) is not None and norm(c["value"]) == norm(g.get(f))))
    return np.array(xs), np.array(ys)


def logreg(x: np.ndarray, y: np.ndarray, l2: float = 1e-3, iters: int = 3000, lr: float = 0.5) -> np.ndarray:
    """Без свободного члена: его роль играют индикаторы источника (prior)."""
    w = np.zeros(x.shape[1])
    for _ in range(iters):
        p = 1 / (1 + np.exp(-(x @ w)))
        grad = x.T @ (p - y) / len(y) + l2 * w
        w -= lr * grad
    return w


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sets", nargs="+", default=["dev_synth", "dev_chaos", "val"])
    ap.add_argument("--write", action="store_true", help="записать веса в rules/arbiter.yaml")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    golds = {s: load_set(s) for s in args.sets}
    recs = {s: [{"id": g.get("id"), "raw_address": g.get("raw_address")} for g in gold] for s, gold in golds.items()}

    shadow = Pipeline(tagger_mode="shadow")
    xs, ys = [], []
    for s, gold in golds.items():
        x, y = candidate_rows(gold, parse_records(shadow, recs[s], explain=True))
        xs.append(x)
        ys.append(y)
        print(f"{s}: кандидатов {len(y)}, верных {y.mean():.3f}")
    x, y = np.concatenate(xs), np.concatenate(ys)
    w = {k: float(v) for k, v in zip(FEATURES, logreg(x, y), strict=True)}
    print("веса арбитра (логит):", {k: round(v, 2) for k, v in w.items()})

    path = config.RULES_DIR / "arbiter.yaml"
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    cfg["prior"] = {"rules": round(w["src_rules"], 3), "model": round(w["src_model"], 3)}
    cfg["w_p"] = {"rules": round(w["p_rules"], 3), "model": round(w["p_model"], 3)}
    cfg["rules_p"] = {"default": 1.0}  # p правил = score шага, калибровку несёт w_p.rules
    cfg["checks"] = {k: round(w[k], 3) for k in CHECKS}
    cfg["accept_model_only"] = {"default": round(math.log(ACCEPT_P / (1 - ACCEPT_P)), 3)}
    if args.write:
        # шапка с комментариями (до первой пустой строки) сохраняется, последняя её строка: на чём подобрано
        head = path.read_text(encoding="utf-8").split("\n\n", 1)[0].splitlines()
        head = [ln for ln in head if not ln.startswith("# подобрано на:")] + [f"# подобрано на: {', '.join(args.sets)}"]
        body = yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False, default_flow_style=None)
        path.write_text("\n".join(head) + "\n\n" + body, "utf-8")
        print(f"-> {path}")

    print("confidence подбирается отдельно: python -m training.fit_confidence --write")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
