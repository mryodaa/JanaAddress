# Jana Address

Сервис разбора однострочных адресов Казахстана на поля `province, city, district, living_area, street_type, street_name, house, apartment, entrance, floor, landmark` с осмысленным `confidence`. Район, жилой массив, город и область, которых нет в строке, восстанавливаются по собственному справочнику (OSM + КАТО + ручное ядро). Решение для хакатона Jana Post x Terricon Valley, кейс «Jana Address».

* правила и словари в YAML + справочник SQLite, без сетевых вызовов, LLM и геокодеров в рантайме;
* на каждую запись ровно один ответ, `id` и `raw_address` байт в байт, неизвестное поле = `null`;
* 1000 записей разбираются меньше чем за секунду (требование: 5 минут);
* UI оператора: загрузка пакета, таблица с подсветкой, правка с клавиатуры, экспорт, trace по шагам.

## Запуск одной командой

```bash
docker compose up --build
# http://localhost:8000      — интерфейс
# http://localhost:8000/docs — OpenAPI
```

Healthcheck compose ждёт `GET /api/v1/health` (готовность наступает меньше чем через секунду после старта: справочник грузится при старте).

## Как жюри прогоняет тестовый набор

**Через батч-эндпоинт** (файл как есть: JSON-тело или multipart):

```bash
curl -s -X POST http://localhost:8000/api/v1/parse/batch \
     -H "content-type: application/json" --data-binary @data/sample_input.json > out.json
# или файлом
curl -s -X POST http://localhost:8000/api/v1/parse/batch -F file=@data/sample_input.json > out.json
# источники полей и trace (для разбора на защите)
curl -s -X POST "http://localhost:8000/api/v1/parse/batch?explain=true" -F file=@data/sample_input.json
```

Форма ответа повторяет форму входа: массив → массив, объект `{"records": [...]}` → тот же ключ, JSONL → JSONL (см. `docs/QUESTIONS.md`, Q1).

**Через CLI** (запасной путь, без сервера):

```bash
docker compose run --rm -v "$PWD/data:/data" jana-address python -m jana_address.cli /data/sample_input.json /data/out.json
# локально
python -m jana_address.cli data/sample_input.json out.json
```

## Офлайн-сборка и готовый образ

Всё нужное лежит в репозитории: Linux-wheels в `vendor/wheels` (ставятся через `pip --no-index`), собранный фронт в `src/jana_address/static`, справочник в `reference/reference.sqlite`. Загрузок при старте нет.

```bash
docker build --network=none -t jana-address .   # проверка офлайн-сборки (нужен закешированный python:3.12-slim)
docker run --rm --network=none -p 8000:8000 jana-address
./scripts/export_image.sh                         # docker save -> jana-address.tar
docker load -i jana-address.tar && docker run --rm -p 8000:8000 jana-address:latest
```

Чек-лист офлайн-проверки (выполнить на машине с Docker): `docker build --network=none` проходит; контейнер healthy при `--network=none` за время меньше 3 минут; `python scripts/benchmark.py --api http://localhost:8000 --n 1000` укладывается в секунды.

`data/` (train, sample, dev_gold) исключён из git и из образа (`.gitignore`, `.dockerignore`).

## Разработка

```bash
python -m venv .venv && .venv/Scripts/activate          # Windows; Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"            # + ".[build]" для сборки справочника
uvicorn jana_address.api.app:app --reload
pytest -q                          # шаги, e2e, API, производительность, запрет запоминания
ruff check src scripts tests && ruff format --check src scripts tests && mypy
cd frontend && npm ci && npm run build && npm run lint   # сборка UI в src/jana_address/static
```

Типы фронта генерируются из схемы: `python scripts/export_openapi.py && cd frontend && npm run gen:api`.

## Пайплайн

`clean → tokenize → split_bilingual → admin → details → street → landmark → numbers → leftover → reference → confidence`. У каждого шага единый интерфейс (`ParseState → ParseState` + trace) и свои тесты. Подробно: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

Словари маркеров, типов улиц (с сокращениями, латиницей и казахскими формами), ориентиров и веса confidence лежат в `src/jana_address/rules/*.yaml`. Новый паттерн добавляется без правки кода.

## Справочник

`reference/reference.sqlite`: области, районы областей и городов, населённые пункты, микрорайоны/ЖК, улицы (с каз. и старыми названиями), дома с районом по геометрии. Источники, лицензии (OSM ODbL), пересборка и покрытие описаны в [docs/REFERENCE.md](docs/REFERENCE.md).

## Оценка

`scripts/eval.py` считает метрику жюри ровно по ТЗ: per-field сравнение после нижнего регистра, удаления пунктуации и схлопывания пробелов; веса 60/25/15; справочные поля только там, где они есть в строке. Печатает разбивку по полям, топ ошибок с исходными строками и калибровку confidence (ECE).

```bash
python -m jana_address.cli data/dev_gold.json out.json
python scripts/eval.py out.json data/dev_gold.json
python scripts/analyze_train.py data/train.json --unknown   # что добавить в словари
python scripts/label.py data/train.json data/dev_gold.json --n 300 --shard 0/3   # разметка командой
```

Текущие результаты: на собственных фикстурах (`tests/fixtures/dev_seed_gold.json`, кейсы из ТЗ) 100%, 50 e2e-кейсов зелёные. Это не независимая оценка: `train.json` и `sample_output.json` пока не выданы, поэтому настоящий dev-набор (`data/dev_gold.json`, 200–300 строк) ещё не размечен.

## Статус

Реализовано полностью: API (батч, одна строка, health, сессии, правки, экспорт), CLI, пайплайн из 11 шагов с trace и источниками полей, правила в YAML, метрика и инструменты разметки/анализа, UI, тесты (190+), офлайн-зависимости, Docker/compose.

Дальше:
1. Получить `train.json`/`sample_output.json`, сверить формат контейнера и ожидания (`docs/QUESTIONS.md`), разметить dev-набор, итерировать правила по `eval.py`.
2. Подключить КАТО (нужен файл классификатора с stat.gov.kz) и, по возможности, адресный регистр. OSM уже собран: 6900 населённых пунктов, 58 тыс. улиц, 1.18 млн домов.
3. Откалибровать веса confidence по dev-набору.
4. Проверить офлайн-сборку образа на машине с Docker.
