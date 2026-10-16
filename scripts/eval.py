"""Метрика жюри (ТЗ, раздел 4).

    python scripts/eval.py predictions.json gold.json [--strict-fp] [--top 30] [--json report.json]

Сравнение по каждому полю отдельно: нижний регистр, удалить пунктуацию, схлопнуть пробелы, посимвольно.
  адрес   60%: province, city, street_name, house
  детали  25%: apartment, entrance, floor
  справка 15%: district, living_area, только если значение есть в самой строке
Эталон null + наш null -> запись исключена по полю. Эталон null + наше значение -> исключено
(по ТЗ это «поднято из справочника»), с --strict-fp считается ошибкой.

Разметка эталона может явно указать, какие поля взяты не из строки: "_from_reference": ["district"].
Иначе для district/living_area «есть в строке» определяется подстрокой нормализованного значения в raw_address.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jana_address import io_format

GROUPS: dict[str, tuple[float, tuple[str, ...]]] = {
    "address": (0.60, ("province", "city", "street_name", "house")),
    "details": (0.25, ("apartment", "entrance", "floor")),
    "reference": (0.15, ("district", "living_area")),
}
EXTRA_FIELDS = ("street_type", "landmark")  # в метрику не входят, печатаем для себя
_ws = re.compile(r"\s+")


def norm(v: Any) -> str:
    if v is None:
        return ""
    s = str(v).lower()
    # ТЗ: «удалить пунктуацию» понимаем буквально (символ удаляется, а не заменяется пробелом)
    s = "".join(" " if unicodedata.category(ch)[0] == "Z" or ch in "\t\n\r" else ch for ch in s)
    s = "".join(ch for ch in s if unicodedata.category(ch)[0] not in "PC")
    return _ws.sub(" ", s).strip()


def in_string(value: Any, raw: Any) -> bool:
    n = norm(value)
    return bool(n) and n in norm(raw)


@dataclass
class FieldStat:
    correct: int = 0
    total: int = 0
    excluded: int = 0
    fp: int = 0  # эталон null, мы что-то вернули
    errors: list[dict[str, Any]] = field(default_factory=list)

    @property
    def acc(self) -> float:
        return self.correct / self.total if self.total else float("nan")


def load(path: Path) -> list[dict[str, Any]]:
    return io_format.loads(path.read_bytes())[0]


def align(pred: list[dict[str, Any]], gold: list[dict[str, Any]]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    gold_ids = [g.get("id") for g in gold]
    if len(set(map(str, gold_ids))) == len(gold_ids):
        by_id = {str(p.get("id")): p for p in pred}
        return [(by_id.get(str(g.get("id")), {}), g) for g in gold]
    return list(zip(pred, gold, strict=False))


def evaluate(pred: list[dict[str, Any]], gold: list[dict[str, Any]], strict_fp: bool = False) -> dict[str, Any]:
    stats: dict[str, FieldStat] = defaultdict(FieldStat)
    per_record: list[tuple[float, bool]] = []
    for p, g in align(pred, gold):
        raw = g.get("raw_address")
        from_ref = set(g.get("_from_reference") or [])
        rec_ok, rec_counted = True, 0
        for gname, (_, fields) in GROUPS.items():
            for f in fields:
                gv, pv = g.get(f), p.get(f)
                st = stats[f]
                if gv is None or norm(gv) == "":
                    if pv is not None and norm(pv) != "":
                        st.fp += 1
                        if strict_fp:
                            st.total += 1
                            st.errors.append({"field": f, "gold": gv, "pred": pv, "raw": raw})
                            rec_ok = False
                            rec_counted += 1
                            continue
                    st.excluded += 1
                    continue
                if gname == "reference" and (f in from_ref or ("_from_reference" not in g and not in_string(gv, raw))):
                    st.excluded += 1
                    continue
                st.total += 1
                rec_counted += 1
                if norm(pv) == norm(gv):
                    st.correct += 1
                else:
                    rec_ok = False
                    st.errors.append({"field": f, "gold": gv, "pred": pv, "raw": raw})
        for f in EXTRA_FIELDS:
            gv, pv = g.get(f), p.get(f)
            if gv is None:
                continue
            st = stats[f]
            st.total += 1
            if norm(pv) == norm(gv):
                st.correct += 1
            else:
                st.errors.append({"field": f, "gold": gv, "pred": pv, "raw": raw})
        if rec_counted:
            conf = p.get("confidence")
            per_record.append((float(conf) if isinstance(conf, int | float) else 0.0, rec_ok))

    groups: dict[str, dict[str, float]] = {}
    for gname, (w, fields) in GROUPS.items():
        c = sum(stats[f].correct for f in fields)
        t = sum(stats[f].total for f in fields)
        accs = [stats[f].acc for f in fields if stats[f].total]
        groups[gname] = {
            "weight": w,
            "pooled": c / t if t else float("nan"),
            "mean": sum(accs) / len(accs) if accs else float("nan"),
            "n": t,
        }

    def total(kind: str) -> float:
        num = sum(v["weight"] * v[kind] for v in groups.values() if v["n"])
        den = sum(v["weight"] for v in groups.values() if v["n"])
        return num / den if den else float("nan")

    return {
        "score": total("pooled"),
        "score_mean_variant": total("mean"),
        "groups": groups,
        "fields": {
            f: {"acc": s.acc, "correct": s.correct, "total": s.total, "excluded": s.excluded, "fp": s.fp}
            for f, s in stats.items()
        },
        "calibration": calibration(per_record),
        "errors": [e for s in stats.values() for e in s.errors],
        "records": len(gold),
    }


def calibration(items: list[tuple[float, bool]], bins: int = 10) -> dict[str, Any]:
    buckets: list[list[tuple[float, bool]]] = [[] for _ in range(bins)]
    for c, ok in items:
        buckets[min(bins - 1, max(0, int(c * bins)))].append((c, ok))
    rows, ece = [], 0.0
    n = len(items) or 1
    for i, b in enumerate(buckets):
        if not b:
            continue
        mc = sum(c for c, _ in b) / len(b)
        acc = sum(ok for _, ok in b) / len(b)
        ece += len(b) / n * abs(mc - acc)
        rows.append({"bin": f"{i / bins:.1f}-{(i + 1) / bins:.1f}", "n": len(b), "conf": mc, "acc": acc})
    return {"ece": ece, "bins": rows}


def print_report(rep: dict[str, Any], top: int) -> None:
    pct = lambda x: "  n/a " if x != x else f"{x * 100:5.1f}%"  # noqa: E731
    print(f"\nЗаписей: {rep['records']}")
    print(f"ИТОГ (пул по группе): {pct(rep['score'])}    вариант «среднее по полям»: {pct(rep['score_mean_variant'])}")
    for g, v in rep["groups"].items():
        print(f"  {g:<10} вес {v['weight']:.2f}  пул {pct(v['pooled'])}  среднее {pct(v['mean'])}  n={v['n']}")
    print("\nПо полям:")
    for g, (_, fields) in GROUPS.items():
        for f in (*fields,) if g else ():
            s = rep["fields"].get(f, {"acc": float("nan"), "correct": 0, "total": 0, "excluded": 0, "fp": 0})
            print(f"  {f:<12} {pct(s['acc'])}  {s['correct']}/{s['total']}  искл={s['excluded']}  fp={s['fp']}")
    for f in EXTRA_FIELDS:
        s = rep["fields"].get(f)
        if s:
            print(f"  {f:<12} {pct(s['acc'])}  {s['correct']}/{s['total']}  (вне метрики)")
    cal = rep["calibration"]
    print(f"\nКалибровка confidence (запись верна целиком), ECE={cal['ece']:.3f}")
    for r in cal["bins"]:
        print(f"  {r['bin']}  n={r['n']:<5} conf={r['conf']:.2f}  acc={r['acc']:.2f}")
    errs = rep["errors"]
    if errs:
        print(f"\nТоп ошибок (всего {len(errs)}):")
        by_field = Counter(e["field"] for e in errs)
        print("  " + ", ".join(f"{k}: {v}" for k, v in by_field.most_common()))
        for e in errs[:top]:
            print(f"  [{e['field']}] эталон={e['gold']!r} мы={e['pred']!r}\n      {e['raw']!r}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pred", type=Path)
    ap.add_argument("gold", type=Path)
    ap.add_argument("--strict-fp", action="store_true")
    ap.add_argument("--top", type=int, default=30)
    ap.add_argument("--json", type=Path, help="сохранить отчёт в JSON")
    args = ap.parse_args(argv)
    rep = evaluate(load(args.pred), load(args.gold), args.strict_fp)
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    print_report(rep, args.top)
    if args.json:
        args.json.write_text(json.dumps(rep, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
