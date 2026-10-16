# CLAUDE.md

Хакатон Jana Post x Terricon Valley, кейс «Jana Address»: разбор однострочного адреса РК на поля + восстановление по собственному справочнику. Подробности в README.md, docs/ARCHITECTURE.md, docs/REFERENCE.md, открытые вопросы в docs/QUESTIONS.md.

## Команды

```bash
.venv/Scripts/python -m pytest -q                 # все тесты (~1 с)
.venv/Scripts/ruff check src scripts tests && .venv/Scripts/ruff format src scripts tests
.venv/Scripts/mypy                                # strict
.venv/Scripts/python -m uvicorn jana_address.api.app:app --reload
.venv/Scripts/python -m jana_address.cli IN.json OUT.json [--explain]
.venv/Scripts/python scripts/eval.py PRED.json GOLD.json [--strict-fp]
.venv/Scripts/python scripts/build_reference/build_sqlite.py [--osm ...] [--kato ...]   # после правки seed/*.yaml
.venv/Scripts/python scripts/export_openapi.py && (cd frontend && npm run gen:api)    # после правки API-моделей
cd frontend && npm run build && npx biome check src                                    # сборка коммитится
```

## Архитектура (коротко)

* `src/jana_address/pipeline/` — шаги `clean → tokenize → split_bilingual → admin → details → street → landmark → numbers → leftover → reference → confidence`, порядок в `steps.py`. Общение только через `ParseState` (`base.py`).
* `src/jana_address/rules/*.yaml` — словари (маркеры, типы улиц, ориентиры, admin-маркеры, веса confidence). Загрузка и индексы фраз: `rules_loader.py`.
* `src/jana_address/reference/` — `normalize.py` (fold/translit только для сравнения), `store.py` (read-only SQLite + индексы, rapidfuzz).
* `src/jana_address/api/` — FastAPI: `routes_parse.py` (батч/одна строка), `routes_sessions.py` + `sessions.py` (UI, правки в отдельной edits.sqlite).
* `scripts/build_reference/` — сборка справочника (seed YAML, OSM через pyosmium + shapely, КАТО).
* `frontend/` — React/Vite/TS strict/Tailwind v4/TanStack; `vite build` пишет в `src/jana_address/static`.

## Жёсткие правила (от них зависит метрика и допуск)

* `id`, `raw_address` возвращаются байт в байт; ровно один ответ на запись, порядок сохраняется; исключение на записи даёт все поля null (runner.parse_record).
* Неопределённое поле = `null`, не `""`. null лучше неверного значения: при сомнении ставить флаг и понижать confidence, а не угадывать.
* `street_name`/`landmark` вырезаются из ОРИГИНАЛЬНОЙ строки по спану (`util.value_from`): без исправления опечаток, падежа и регистра. `fold()`/`norm()` только для сравнения, никогда для вывода.
* Строковое значение никогда не перезаписывается справочным (`ParseState.set_field`). Источник: `string` | `reference:<seed|osm|kato>` | `manual`.
* ЗАПРЕЩЕНО: сопоставление по id, кэш/таблица по целой строке, запоминание train.json. В справочнике только топонимы. Не ставить `lru_cache` на функции разбора целой строки (кэш по отдельным токенам/топонимам можно). Проверка: `tests/test_no_memorization.py`.
* Никаких сетевых вызовов в рантайме. Сеть только в `scripts/build_reference/download.py`.
* `data/` в .gitignore и .dockerignore. Строки train.json не копировать в тесты, фикстуры и коммиты.

## Соглашения

* Python 3.12, mypy strict, ruff (line 120). Комментарии и docstring по-русски, коротко, о «почему».
* Новый паттерн по возможности добавлять в YAML, а не в код. Новый кейс добавлять в `tests/test_e2e.py` (сквозной) и/или `tests/test_steps.py` (на шаг).
* Невидимые символы в исходниках только escape-последовательностями (`"​"`), не литералами.
* Расхождение с форматом жюри / неоднозначность фиксировать в docs/QUESTIONS.md с выбранным безопасным вариантом.
* Коммиты маленькие и логические; после каждого шага решение должно оставаться сдаваемым (батч отвечает на каждую запись).
