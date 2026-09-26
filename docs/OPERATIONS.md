# ДомСигнал — эксплуатация

Короткая памятка: сборка, запуск, выкладка, наблюдение, нагрузочные прогоны.
Выкладка по шагам — [deploy/README.md](../deploy/README.md) («Safe redeploy»),
масштаб — [SCALING.md](SCALING.md).

## Сборка — замер (ТЗ, стр. 9: не дольше 5 минут)

27.09.2026, срез D5.

| Что | Значение |
|---|---|
| Исходник | чистый `git clone --branch main` с GitHub, `main` = `443943d` (код сервера совпадает с выложенным `39e3dcc`, lock-файлы в D5 не менялись) |
| Подготовка | базовые образы скачаны заранее (`node:24.21.0-bookworm-slim`, `python:3.12.11-slim-bookworm`, `postgres:16.10-bookworm`), кеш сборки очищен (`docker builder prune -af`) |
| Команда | `docker compose build --no-cache` |
| Время | **37 с** (самые долгие шаги: `apt-get` 15 с, `pip install uv` 14 с, `npm run build` 9,9 с, `npm ci` 9,7 с; стадии фронтенда и Python идут параллельно) |
| Образ | `domsignal-backend:local`, 344 МБ |
| Машина | Windows 11 Pro, AMD Ryzen 5 7500F (6 ядер / 12 потоков), 32 ГБ ОЗУ; Docker Desktop 28.3.2, ВМ Docker — 12 CPU, 15,4 ГБ |

Время зависит от сети: зависимости npm и PyPI скачиваются при сборке.
Базовые образы в замер не входят (их скачивание — разовое).

## Запуск локально

```
docker compose up -d --build
```

API — `http://localhost:8000`, демо-данные включены (`DEMO_SEED=true`), MAX
выключен (`MAX_TRANSPORT=off`), модель — правила (`LLM_PROVIDER=rules`).
Проверка — `uv run python scripts/docker_smoke.py`.

## Переменные масштаба (D5)

| Переменная | По умолчанию | Production | Смысл |
|---|---|---|---|
| `AI_WORKER_CONCURRENCY` | 1 | 2 | параллельные вызовы модели в процессе `ai-worker`, не больше `LLM_MAX_CONCURRENCY` |
| `OPERATIONAL_WORKER_CONCURRENCY` | 1 | 1 | параллельные циклы операционного пула |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | 5 / 10 | 5 / 10 | пул соединений на процесс |

Процессы × (размер + запас) ≤ `max_connections` PostgreSQL (100 по
умолчанию); три процесса production — 45.

## Наблюдение

- `GET /ready`, `GET /version` (SHA и версии слоёв справочника).
- Обзор платформы (`/platform-admin/`): очередь по пулам и возраст самой
  старой задачи, доля окон у правил за 24 ч, бюджет модели сегодня,
  готовность справочника.
- `.github/workflows/uptime.yml` — внешняя проверка `/ready`, `/version`,
  webhook 401, письмо о сбое.
- Копии БД — `domsignal-backup.timer` (03:00 МСК, 14 копий).
- Очередь чистится сама: `jobs.cleanup` раз в час (выполненные старше 14
  дней, упавшие старше 30).

## Нагрузочные прогоны

Локально, на своей PostgreSQL:

```
DATABASE_URL=postgresql+asyncpg://.../domsignal_load \
  uv run python scripts/load_ingest.py --chats 1000 \
  --profile evaluation/reports/2026-09-27-d1-load-profile.json --rate 2 --duration 780 \
  --ai-processes 4 --ai-concurrency 4 --operational-concurrency 2 --i-own-this-database
```

На железе production — только изолированный стек со своей БД, без портов
наружу и с лимитами CPU/ОЗУ (`deploy/load/compose.load.yaml`, проект
`domsignal-load`), в окно 01:00–07:00 МСК, с проверкой `/ready` живого
сервиса раз в 10 с; после прогона — `docker compose -p domsignal-load … down -v`.

Сквозные сценарии продукта на своей БД — `uv run python scripts/scenario_run.py`.
