"""Сравнение режимов разбора rules / tagger / hybrid на отложенных наборах и решение о включении hybrid.

    python scripts/compare_modes.py [--sets dev_synth_s2 dev_chaos_holdout dev_chaos_v2_holdout dev_hard_holdout unseen]
                                    [--out docs/hybrid_results.md]

rules: только правила; tagger: поля только из модели (canonical через справочник); hybrid: правила + теггер +
арбитр. Наборы из data/: dev_* в формате эталона; unseen = data/tagger/unseen.jsonl (улицы и населённые пункты,
которых не было в обучении теггера: проверка обобщения, а не запоминания).

Правило включения (docs/ARCHITECTURE.md, «Гибридный разбор»): hybrid по умолчанию, только если на каждом решающем
наборе (dev_synth_s2, dev_chaos_holdout, dev_chaos_v2_holdout) итог не ниже rules и ни одно поле метрики не хуже
rules больше чем на 0.3 п. После выдачи данных решающий набор: data/dev_gold.json (--sets dev_gold).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from scripts.eval import GROUPS, WEAK_TAGS, evaluate, load, predict  # noqa: E402

DECISIVE = ("dev_synth_s2", "dev_chaos_holdout", "dev_chaos_v2_holdout")
DEFAULT_SETS = (*DECISIVE, "dev_hard_holdout", "unseen")
MODES = ("rules", "tagger", "hybrid")
METRIC_FIELDS = tuple(f for _, fs in GROUPS.values() for f in fs)
MAX_FIELD_DROP = 0.003
EXTRA_TAGS = ("numbered_street", "street_type_last", "street_marker_typo", "junk_prefix", "person", "city_last")


def load_set(name: str) -> list[dict[str, Any]]:
    if name == "unseen":
        rows = [json.loads(line) for line in (ROOT / "data" / "tagger" / "unseen.jsonl").open(encoding="utf-8")]
        return [
            {"id": f"u{i}", "raw_address": r["raw"], **{k: v for k, v in r.items() if k not in ("raw", "spans")},
             "_tags": r.get("tags", [])}
            for i, r in enumerate(rows)
        ]  # fmt: skip
    return load(ROOT / "data" / f"{name}.json")


def pct(x: float) -> str:
    return "n/a" if x != x else f"{x * 100:.1f}%"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sets", nargs="+", default=list(DEFAULT_SETS))
    ap.add_argument("--modes", nargs="+", default=list(MODES), choices=MODES)
    ap.add_argument("--out", type=Path, help="markdown-отчёт")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

    reports: dict[str, dict[str, dict[str, Any]]] = {}
    timing: dict[str, dict[str, float]] = {}
    for name in args.sets:
        gold = load_set(name)
        reports[name], timing[name] = {}, {}
        for mode in args.modes:
            t0 = time.perf_counter()
            pred = predict(gold, mode)
            timing[name][mode] = time.perf_counter() - t0
            reports[name][mode] = evaluate(pred, gold)
            rep = reports[name][mode]
            ece, sec = rep["calibration"]["ece"], timing[name][mode]
            print(f"{name:<22} {mode:<7} ИТОГ {pct(rep['score'])}  ECE {ece:.3f}  {sec:.1f} с", flush=True)

    lines = ["| Набор | " + " | ".join(args.modes) + " |", "|---|" + "---:|" * len(args.modes)]
    for name in args.sets:
        lines.append(f"| {name} | " + " | ".join(pct(reports[name][m]["score"]) for m in args.modes) + " |")
    lines += ["", "**По полям метрики** (rules → hybrid):", "", "| Набор | " + " | ".join(METRIC_FIELDS) + " |",
              "|---|" + "---:|" * len(METRIC_FIELDS)]  # fmt: skip
    for name in args.sets:
        if "rules" in reports[name] and "hybrid" in reports[name]:
            r, h = reports[name]["rules"]["fields"], reports[name]["hybrid"]["fields"]
            cells = [f"{pct(r.get(f, {}).get('acc', float('nan')))} → {pct(h.get(f, {}).get('acc', float('nan')))}"
                     for f in METRIC_FIELDS]  # fmt: skip
            lines.append(f"| {name} | " + " | ".join(cells) + " |")
    tags = [
        t for t in (*WEAK_TAGS, *EXTRA_TAGS) if any(t in reports[n][m]["tags"] for n in args.sets for m in args.modes)
    ]
    lines += ["", "**Слабые теги** (запись верна целиком, все наборы вместе):", "",
              "| Тег | n | " + " | ".join(args.modes) + " |", "|---|---:|" + "---:|" * len(args.modes)]  # fmt: skip
    for t in tags:
        cells, n = [], 0
        for m in args.modes:
            ok = tot = 0
            for name in args.sets:
                v = reports[name][m]["tags"].get(t)
                if v:
                    ok += v["ok"] * v["n"]
                    tot += v["n"]
            n = max(n, tot)
            cells.append(pct(ok / tot) if tot else "n/a")
        lines.append(f"| {t} | {n} | " + " | ".join(cells) + " |")
    lines += ["", "**Калибровка confidence (ECE)**:", "", "| Набор | " + " | ".join(args.modes) + " |",
              "|---|" + "---:|" * len(args.modes)]  # fmt: skip
    for name in args.sets:
        lines.append(
            f"| {name} | " + " | ".join(f"{reports[name][m]['calibration']['ece']:.3f}" for m in args.modes) + " |"
        )

    verdict = decide(reports)
    lines += ["", f"**Решение:** {verdict}"]
    text = "\n".join(lines)
    print("\n" + text)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    return 0


def decide(reports: dict[str, dict[str, dict[str, Any]]]) -> str:
    sets = [s for s in DECISIVE if s in reports and {"rules", "hybrid"} <= set(reports[s])]
    if "dev_gold" in reports:
        sets = ["dev_gold"]
    if not sets:
        return "нет решающих наборов"
    problems = []
    for s in sets:
        r, h = reports[s]["rules"], reports[s]["hybrid"]
        if h["score"] < r["score"]:
            problems.append(f"{s}: итог {pct(h['score'])} < {pct(r['score'])}")
        for f in METRIC_FIELDS:
            a, b = r["fields"].get(f, {}).get("acc", float("nan")), h["fields"].get(f, {}).get("acc", float("nan"))
            if a == a and b == b and a - b > MAX_FIELD_DROP:
                problems.append(f"{s}: {f} {pct(b)} < {pct(a)}")
    if problems:
        return "hybrid НЕ включаем по умолчанию (" + "; ".join(problems) + ")"
    return f"hybrid включаем по умолчанию: не хуже rules на {', '.join(sets)}"


if __name__ == "__main__":
    raise SystemExit(main())
