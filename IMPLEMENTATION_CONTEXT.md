# ДомСигнал — implementation context

## Назначение

Рабочий путь продукта: чат или личное сообщение → инцидент → проверяемый маршрут → редактируемый черновик → официальный канал руками пользователя → отметка жителя и наблюдение результата. Продукт не утверждает, что сам зарегистрировал обращение во внешней системе.

## Утверждённая цель ARCH-PLATFORM-v1

Владелец согласовал [целевую архитектуру](docs/PRODUCT_ARCHITECTURE.md):
общий бот/одна Mini App, tenant УК и периоды управления домом, независимые
назначения и проверяемое подключение чатов, отдельный веб-кабинет и ограниченная
рабочая очередь Ticket. Это TARGET / NOT IMPLEMENTED BY THIS DOCUMENT.
Report, Incident, Ticket и ExternalAppeal разделены; self-report и отчёт
исполнителя не подтверждают внешнюю регистрацию и результат жителем.
Tenant isolation, onboarding, кабинет и Ticket ещё отсутствуют в проверенном
ref; личный путь и модульный монолит сохраняются. DEV-A — AI, DEV-B — продукт
и интеграция. Ближайший отдельный срез — A-01, не реализация всей платформы.

## Проверенное состояние

**25–26.09.2026, срез D3 (MERGED, DEPLOYED `bc0ffbe`, живые шаги 1–5 — [чекпоинт D3](docs/MAX_LIVE_SMOKE.md#d3-checkpoint--2526-сентября-2026-объявление-опрос-заявка-в-чате-мой-дом-сводка)):** жилищный навигатор
(«Мой дом», профиль УК «по данным УК», «Выполненные работы», запись на приём) и
домовое сообщество (объявления, рассылки и опросы УК и платформы с
предпросмотром, расписанием и статистикой; статус заявки в чате и «Меня тоже
касается»; настройки бота и тихие часы чата; «Мои обращения»; сопровождение
обращения и ежедневная сводка) — [BOT-VOICE-HUMAN-2026-09-27](docs/decisions.md#bot-voice-human-2026-09-27),
[COMMUNITY-D3-2026-09-27](docs/decisions.md#community-d3-2026-09-27), [D3-LIVE-2026-09-26](docs/decisions.md#d3-live-2026-09-26); проверки,
выкладка и живые шаги — [docs/status/dev-b.md](docs/status/dev-b.md).

**24.09.2026, срез D2 (IMPLEMENTED IN BRANCH → см. статус):** страница продукта и
единый вход, самостоятельное подключение УК со страницей статуса, квота чатов
(CHAT-QUOTA-2026-09-26), сброс пароля/MFA и открытая регистрация сотрудников,
дашборды платформы и УК, второй регион RU-MOW данными. Состояние, проверки,
выкладка и живые шаги — [docs/status/dev-b.md](docs/status/dev-b.md),
масштабирование — [docs/SCALING.md](docs/SCALING.md).

**24.09.2026, срез D1 (MERGED, DEPLOYED, частично LIVE VERIFIED):** житель —
участник домового чата (RESIDENT-BY-CHAT-2026-09-25), открытый доступ к дому
(OPEN-HOUSE-ACCESS-2026-09-25), личный бот B-04, вход в mini app без тупиков;
подписка MAX — восемь типов. Актуальное состояние, проверки и живые шаги —
[docs/status/dev-b.md](docs/status/dev-b.md) (единый статус проекта) и
[чекпоинт D1](docs/MAX_LIVE_SMOKE.md). Текст ниже — исторический снимок 17.09.

Состояние повторно сверено 2026-09-17 по коду, OpenAPI, существующим тестам
и refs после fetch: `main`, `origin/main`, `dev/b-experience` и
`origin/dev/b-experience` = `3d4a095` (интеграционный merge `e3ab6b7`).
Документационный patch ARCH-PLATFORM-v1 не меняет producer и не является
новым runtime/live прогоном. Совпадение refs относится к началу этого patch;
его собственный commit не объявляется MERGED TO MAIN.

- **IMPLEMENTED:** FND-01 даёт исполняемый backend/runtime, PostgreSQL-модель и
  миграцию, C0 API, test-session/demo seed, durable jobs/worker, режимы MAX
  transport `off`/`recording`, OpenAPI и сгенерированные TypeScript-типы.
- **MERGED TO MAIN:** FND-01, B-00 и реализация B-02 на фактическом C0 API входят
  в `main`; B-02 остаётся **PARTIAL**, пока producer/consumer не сведены с
  целевым B-00 contract.
- **LIVE VERIFIED:** нет. Локальные unit/contract/frontend/PostgreSQL/Docker
  проверки не являются подтверждением работы в реальном MAX или публичном
  production-окружении.
- **NOT LIVE VERIFIED:** реальные MAX web/iOS/Android-клиенты, live initData и
  webhook, MAX-controlled appearance, публичный TLS deploy и внешние providers.
- Интегратор по умолчанию — **DEV-B**. Он обновляет этот файл после значимого
  принятого merge/этапа по проверенному `main`.

## Сверка интегратора 18.09.2026

Q&A docs-only сверка: `HEAD`/`origin/dev/b-experience` перед правкой —
`4628d11` (A-07), `origin/main` — `3d4a095`. Нового runtime/live evidence нет;
прежние статусы ниже сохранены. [Уточнения Q&A](docs/decisions.md#qa-alignment-2026-09-18)
обновляют требования API/сдачи/A-16; A-16 не начата. Групповой A-07 — явная
`/report`, обычная переписка не анализируется автоматически. Live MAX остаётся
NOT VERIFIED / PENDING TOKEN. Следующее проектное действие — отдельное
согласование A-16; B-01 live требует доступов.

`origin/main` по fetch остаётся `3d4a095`; merge A-01/A-15 не выполнен.
Таблица main ниже намеренно не повышена до состояния ветки. A-01 и A-15
**IMPLEMENTED IN BRANCH `dev/b-experience`**, проверки и текущие ограничения —
[DEV-B handoff](docs/status/dev-b.md); новая DB/access реализация описана в
[ARCHITECTURE](docs/ARCHITECTURE.md) и [CONTRACTS](docs/CONTRACTS.md).
Следующая интеграционная операция — review/CI и PR, не автоматический merge.
Live MAX и deployment по-прежнему NOT VERIFIED.

A-07 добавлена в той же ветке поверх A-15 (`ffd9b84`): MAXChat,
ConnectionRequest, ChatBinding, проверка provider/approval и версия queued context.
Это IMPLEMENTED IN BRANCH, не состояние main. CB и regression evidence —
[DEV-B handoff](docs/status/dev-b.md). Live MAX: NOT VERIFIED / PENDING TOKEN;
[checklist](docs/MAX_LIVE_SMOKE.md). Ticket/full admin UI/AI не начаты.

## Возможности в проверенном main

Delivery integrator note, 18.09.2026: actual START `dev/b-experience=95a6c24`;
`origin/main=3d4a095` remains the accepted main reference. A-05/B-03 and personal
parts of B-06/B-07/B-08 now connect existing A-16 outbox to verified-recipient MAX
delivery, callbacks, Mini App launch and reconciliation. This is IMPLEMENTED IN
BRANCH / DETERMINISTIC TESTED, not a new main capability or live verification.
A-09 reminders, full group/sharing/QR scope and A-10 are unchanged. Current evidence,
commands and pending live boundary: [DEV-B handoff](docs/status/dev-b.md).

Сверка интегратора B-14, 18.09.2026: START/END fetch подтверждают прежний
`origin/main=3d4a095`; принятых новых merge нет, таблица main ниже не повышена.
На `dev/b-experience` A-16 (`194d91a`) дополнена B-14: один Vite-проект с
employee `/admin/` и прежней resident Mini App, оба используют A-16 API.
Это **IMPLEMENTED IN BRANCH**, не MERGED TO MAIN и не LIVE VERIFIED.
Текущий результат/команды/ограничения находятся в [DEV-B handoff](docs/status/dev-b.md)
и [UI-TK evidence](scenarios/acceptance.md#b-14--ui-tk-evidence), которые заменяют
исторические branch-only «A-16/B-14 не начаты» выше. Нового workflow/миграции
нет; staff read DTO получил имена и summary текущих наблюдений, resident
allowlist неизменна. Полноценный web-auth/MFA остаётся A-10/B-09; существующая
сессия используется без выдачи новой identity. Следующая интеграционная операция —
review DEV-A и актуальный CI/PR; автоматического merge в main нет.

| Возможность / flag | Состояние | Фактический статус |
|---|---|---|
| Backend/runtime foundation | IMPLEMENTED · MERGED TO MAIN | FastAPI, services/core, PostgreSQL, Alembic, worker/jobs, Docker и CI quality gate находятся в `main` |
| C0 API и контракты | IMPLEMENTED · MERGED TO MAIN | House-scoped auth, reports/incidents, capabilities, OpenAPI и TS schema работают; B-00 convergence ещё не завершена |
| B-02 mini app | PARTIAL · MERGED TO MAIN | Board/detail/report flow подключён к реальному C0 API; planned actions/read-model/error semantics ещё требуют A-01 convergence |
| MAX transport | IMPLEMENTED LOCALLY · NOT LIVE VERIFIED | Подпись initData и режимы `off`/`recording` реализованы; live webhook/client compatibility не подтверждены |
| Demo/test data | IMPLEMENTED · MERGED TO MAIN | Явные local/test session и demo seed присутствуют; это не реальные пользовательские данные |
| LLM/NLP/ML | NOT IMPLEMENTED | Детерминированный `rules` fallback сохраняет рабочий manual path; AI providers и модели не подключены |
| Media, group mode, reminders | NOT IMPLEMENTED | Не реализованы и не проверены |
| Public deploy / Live MAX validation | NOT LIVE VERIFIED | Реальный MAX и публичный TLS-стенд не проверялись |

## Согласованные границы

- Один backend-пакет и один runtime image; `api` включает HTTP/webhook, отдельный durable `worker` работает без Redis на старте.
- Зависимости: API/bot/worker → services → core; бизнес-правила не дублируются во frontend или bot handlers.
- DEV-A владеет AI/NLP/ML: подготовкой текста для моделей, извлечением и классификацией, providers/prompts, structured output, semantic ranking, AI-specific resilience, datasets/evaluation и выделенным backend-кодом этих модулей.
- DEV-B владеет продуктовым контуром: mini app/MAX/bot, public API/contracts, core/services, incidents/appeals, DB/migrations, auth, rules/regions, общей jobs/outbox инфраструктурой, admin/analytics, deploy/CI/release и end-to-end интеграцией.
- DEV-B передаёт AI только разрешённый scope; DEV-A возвращает типизированный аналитический результат; DEV-B валидирует его, применяет бизнес-правила и выполняет транзакцию. Manual/deterministic путь остаётся рабочим без LLM.
- Каноническая матрица путей, shared writers и Owner задач находится в `ROADMAP.md`.

## Ближайший интеграционный риск

B-02 остаётся PARTIAL: C0 producer расходится с B-00 target по structured `allowed_actions`, provenance/freshness, capabilities, count semantics, read-model полям и errors. Следующий backend-срез **DEV-B** — существующая A-01, минимальная C0/B-00 convergence с producer+consumer+generated types+tests
и явным решением минимального tenant/house/access context. Реализация tenant
и изоляции — отдельная A-15, затем повторный binding B-02. Это не требует публиковать неподдержанные действия. DEV-A review обязателен; отсутствие convergence не переносит общий backend обратно DEV-A.

## Ссылки

- [DEV-A handoff](docs/status/dev-a.md) · [DEV-B handoff](docs/status/dev-b.md)
- [Roadmap](ROADMAP.md) · [Architecture](docs/ARCHITECTURE.md) · [Contracts](docs/CONTRACTS.md)

## Employee authentication branch checkpoint — 19.09.2026

A-10 employee identity slice is implemented in `dev/b-experience`, separately from
A-15 authority. B-14 now has password/MFA cookie entry and session restoration.
A-10/B-09 onboarding, company applications, limits and staff UI remain open.
No main merge is implied; `origin/main=3d4a095` remains the accepted baseline.
Release `f861e97` is DEPLOYED with deterministic auth/regressions verified; live
employee password change, human-owned MFA, scoped queue and same-session reload
are LIVE VERIFIED. Reset/revoke/recovery remain deterministic-only. Evidence is maintained in
[DEV-B status](docs/status/dev-b.md); historical live MAX evidence is preserved.
# Administrative onboarding checkpoint — 19.09.2026

The A-10/B-09 company/staff/house onboarding slice is implemented on
`dev/b-experience`: additive `e107a3cff433`, existing A-10 MFA, separate administrative
surfaces and A-07 connection UI. A-10/B-09 remain PARTIAL for limits/settings and
the remaining roadmap scope. This is not a merge into main (`3d4a095` at START).
Current deterministic, deployment and live evidence, including explicit limits,
are in [DEV-B status](docs/status/dev-b.md); older statements below describe their
recorded refs and are not current branch/live readiness claims.
