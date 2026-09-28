# Развёртывание ДомСигнала

Три режима: **локальная проверка** одной командой Docker, **разработка** без Docker и
**production** (VPS за Caddy с TLS). Подробный журнал сервера —
[`deploy/README.md`](../deploy/README.md), выпуск и восстановление витрины —
[`RELEASE.md`](RELEASE.md), эксплуатация — [`OPERATIONS.md`](OPERATIONS.md).

## Что нужно

| Режим | Требования |
|---|---|
| Проверка в Docker | Docker Engine 24+ с Compose v2 (проверено: Docker 28.3, Compose 2.39), 4 ГБ свободной памяти, свободный порт 8000 (или `API_PORT`) |
| Разработка | Python 3.12, `uv` 0.12, Node.js 24 LTS, PostgreSQL 16 |
| Production | Linux VPS с Docker, публичный домен (сейчас `domsignal.176-108-244-168.sslip.io`), токен бота MAX от организаторов, ключ Cloud.ru — по желанию |

## Локально — одна команда

```bash
git clone https://github.com/Qward1/MAX_hack.git && cd MAX_hack
docker compose up --build
```

Порядок старта задаёт `compose.yaml`: `db` (healthcheck `pg_isready`) → `migrate`
(`alembic upgrade head`, одноразовый) → `seed` (демо-данные, одноразовый) → `api`
(healthcheck `/health`), `worker` (операционный пул), `ai-worker` (пул модели).
Готовность: `curl http://localhost:8000/ready` → `{"status":"ready"}`.

**Замер 28.09.2026** (чистый клон ветки финальной версии, Windows 11, Docker Desktop
28.3, базовые образы уже скачаны): `docker compose build --no-cache` — **34 с**
(лимит задания — 5 минут); от `up -d` до `ready` — **20 с**.

Переменные для локального запуска задавать не нужно — `compose.yaml` подставляет
безопасные локальные значения. Полный список — [`.env.example`](../.env.example),
пояснения — README, «Переменные окружения». Эмулятор MAX вместо настоящего бота:
`MAX_TRANSPORT=record PASSIVE_CAPTURE_ENABLED=true docker compose up --build -d`
(README, «Проверить бота без MAX»).

## Остановка, перезапуск, сброс

```bash
docker compose restart api          # любой сервис: api, worker, ai-worker, db
docker compose down                 # остановить, данные сохраняются в томе postgres-data
docker compose up -d                # снова, с прежними данными
docker compose down -v              # сбросить локальный стенд полностью (удалит том)
```

**Проверено 28.09.2026** на чистом клоне: после `restart` каждого из `api`,
`worker`, `ai-worker`, `db` и после `down` / `up -d` сервис готов за 0–4 с,
созданная до этого проблема на месте; при остановленном `worker` приём работает,
задачи ждут и выполняются после `start`. В очереди в покое — только пять
периодических задач с будущим временем запуска (`jobs.cleanup`, `chat.buffer.purge`,
`appeal.followup.tick`, `reception.reminder.tick`, `staff.digest.tick`).

## Разработка без Docker

```bash
uv sync --frozen                                   # Python-зависимости из uv.lock
npm --prefix miniapp ci                            # фронтенд из package-lock.json
export DATABASE_URL=postgresql+asyncpg://domsignal:domsignal@localhost:5432/domsignal
uv run alembic upgrade head
uv run python -m domsignal.tools.seed_demo
uv run uvicorn domsignal.main:app --reload         # API и собранное мини-приложение
uv run python -m domsignal.worker.main --pool operational
uv run python -m domsignal.worker.main --pool ai
npm --prefix miniapp run dev                       # Vite на :5173
```

## Production

Файлы: [`compose.prod.yaml`](../compose.prod.yaml) поверх `compose.yaml`,
[`deploy/Caddyfile`](../deploy/Caddyfile) (TLS Let's Encrypt, HSTS, журналы без
полных IP), секреты — `deploy/.env.production` (права 600, не в git; шаблон
переменных — `.env.example`). Production-настройки отвергают локальные значения:
тестовый вход, демо-данные, локальный ключ TOTP, режим эмулятора MAX.

```bash
export BUILD_COMMIT="$(git rev-parse HEAD)"
docker compose --project-name domsignal-prod --env-file deploy/.env.production \
  -f compose.yaml -f compose.prod.yaml up -d --build
curl --fail https://<домен>/ready          # {"status":"ready"}
curl https://<домен>/version               # commit = BUILD_COMMIT
curl -X POST https://<домен>/max/webhook   # 401 без секрета
```

Безопасная выкладка — [`deploy/README.md`](../deploy/README.md) §6: копия базы до
выкладки (`scripts/backup_postgres.py`), образ прежней версии под тегом
`domsignal-backend:pre-<sha>` для отката, миграция сначала на копии базы, затем
проверка выпуска `uv run python scripts/release_check.py --fetch`. Подписка вебхука
MAX — §5. Ежедневная копия базы — `domsignal-backup.timer` в 03:00 МСК, 14 копий.

## Проверки здоровья и журналы

| Что | Как |
|---|---|
| Процесс жив | `GET /health` → `{"status":"ok"}`; Docker healthcheck контейнера `api` |
| База доступна | `GET /ready` → `{"status":"ready"}` |
| Какая версия | `GET /version` → `commit`, версии пакетов регионов; боту — `/version` |
| Очереди, доставка, модель | кабинет платформы → «Обзор» и «Состояние системы»; `GET /api/v1/platform/health` |
| Витрина жюри | `scripts/showcase_check.py` (раз в сутки в `.github/workflows/uptime.yml`) |
| Внешний мониторинг | `.github/workflows/uptime.yml`: `/ready`, `/version`, вебхук 401, письмо при сбое |
| Журналы | `docker compose -p domsignal-prod … logs --tail=200 api worker ai-worker caddy`; строки «событие ключ=значение», запрос — `http_request` с `request_id` (= `trace_id` в ответе с ошибкой и заголовок `X-Request-ID`), без текстов жителей и полных IP; ротация 5 × 10 МБ |

## Если что-то не так

| Симптом | Причина и что сделать |
|---|---|
| `port is already allocated` | порт 8000 занят: `API_PORT=8080 docker compose up --build`, адрес — `http://localhost:8080` |
| `/ready` не отвечает минуту после старта | `docker compose ps` и `logs migrate` — миграция не прошла; `logs db` — нет памяти или диска |
| Вход сотрудника: «Слишком много попыток» | пауза 5 минут по логину или адресу — подождать или войти другим логином |
| Вход: «Неверный или уже использованный код» | один код TOTP дважды не принимается — дождаться следующего (30 с); проверить время на телефоне |
| Бот не отвечает в MAX (production) | `/ready`; вебхук без секрета должен давать 401; подписка — `deploy/README.md` §5; журнал `api` (события вебхука) |
| Сигналы из чата не появляются | чтение чата выключено («MAX-чаты» → «Включить чтение чата») или ещё не прошла пауза окна (production — 30 секунд тишины, затем до минуты на разбор) |
| Модель не отвечает, кончился баланс | ничего не делать: окна разбирают правила, опасность — всегда правила; обзор платформы показывает долю окон у правил |
| Сломана витрина жюри | `docs/RELEASE.md`, «Восстановление витрины» — каждый инвариант штатной командой |
