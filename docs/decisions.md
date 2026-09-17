# ДомСигнал — журнал решений

Формат: дата — вопрос — принятое решение — причина — затронутые ID. Обычные шаги реализации здесь не записываются.

- 2026-09-17 — Владение и интеграция — DEV-A ведёт `dev/a-core` и по умолчанию является интегратором, DEV-B ведёт `dev/b-experience`, `main` принимает только обычные merge commits через PR — две постоянные зоны снижают пересечения и сохраняют историю long-running branches — BOOT-01, FND-01.
- 2026-09-17 — Граница продукта — продукт готовит маршрут и черновик, а официальный канал открывает пользователь; отметка жителя не выдаётся за внешнюю регистрацию — в текущем scope нет подтверждённой интеграции регистрации обращений — A-04, B-05.
- 2026-09-17 — Стартовая архитектурная граница — один backend package/image, API с webhook, отдельный PostgreSQL-backed worker, без Redis и микросервисов на старте — минимизирует инфраструктуру, сохраняя durable delivery boundary — FND-01, A-05, B-03.
- 2026-09-17 — Контур C0 — первый slice создаёт отдельный Report и Incident только при ручном выборе категории; routes/appeals отсутствуют и скрыты capabilities — каркас проверяет границы, не имитируя будущий golden path — FND-01, A-01…A-04, B-02…B-05.
- 2026-09-17 — Auth boundary — local/test session выдаётся отдельным endpoint для двух seeded actors, production запрещает bypass конфигурацией; house access следует только из membership — пользовательские headers, query и deep links не являются доказательством доступа — FND-01, A-07.
- 2026-09-17 — Frontend toolchain — Node 24 LTS в image/CI, `@maxhub/max-ui` 0.5.0 и его exact peers React/ReactDOM 19.2.8; TypeScript 5.9.3 выбран из-за peer range генератора OpenAPI — зависимости разрешены без force/legacy-peer-deps, UI contract воспроизводим — FND-01, B-02.
- 2026-09-17 — MAX foundation — официальный initData HMAC реализован серверно; outbound ограничен `off`/`recording`, normalized replay явно тестовый; API domain `platform-api2.max.ru` и live payload оставлены реальному transport — без credentials и live fixtures нельзя честно объявить MAX интеграцию — FND-01, B-01, B-03.
