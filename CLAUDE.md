# CLAUDE.md

Хакатон Jana Post x Terricon Valley, кейс «Jana Address»: разбор однострочного адреса РК на поля + восстановление по собственному справочнику. Подробности в README.md, docs/ARCHITECTURE.md, docs/REFERENCE.md, открытые вопросы в docs/QUESTIONS.md.

## Команды

```bash
.venv/Scripts/python -m pytest -q                 # все тесты (~1 с)
.venv/Scripts/ruff check src scripts tests && .venv/Scripts/ruff format src scripts tests
.venv/Scripts/mypy                                # strict
.venv/Scripts/python -m uvicorn jana_address.api.app:app --reload
.venv/Scripts/python -m jana_address.cli IN.json OUT.json [--explain]
.venv/Scripts/python scripts/eval.py PRED.json GOLD.json [--strict-fp] [--baseline OLD_PRED.json]
.venv/Scripts/python scripts/gen_dev.py --n 1000 --seed 1 [--chaos]   # синтетический dev-набор -> data/dev_synth.json
.venv/Scripts/python scripts/fuzz.py --n 20000                 # инварианты на мусорном вводе, код 1 при нарушениях
# справочник (docs/REFERENCE.md): геометрия только здесь, рантайм читает готовые привязки из SQLite
.venv/Scripts/python scripts/build_reference/osm_survey.py                     # разведка дампа -> docs/OSM_SURVEY.md
.venv/Scripts/python scripts/build_reference/osm_extract.py && .venv/Scripts/python scripts/build_reference/assign_districts.py
.venv/Scripts/python scripts/build_reference/build_sqlite.py --osm scripts/build_reference/cache/osm_assigned --kato scripts/build_reference/cache/kato.json   # после правки seed/*.yaml
.venv/Scripts/python scripts/build_reference/gen_landmarks.py                  # бренды POI -> rules/landmarks_osm.yaml
.venv/Scripts/python scripts/coverage_report.py IN.json [--db OLD.sqlite]      # доля восстановленных полей по источникам
.venv/Scripts/python scripts/export_openapi.py && (cd frontend && npm run gen:api)    # после правки API-моделей
cd frontend && npm run build && npx biome check src                                    # сборка коммитится
# теггер (docs/ARCHITECTURE.md, «Гибридный разбор»); torch только в .venv-train (requirements-train.txt)
.venv/Scripts/python scripts/gen_train_tagger.py --n 150000 --seed 1001 --split train --out data/tagger/train.jsonl
.venv-train/Scripts/python -m training.train --train data/tagger/train.jsonl --val data/tagger/val.jsonl --unseen data/tagger/unseen.jsonl --out training/runs/v2 --resume
.venv-train/Scripts/python -m training.export --run training/runs/v2 --val data/tagger/val.jsonl --unseen data/tagger/unseen.jsonl --out models
.venv/Scripts/python -m training.fit_arbiter --write          # веса арбитра, только dev
.venv/Scripts/python -m training.fit_confidence --write       # веса confidence (после арбитра), только dev; руками не править
.venv/Scripts/python scripts/compare_modes.py --out docs/hybrid_results.md   # rules / tagger / hybrid на отложенных
.venv/Scripts/python scripts/eval.py PRED.json GOLD.json --run hybrid        # разобрать эталон в режиме и оценить
# почти реальный эталон (train.json не выдадут): data/realish/, компактная разметка -> JSON, проверка, сплит dev/holdout
.venv/Scripts/python scripts/realish.py lines data/realish/llm/*.txt --tag src:llm --prefix llm_ --out data/realish/llm.json
.venv/Scripts/python scripts/realish.py validate data/realish/llm.json && .venv/Scripts/python scripts/realish.py split data/realish/llm.json
.venv/Scripts/python scripts/build_reference/download.py egov && .venv/Scripts/python scripts/realish.py egov --out data/realish/egov/raw.txt
```

## Архитектура (коротко)

* `src/jana_address/pipeline/` — шаги `layout → clean → tokenize → split_bilingual → parts → admin → details → street → landmark → numbers → building → leftover → [tagger → arbiter] → reference → confidence`, порядок в `steps.py`. Общение только через `ParseState` (`base.py`). tagger/arbiter есть, если `JANA_TAGGER` не `off` (по умолчанию см. `config.DEFAULT_TAGGER_MODE`).
* `src/jana_address/tagger/` — посимвольный теггер: `features.py` (общие с training/), `crf.py` (Витерби/маргиналы на numpy), `runtime.py` (onnxruntime). Артефакт `models/tagger.onnx` + `tagger_meta.json`.
* `training/` — обучение (torch, вне образа), экспорт ONNX int8, подбор весов арбитра; `scripts/synth/` — генератор с посимвольными спанами.
* `src/jana_address/rules/*.yaml` — словари (маркеры, типы улиц, ориентиры, admin-маркеры, веса confidence). Загрузка и индексы фраз: `rules_loader.py`.
* `src/jana_address/reference/` — `normalize.py` (fold/translit только для сравнения), `store.py` (read-only SQLite + индексы, rapidfuzz).
* `src/jana_address/api/` — FastAPI: `routes_parse.py` (батч/одна строка), `routes_sessions.py` + `sessions.py` (UI, правки в отдельной edits.sqlite).
* `scripts/build_reference/` — сборка справочника (seed YAML, OSM через pyosmium + shapely, КАТО).
* `frontend/` — React/Vite/TS strict/Tailwind v4/TanStack; `vite build` пишет в `src/jana_address/static`.

## Жёсткие правила (от них зависит метрика и допуск)

* `id`, `raw_address` возвращаются байт в байт; ровно один ответ на запись, порядок сохраняется; исключение на записи даёт все поля null (runner.parse_record).
* Неопределённое поле = `null`, не `""`. null лучше неверного значения: при сомнении ставить флаг и понижать confidence, а не угадывать. Исключение (решение команды, Q20): справочный district/living_area по улице в нескольких районах ставится лучшим кандидатом с флагом.
* `street_name`/`landmark` вырезаются из ОРИГИНАЛЬНОЙ строки по спану (`util.value_from`): без исправления опечаток, падежа и регистра. `fold()`/`norm()` только для сравнения, никогда для вывода.
* Строковое значение никогда не перезаписывается справочным (`ParseState.set_field`). Источник: `string` | `reference:osm:<house|street|polygon|point|poi>` | `reference:<seed|kato>` | `manual`.
* Справочник: shapely/osmium/геометрия только в `scripts/build_reference/`, в рантайме только индексные запросы. Синтетика (gen_dev, gen_train_tagger, test_synth_spans) читает снапшот `reference/reference.synth_v1.sqlite` (`config.SYNTH_DB`), а не основной файл: иначе пересборка справочника сдвигает отложенные наборы и split unseen.
* ЗАПРЕЩЕНО: сопоставление по id, кэш/таблица по целой строке, запоминание train.json. В справочнике только топонимы. Не ставить `lru_cache` на функции разбора целой строки (кэш по отдельным токенам/топонимам можно). Проверка: `tests/test_no_memorization.py`.
* Никаких сетевых вызовов в рантайме. Сеть только в `scripts/build_reference/download.py`.
* `data/` в .gitignore и .dockerignore. Строки train.json не копировать в тесты, фикстуры и коммиты.
* Теггер только предлагает спаны: значение строкового поля всегда срез raw (`util.value_from`/`tidy_value`), canonical через справочник. Веса арбитра подбирать только на dev (dev_synth, dev_chaos, val, data/realish/*_dev), не на отложенных (dev_synth_s2, dev_chaos_holdout, dev_chaos_v2_holdout, dev_hard_holdout, unseen, data/realish/*_holdout). На *_holdout не смотреть ошибки, только итог. Seed 1, 2, 11, 99, 4242, 4343 заняты dev/отложенными наборами.
* Не запускать тяжёлое параллельно с обучением: памяти мало, torch падает с access violation (есть `--resume`).
* Невидимые символы: инструмент Write превращает `\u200b` в литерал; после записи .py проверять скан на литеральные невидимые символы.

## Соглашения

* Python 3.12, mypy strict, ruff (line 120). Комментарии и docstring по-русски, коротко, о «почему».
* Новый паттерн по возможности добавлять в YAML, а не в код. Новый кейс добавлять в `tests/test_e2e.py` (сквозной) и/или `tests/test_steps.py` (на шаг).
* Невидимые символы в исходниках только escape-последовательностями (`"\u200b"`), не литералами.
* Расхождение с форматом жюри / неоднозначность фиксировать в docs/QUESTIONS.md с выбранным безопасным вариантом.
* Коммиты маленькие и логические; после каждого шага решение должно оставаться сдаваемым (батч отвечает на каждую запись).
