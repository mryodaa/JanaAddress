"""Статистика по train.json, чтобы направлять работу над правилами.

    python scripts/analyze_train.py data/train.json [--top 40] [--unknown]

Печатает: долю латиницы/казахских букв/слэшей/невидимых символов, частые слова (кандидаты в маркеры),
типы слитного написания, частые первые сегменты (город/область), длины, и с --unknown частые слова,
которые не покрываются ни одним словарём rules/*.yaml (что добавить в правила).
Ничего не сохраняет и строки целиком не индексирует (ТЗ, раздел 7).
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jana_address import io_format

INVISIBLE = {"\u200b", "\u200c", "\u200d", "\u2060", "\ufeff", "\u00a0", "\u00ad"}
KAZ = set("әғқңөұүһіӘҒҚҢӨҰҮҺІ")
WORD = re.compile(r"[^\W\d_]+", re.UNICODE)
GLUED_NUM_WORD = re.compile(r"\d+[^\W\d_]{2,}")
GLUED_WORD_NUM = re.compile(r"[^\W\d_]{3,}\d+")
SLASH_WORDS = re.compile(r"[^\W\d_]\s*/\s*[^\W\d_]")
SLASH_NUMS = re.compile(r"\d\s*/\s*\d")


def known_vocab() -> set[str]:
    try:
        from jana_address.rules_loader import all_marker_words

        return all_marker_words()
    except Exception:
        return set()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", type=Path)
    ap.add_argument("--top", type=int, default=40)
    ap.add_argument("--unknown", action="store_true", help="частые слова вне словарей правил")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

    records, cont = io_format.loads(args.path.read_bytes())
    raws = [r.get("raw_address") or "" for r in records]
    n = len(raws) or 1
    print(f"Записей: {len(raws)}  контейнер: {cont.kind} {cont.key or ''}")

    def share(pred: object) -> str:
        c = sum(1 for s in raws if pred(s))  # type: ignore[operator]
        return f"{c:6d}  {c / n * 100:5.1f}%"

    print("\nПризнаки строк:")
    print("  пустые                ", share(lambda s: not s.strip()))
    print("  латиница              ", share(lambda s: re.search(r"[A-Za-z]", s) is not None))
    print("  казахские буквы       ", share(lambda s: any(ch in KAZ for ch in s)))
    print("  слэш между словами    ", share(lambda s: SLASH_WORDS.search(s) is not None))
    print("  слэш между цифрами    ", share(lambda s: SLASH_NUMS.search(s) is not None))
    print("  невидимые символы     ", share(lambda s: any(ch in INVISIBLE for ch in s)))
    print("  управляющие символы   ", share(lambda s: any(unicodedata.category(ch) == "Cc" for ch in s)))
    print("  цифра+слово слитно    ", share(lambda s: GLUED_NUM_WORD.search(s) is not None))
    print("  слово+цифра слитно    ", share(lambda s: GLUED_WORD_NUM.search(s) is not None))
    print("  двойные пробелы       ", share(lambda s: "  " in s))
    print("  пробел перед точкой   ", share(lambda s: " ." in s))

    inv = Counter(f"U+{ord(ch):04X}" for s in raws for ch in s if ch in INVISIBLE or unicodedata.category(ch) == "Cc")
    if inv:
        print("  символы:", ", ".join(f"{k}×{v}" for k, v in inv.most_common()))

    lens = sorted(len(s) for s in raws)
    print(
        f"\nДлина: медиана {lens[len(lens) // 2] if lens else 0}, p95 {lens[int(len(lens) * 0.95)] if lens else 0},"
        f" max {lens[-1] if lens else 0}"
    )

    words = Counter(w.lower() for s in raws for w in WORD.findall(s))
    print(f"\nЧастые слова (top {args.top}):")
    print("  " + ", ".join(f"{w}×{c}" for w, c in words.most_common(args.top)))

    glued = Counter(re.sub(r"\d+", "N", m.lower()) for s in raws for m in GLUED_NUM_WORD.findall(s))
    print("\nСлитное «число+слово» (N = число):")
    print("  " + ", ".join(f"{w}×{c}" for w, c in glued.most_common(args.top)))
    glued2 = Counter(re.sub(r"\d+", "N", m.lower())[-6:] for s in raws for m in GLUED_WORD_NUM.findall(s))
    print("Слитное «слово+число» (хвост):")
    print("  " + ", ".join(f"{w}×{c}" for w, c in glued2.most_common(20)))

    first = Counter(s.split(",")[0].strip().lower()[:40] for s in raws if "," in s)
    print("\nЧастые первые сегменты (до запятой):")
    print("  " + "; ".join(f"{w}×{c}" for w, c in first.most_common(args.top)))

    segs = Counter(len(s.split(",")) for s in raws)
    print("\nЧисло сегментов через запятую:", dict(sorted(segs.items())))

    if args.unknown:
        vocab = known_vocab()
        unk = Counter({w: c for w, c in words.items() if w not in vocab and len(w) > 1})
        print(f"\nЧастые слова вне словарей rules/*.yaml (словарь: {len(vocab)} слов):")
        print("  " + ", ".join(f"{w}×{c}" for w, c in unk.most_common(args.top * 2)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
