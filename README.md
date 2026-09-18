# ДомСигнал

Проверяемый архитектурный каркас: тестовый житель создаёт вручную
категоризированный сигнал, backend сохраняет `Report` и `Incident` в PostgreSQL,
а mini app показывает доску дома и карточку после перезагрузки.

Это этап `FND-01`, а не полный продукт. Реальная доставка MAX, групповые чаты,
юридические маршруты, обращения, напоминания и AI-функции пока не реализованы.

## Быстрый запуск

Нужны Docker Engine с Compose v2. Локальные MAX- и LLM-секреты не нужны.

```bash
docker compose up --build
```

После готовности сервисов откройте <http://localhost:8000>. При первом входе
mini app получает только локальную тестовую сессию пользователя `demo`. Данные
хранятся в volume PostgreSQL.

```bash
docker compose down       # остановить, сохранив данные
docker compose up -d      # повторный запуск с прежними данными
```

Сброс — только для явно выбранного собственного тестового окружения после
проверки Compose project/БД/volumes. Общие/dev/prod данные не сбрасываются
локальной проверкой; обычная остановка сохраняет volume.

Для параллельной работы используйте разные project names:

```bash
docker compose -p domsignal-dev-a up --build
```

## Локальная разработка

Требуются Python 3.12, `uv`, Node.js 24 LTS и PostgreSQL 16.

```bash
uv sync --frozen --group dev
npm --prefix=miniapp ci
uv run alembic upgrade head
uv run python -m domsignal.tools.seed_demo
uv run uvicorn domsignal.main:app --reload --port 8000
npm --prefix=miniapp run dev
```

По умолчанию API слушает `8000`, Vite — `5173`, PostgreSQL в Compose — только
внутри сети. В production overlay Caddy публикует `80/443`; запуск overlay
требует безопасных переменных окружения и HTTPS-домена.

## Проверки

Зависимости устанавливаются отдельно; runner их не переустанавливает.

```bash
uv run python scripts/check.py --scope backend
uv run python scripts/check.py --scope frontend
uv run python scripts/check.py --scope contracts
DATABASE_URL=postgresql+asyncpg://... uv run python scripts/check.py --scope integration
uv run python scripts/check.py --scope all
```

OpenAPI и TypeScript-типы обновляются явно:

```bash
uv run python scripts/export_openapi.py
npm --prefix=miniapp run api:generate
```

## Режимы и безопасность

- `local`: `MAX_TRANSPORT=off`, `LLM_PROVIDER=rules`, разрешена явная тестовая
  сессия и demo seed.
- `test`: то же, плюс допустим `MAX_TRANSPORT=recording` для проверок worker.
- `production`: запрещены test-session, demo seed, demo DB credentials,
  recording transport, wildcard CORS, HTTP public URL и стандартный session secret.

Тестовая авторизация вызывается отдельным endpoint и не включается заголовком
пользователя. Deep link или `house_id` в query не создаёт membership. Сессии
хранятся как HMAC-хеш, raw MAX `initData` не сохраняется.

## Фактический тестовый путь

1. Открыть mini app; в local она получает сессию явно тестового жителя.
2. Нажать «Сообщить», выбрать категорию вручную и ввести описание.
3. После сохранения открыть карточку на доске.
4. Перезагрузить страницу — карточка читается из PostgreSQL.
5. Повтор API-команды с тем же `Idempotency-Key` и телом возвращает тот же
   результат; другое тело получает `409 application/problem+json`.

## Что реально и что запланировано

Реальны PostgreSQL, миграция, house-scoped authorization, API C0, серверная
проверка подписи MAX initData, durable jobs/leases, recording/off transport,
OpenAPI/TS contract и UI board/detail. Нормализованный replay — тестовый вход,
а не доказательство совместимости с live payload MAX.

Не проверены live MAX webhook/initData на реальном клиенте, публичный TLS-стенд
и правовые правила. Route/appeal endpoints не опубликованы и UI их не обещает.
Для поставки готовим проверяемый собственный API по A-13. Не хватает официального
шаблона DATA-API.yaml; решение готовить API и обязательные проверки уже принято
по [Q&A](docs/decisions.md#qa-alignment-2026-09-18).

## Чеклист технической сдачи — PLANNED / NOT RUN

Owner A-12/A-13/B-11 — DEV-B; AI provider/evaluation evidence — DEV-A.
Это критерии будущей поставки, не новый PASS текущего документационного commit.

- [ ] Чистый клон выбранного release SHA → документированная конфигурация без
  секретов в Git → Docker → миграции → изолированные тестовые данные → проверки
  → restart API/worker без потери истории. Указать версии, команды и результат.
- [ ] Измеренная сборка не более **5 минут без первоначальной загрузки базовых
  образов**; приложить время/условия замера. Старый smoke не доказывает этот gate.
- [ ] HTTPS base URL собственного API доступен на весь период проверки;
  runtime OpenAPI 3.0/3.1 согласно ТЗ и generated TS соответствуют producer.
- [ ] Безопасные проверочные учётные записи/доступы нужных ролей и изолированные
  данные позволяют проверить positive/negative scope без production test-login
  или админского bypass. Доступы передаются проверяющим безопасным каналом.
- [ ] Обязательные API-проверки: схема/status/headers/required fields, auth/scope/
  actions, persistence readback, timeout/repeat/conflict/concurrency и безопасные
  ошибки по [API DoD](docs/CONTRACTS.md#definition-of-done-продуктовых-api).
- [ ] DATA-API.yaml по официальной схеме организаторов. **MISSING INPUT:**
  шаблон не найден; не создавать official schema_version и не объявлять
  самодельный/архивный формат совместимым с проверяющей платформой.
- [ ] Раздельное evidence A unit/contract, B HTTP/services/PostgreSQL/worker и
  C live MAX/LLM. Локальное воспроизведение не требует внешних секретов;
  `transport=off` не реальная интеграция. Рабочий MAX-стенд с разрешённым ботом,
  HTTPS, ролями и реальными клиентами проверяется отдельно по
  [MAX_LIVE_SMOKE](docs/MAX_LIVE_SMOKE.md), сейчас NOT RUN / PENDING TOKEN.
- [ ] Локальные проверки не меняют общий webhook и не сбрасывают общие данные.
  [DB runbook](deploy/database.md) требует явно выбранную тестовую БД; перед
  интеграционными fixtures, которые очищают её, проверить DATABASE_URL.
- [ ] Партнёр согласовал раздельное хранение переписки, рабочей истории и
  юридически значимых запросов/ответов по [матрице №416](docs/PRODUCT_ARCHITECTURE.md#пп-рф-416--документальная-сверка-18092026).
  Короткий TTL переписки не применяется ко всем объектам.

Семантика API: [docs/CONTRACTS.md](docs/CONTRACTS.md). Фактическая структура:
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

Согласованная цель: [ARCH-PLATFORM-v1](docs/PRODUCT_ARCHITECTURE.md) — tenant УК,
проверяемые подключения, отдельный web-кабинет и Ticket. Это TARGET; текущие
возможности и refs — в [IMPLEMENTATION_CONTEXT](IMPLEMENTATION_CONTEXT.md),
очерёдность — в [ROADMAP](ROADMAP.md).
