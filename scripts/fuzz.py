"""Фаззинг пайплайна: случайный и «злой» ввод не должен ронять разбор, зависать или выдумывать значения.

    python scripts/fuzz.py [--n 5000] [--seed 1] [--show 20] [--tagger on]

Инварианты на каждой записи:
  * pipeline.run не бросает исключение (защита runner.parse_record срабатывать не должна: это баг);
  * время разбора одной строки < --max-ms (ловит катастрофический backtracking в регулярках);
  * строковые поля (source=string) есть в исходной строке (после удаления невидимых символов и пробелов);
  * confidence в [0, 1]; на строке без букв и цифр все поля null.
Код возврата 1, если есть нарушения. Короткий прогон этого же генератора: tests/test_fuzz.py.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
import unicodedata
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jana_address import engine, io_format
from jana_address.models import PARSED_FIELDS
from jana_address.pipeline.runner import explain_extra, parse_record, state_to_result
from jana_address.pipeline.util import strip_invisible

STRING_FIELDS = ("street_name", "house", "apartment", "entrance", "floor", "landmark", "living_area")
SEEDS = [
    "г. Алматы, ул. Абая 150/2, кв 5",
    "Нурсити 2 микрорайон 11дом 5 подьезд 239 кв",
    "город Актобе/Ақтөбе қаласы, проспект Абилкайыр хана 52, кв 14",
    "66квартал 12дом 69квартира",
    "Ул .Курильская 9 кв 1",
    "Astana, Mangilik El 55, flat 191",
    "Шымкент, Qazpost Солнечный",
    "Алматинская обл., Карасайский р-н, с. Каскелен, ул. Абая 5, напротив магазина Береке",
]
WORDS = ["ул", "кв", "д", "дом", "мкр", "г", "р-н", "подъезд", "этаж", "Абая", "Алматы", "көшесі", "ЖК", "пр-т", "№"]
JUNK = [
    "",
    " ",
    "\u200b\u200b\u200b",
    "....",
    ",,,;;;",
    "-/-/-",
    "null",
    "None",
    "N/A",
    "нет адреса",
    "???",
    "👍🏠📦",
    "<script>alert(1)</script>",
    "'; DROP TABLE houses; --",
    '{"a": [1, 2]}',
    "https://example.kz/address?id=1",
    "test@mail.kz",
    "+7 (777) 123-45-67",
    "87771234567",
    "050000",
    "1234567890" * 20,
    "кв кв кв кв кв кв кв кв",
    "д д д д 1 2 3 4 5 6 7 8 9",
    "ул. ул. ул. ул.",
    "/" * 500,
    "1/2/3/4/5/6/7/8/9/10/11/12",
    "а" * 5000,
    "Абая " * 2000,
    "\u202eАбая 10\u202c",
    "А\u0301баа\u0308 10",
    "\x00\x01\x02 ул Абая 1",
    "\t\n\r ул\tАбая\n10\r",
    "ﾟ･✿ヾ╲(｡◕‿◕｡)╱✿･ﾟ",
    "Иванову Ивану Ивановичу",
    "до востребования",
]


def mutate(rnd: random.Random, s: str) -> str:
    """Случайная порча строки: удаление/вставка/перестановка символов, слов, разделителей, регистра."""
    ops = rnd.randint(1, 6)
    chars = list(s)
    for _ in range(ops):
        op = rnd.random()
        if not chars:
            chars = list(rnd.choice(SEEDS))
        i = rnd.randrange(len(chars))
        if op < 0.2:
            del chars[i]
        elif op < 0.4:
            chars.insert(i, rnd.choice(" ,.;/-\u00a0\u200b0123456789абвгдеёжзийклмнопрстуфхцчшщыэюяәғқңөұүі"))
        elif op < 0.5 and i + 1 < len(chars):
            chars[i], chars[i + 1] = chars[i + 1], chars[i]
        elif op < 0.6:
            chars.insert(i, rnd.choice(WORDS) + rnd.choice([" ", "", "."]))
        elif op < 0.7:
            chars = [c.upper() if rnd.random() < 0.5 else c.lower() for c in chars]
        elif op < 0.8:
            words = "".join(chars).split()
            rnd.shuffle(words)
            chars = list(" ".join(words))
        elif op < 0.9:
            chars = list(re.sub(r"[ ,]", lambda _: rnd.choice([" ", ",", ";", " / ", "|", "", "  "]), "".join(chars)))
        else:
            chars.insert(
                i, chr(rnd.choice([rnd.randint(0x20, 0x7E), rnd.randint(0x400, 0x4FF), rnd.randint(0x2000, 0x206F)]))
            )
    return "".join(chars)


def random_unicode(rnd: random.Random) -> str:
    blocks = [(0x20, 0x7E), (0x400, 0x4FF), (0x4E00, 0x4FFF), (0x600, 0x6FF), (0x1F300, 0x1F64F), (0x2000, 0x206F)]
    out = []
    for _ in range(rnd.randint(1, 80)):
        lo, hi = rnd.choice(blocks)
        out.append(chr(rnd.randint(lo, hi)))
    return "".join(out)


def gen(rnd: random.Random, n: int) -> list[str]:
    out = list(JUNK)
    while len(out) < n:
        r = rnd.random()
        if r < 0.6:
            out.append(mutate(rnd, rnd.choice(SEEDS)))
        elif r < 0.8:
            out.append(random_unicode(rnd))
        else:
            out.append(" ".join(rnd.choice([*WORDS, str(rnd.randint(0, 999))]) for _ in range(rnd.randint(1, 30))))
    return out[:n]


def squash(s: str) -> str:
    """Для проверки «значение есть в строке»: без невидимых символов (тот же набор, что выбрасывает tidy_value),
    пробелов, кавычек (литера дома «85 "А"» -> «85 А») и регистра."""
    s = unicodedata.normalize("NFC", strip_invisible(s))
    return re.sub(r'[\s"«»“”„]+', "", s).lower()


def roundtrip(rec: dict[str, Any]) -> list[str]:
    """Полный путь жюри: parse_record + сериализация ответа. Ответ должен закодироваться в UTF-8 целиком, а
    id/raw_address прочитаться обратно тем же значением."""
    try:
        res = parse_record(engine.get_pipeline(), rec)
        body = io_format.dumps([res], io_format.Container("list")).encode("utf-8")
        back = json.loads(body)[0]
    except Exception as exc:
        return [f"сериализация: {exc!r}"]
    if back["id"] != rec["id"] or back["raw_address"] != rec["raw_address"]:
        return ["id/raw_address изменены после сериализации"]
    return []


def check(raw: str, max_ms: float) -> list[str]:
    pipe = engine.get_pipeline()
    rec: dict[str, Any] = {"id": "fz", "raw_address": raw}
    t0 = time.perf_counter()
    try:
        state = pipe.run(raw)
    except Exception as exc:
        return [f"исключение {exc!r}"]
    ms = (time.perf_counter() - t0) * 1000
    problems = []
    if ms > max_ms:
        problems.append(f"медленно {ms:.0f} мс")
    out = state_to_result(rec, state)
    if out["id"] != "fz" or not isinstance(out["raw_address"], str) or out["raw_address"] != raw:
        problems.append("id/raw_address изменены")
    problems += roundtrip(rec)
    conf = out.get("confidence")
    if not isinstance(conf, int | float) or not 0 <= conf <= 1:
        problems.append(f"confidence={conf!r}")
    fields = explain_extra(state)["fields"]
    # строка в английской раскладке перекодируется той же длины (pipeline/layout.py): значения ищем и в ней
    hay = squash(raw) + ("\x00" + squash(state.raw) if "layout_fixed" in state.flags else "")
    for f in STRING_FIELDS:
        v = out.get(f)
        if v is None:
            continue
        if v == "":
            problems.append(f"{f}='' вместо null")
        elif fields.get(f, {}).get("source") == "string" and squash(v) not in hay:
            problems.append(f"{f}={v!r} нет в строке")
    if not any(ch.isalnum() for ch in raw) and any(out.get(f) is not None for f in PARSED_FIELDS):
        problems.append("поля заполнены у строки без букв и цифр")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=5000)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--max-ms", type=float, default=200.0)
    ap.add_argument("--show", type=int, default=20)
    ap.add_argument("--tagger", choices=["off", "shadow", "on", "only"], help="режим теггера (JANA_TAGGER)")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    if args.tagger:
        os.environ["JANA_TAGGER"] = args.tagger
        engine.reset()
    engine.get_pipeline()
    print(f"теггер: {engine.info().get('tagger')}")
    engine.get_pipeline().run("г. Алматы, ул. Абая 1")  # прогрев: индексы справочника строятся лениво
    bad: list[tuple[str, list[str]]] = []
    t0 = time.perf_counter()
    inputs = gen(random.Random(args.seed), args.n)
    for raw in inputs:
        p = check(raw, args.max_ms)
        if p:
            bad.append((raw, p))
    dt = time.perf_counter() - t0
    print(f"{len(inputs)} строк за {dt:.1f} с, нарушений: {len(bad)}")
    for raw, p in bad[: args.show]:
        shown = raw if len(raw) < 160 else raw[:160] + f"... ({len(raw)} симв.)"
        print(f"  {'; '.join(p)}\n      {shown!r}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
