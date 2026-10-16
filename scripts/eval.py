"""Метрика жюри (ТЗ, раздел 4).

    python scripts/eval.py predictions.json gold.json [--strict-fp] [--top 30] [--json report.json]
                           [--baseline old_predictions.json] [--run rules|tagger|hybrid]

--run: сначала разобрать raw_address эталона в этом режиме и записать в predictions.json (rules: только правила,
tagger: поля только из модели, hybrid: правила + теггер + арбитр). Сравнение режимов разом: compare_modes.py.

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
# слабые места правил из docs/STATE.md: печатаются отдельным блоком
WEAK_TAGS = (
    "settlement",
    "city_kind:village",
    "house_letter",
    "no_commas",
    "district_written",
    "area_with_street",
    "case_upper",
    "case_lower",
)
# режим отчёта -> JANA_TAGGER
MODES = {"rules": "off", "tagger": "only", "hybrid": "on", "shadow": "shadow"}
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
    records: list[dict[str, Any]] = []  # по записи: какие поля метрики неверны (для --baseline и тегов)
    for p, g in align(pred, gold):
        raw = g.get("raw_address")
        from_ref = set(g.get("_from_reference") or [])
        rec_ok, rec_counted = True, 0
        wrong: list[str] = []
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
                            wrong.append(f)
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
                    wrong.append(f)
                    st.errors.append({"field": f, "gold": gv, "pred": pv, "raw": raw})
        records.append(
            {"id": g.get("id"), "raw": raw, "counted": rec_counted > 0, "wrong": wrong, "tags": g.get("_tags") or []}
        )
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
        "per_record": records,
        "tags": by_tag(records),
    }


def by_tag(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Доля записей, верных целиком по полям метрики, в разрезе тегов генератора (gen_dev.py)."""
    out: dict[str, dict[str, Any]] = {}
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in records:
        if r["counted"]:
            for t in r["tags"]:
                groups[t].append(r)
    for t, rs in groups.items():
        fields = Counter(f for r in rs for f in r["wrong"])
        out[t] = {"n": len(rs), "ok": sum(not r["wrong"] for r in rs) / len(rs), "wrong_fields": dict(fields)}
    return out


def compare(base: dict[str, Any], new: dict[str, Any], top: int) -> None:
    """Что изменилось относительно прошлого прогона на том же эталоне."""
    pct = lambda x: "  n/a " if x != x else f"{x * 100:5.1f}%"  # noqa: E731
    delta = lambda a, b: "" if a != a or b != b else f"{(b - a) * 100:+.1f}"  # noqa: E731
    a, b = base["score"], new["score"]
    print(f"\nСравнение с базой: ИТОГ {pct(a)} -> {pct(b)} ({delta(a, b)})")
    for f in (*(f for _, fs in GROUPS.values() for f in fs), *EXTRA_FIELDS):
        a, b = base["fields"].get(f, {}).get("acc", float("nan")), new["fields"].get(f, {}).get("acc", float("nan"))
        if a == a and b == b and abs(a - b) >= 0.0005:
            print(f"  {f:<12} {pct(a)} -> {pct(b)} ({delta(a, b)})")
    old = {str(r["id"]): r for r in base["per_record"]}
    fixed, broken = [], []
    for r in new["per_record"]:
        o = old.get(str(r["id"]))
        if o is None:
            continue
        if set(r["wrong"]) - set(o["wrong"]):
            broken.append((r, sorted(set(r["wrong"]) - set(o["wrong"]))))
        elif set(o["wrong"]) - set(r["wrong"]):
            fixed.append((r, sorted(set(o["wrong"]) - set(r["wrong"]))))
    print(f"  исправлено записей: {len(fixed)}, сломано: {len(broken)}")
    for r, fs in broken[:top]:
        print(f"  СЛОМАНО {','.join(fs)}: {r['raw']!r}")


def predict(gold: list[dict[str, Any]], mode: str) -> list[dict[str, Any]]:
    """Разбор raw_address эталона пайплайном в режиме mode (rules | tagger | hybrid | shadow)."""
    from jana_address.pipeline.runner import Pipeline, parse_records

    recs = [{"id": g.get("id"), "raw_address": g.get("raw_address")} for g in gold]
    return parse_records(Pipeline(tagger_mode=MODES[mode]), recs)


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
    if rep["tags"]:
        print("\nПо тегам (запись верна целиком; сначала худшие):")
        for t, v in sorted(rep["tags"].items(), key=lambda kv: kv[1]["ok"]):
            wf = ", ".join(f"{k}:{n}" for k, n in sorted(v["wrong_fields"].items(), key=lambda kv: -kv[1]))
            print(f"  {t:<28} {pct(v['ok'])}  n={v['n']:<5} {wf}")
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
    ap.add_argument("--baseline", type=Path, help="предсказания прошлого прогона: что исправлено и что сломано")
    ap.add_argument("--run", choices=list(MODES), help="разобрать эталон в этом режиме и записать в pred")
    args = ap.parse_args(argv)
    gold = load(args.gold)
    if args.run:
        args.pred.write_text(json.dumps(predict(gold, args.run), ensure_ascii=False, indent=1), encoding="utf-8")
    rep = evaluate(load(args.pred), gold, args.strict_fp)
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    print_report(rep, args.top)
    if args.baseline:
        compare(evaluate(load(args.baseline), gold, args.strict_fp), rep, args.top)
    if args.json:
        args.json.write_text(json.dumps(rep, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
