# ДомСигнал — implementation context

Состояние на 29.09.2026 (срез F1 — готовность к сдаче). Интегратор — DEV-B; обновляется после
значимого merge или выкладки. Подробности и проверки каждого среза —
[docs/status/dev-b.md](docs/status/dev-b.md) (единый статус проекта с 24.09),
AI-часть — [docs/status/dev-a.md](docs/status/dev-a.md). Прежние версии этого
файла — в истории git.

## Назначение

Проблема из домового чата доходит до того, кто решает. Рабочий путь: реплики
чата или личное сообщение → сигнал или заявка УК → проверяемый маршрут по
справочнику → черновик обращения, который житель отправляет сам → отметка
жителя и проверка результата. Продукт не утверждает, что сам зарегистрировал
обращение во внешней системе; модель не решает, кто отвечает.

## Статусы

- **IMPLEMENTED** — код и тесты в ветке.
- **MERGED** — в `dev/b-experience` и fast-forward в `main`, `dev/a-core`.
- **DEPLOYED** — выложено на `domsignal-prod` по «Safe redeploy»; `/version`
  показывает SHA.
- **LIVE VERIFIED** — проверено в настоящем MAX людьми по чекпоинту
  [MAX_LIVE_SMOKE](docs/MAX_LIVE_SMOKE.md).

Production: `/version` = `c9fcf0e` (выкладка A среза F1, 28.09 06:00 МСК); выкладка B и журнал
выпусков — [docs/RELEASE.md](docs/RELEASE.md). Проверка для жюри — [README](README.md) и
[docs/JURY_GUIDE.md](docs/JURY_GUIDE.md).

| Срез | Что | Статус | Чекпоинт / решения |
|---|---|---|---|
| FND-01, A-01, A-15, A-07, A-16, A-05/B-03, B-14 | backend, доступ УК → дом → объект, подключение чатов, заявки Ticket, личная доставка MAX, кабинет | MERGED · DEPLOYED · LIVE VERIFIED частично (P7a) | [ARCHITECTURE](docs/ARCHITECTURE.md), [CONTRACTS](docs/CONTRACTS.md) |
| A-10/B-09 | вход сотрудников (пароль + MFA), подключение УК и домов | MERGED · DEPLOYED · LIVE VERIFIED (вход, MFA, очередь) | dev-b.md «A-10» |
| P1–P6c (AI) | ядро окна, провайдер (с M1 — Cloud.ru, до него polza), роутер, явный путь, пассивное чтение, Signal Inbox, оценка качества | MERGED · DEPLOYED · LIVE VERIFIED (P7a, P6b, P6c) | [dev-a.md](docs/status/dev-a.md), [PASSIVE-CHAT](docs/decisions.md#passive-chat-2026-09-20) |
| D1 | житель по участию в чате, открытый доступ, личный бот | MERGED · DEPLOYED · LIVE VERIFIED (чекпоинт D1) | [RESIDENT-BY-CHAT](docs/decisions.md#resident-by-chat-2026-09-25) |
| D2 | сайт и вход, заявка УК с квотой чатов, дашборды, RU-MOW | MERGED · DEPLOYED · LIVE VERIFIED (чекпоинт D2) | [CHAT-QUOTA](docs/decisions.md#chat-quota-2026-09-26) |
| D3 | навигатор «Мой дом», объявления, рассылки, опросы, статус заявки в чате, сводка | MERGED · DEPLOYED · LIVE VERIFIED (чекпоинт D3, шаги 1–5) | [COMMUNITY-D3](docs/decisions.md#community-d3-2026-09-27) |
| UX-1 | единая визуальная система | MERGED · DEPLOYED (`39e3dcc`) | [UX_REVIEW](docs/UX_REVIEW.md) |
| D4 | регион и пояс дома, RU-PSK/RU-PRI данными, `/privacy`, совет дома, эксплуатация | MERGED · DEPLOYED (`39e3dcc`); живые шаги 1–5 — тест-кейсы владельца | [HOUSE-REGION](docs/decisions.md#house-region-2026-09-27) |
| D5 | параллельный разбор, пул БД, очистка очереди, здоровье очереди, дома пачкой, `region_pack new`, готовность справочника, реальные агрегаты и разметка, нагрузочные прогоны А–Д | MERGED · DEPLOYED (`00aafba`, 27.09); транспорт MAX проверен, нажатия — тест-кейсы владельца | [QUEUE-SCALE](docs/decisions.md#queue-scale-2026-09-27), [BULK-HOUSES](docs/decisions.md#bulk-houses-2026-09-27), [SCALING](docs/SCALING.md) |
| UX-2 + RA-01…RA-08 | сервисная ясность интерфейса и замечания повторного аудита, только frontend | MERGED в `main` PR #2 (`99037d6`; `dev/a-core` не сдвигался) · DEPLOYED (`99037d6`, 27.09); публичные страницы проверены в браузере на production, MAX WebView и внутренние экраны — только локальный стенд | [UX.md](docs/UX.md#сервисная-ясность-ux-2--27092026) |
| «Мой дом»: ссылки и выбор дома | строки сервисов и тихие текстовые ссылки вместо синих, `HouseSwitch` вместо нативного select, только frontend | MERGED в `main` PR #3 (`9f0a68f`; `dev/a-core` не сдвигался) · DEPLOYED (`9f0a68f`, 27.09); фронтенд production проверен в браузере с API стенда, MAX WebView — не проверялся | [UX.md](docs/UX.md#сервисная-ясность-ux-2--27092026) |
| M1 | смена модели: открытая неамериканская `Qwen/Qwen3-30B-A3B` в Cloud.ru, резерв DeepSeek-V4-Flash, ₽ по цене профиля, `/privacy` | MERGED (`d38b6e7`, `main` = `dev/b-experience` = `dev/a-core`) · DEPLOYED (27.09); наборы настройки — пороги пройдены, контроль — D6 | [LLM-PROVIDER-2026-09-27](docs/decisions.md#llm-provider-2026-09-27) |
| F1 | D6 (проблема закрывается с заявкой, точность памяток), замечания QA, единый язык интерфейса и `ui-lint`, устойчивость модели к 429, эмулятор MAX, приёмка по матрице, доступ жюри и защита витрины, README | MERGED · DEPLOYED выкладка A (`c9fcf0e`); выкладка B — [RELEASE](docs/RELEASE.md) | [ACCEPTANCE_MATRIX](docs/qa/ACCEPTANCE_MATRIX.md), [CONTROL-M1](docs/decisions.md#control-m1-2026-09-28), [LLM-BUDGET-F1](docs/decisions.md#llm-budget-f1-2026-09-29) |

**Не проверено в настоящем MAX людьми:** живые шаги D4 и D3 из B-10 — список
и шаги в [ACCEPTANCE_MATRIX](docs/qa/ACCEPTANCE_MATRIX.md) (способ `human-MAX`);
их логика проходит автотесты с эмулятором MAX (`tests/acceptance`).

## Границы, которые держит код

- Один образ и модульный монолит: `api` (HTTP + webhook), `worker`
  (операционный пул), `ai-worker` (пул модели), PostgreSQL как БД и очередь;
  Redis и брокера нет. Схема и ручки масштаба — [ARCHITECTURE](docs/ARCHITECTURE.md#схема-на-27092026-срез-d5--шесть-блоков-и-ручки-масштаба).
- Доступ: tenant УК → дом → объект → действие; права в MAX-чате и полномочия
  УК независимы; ссылка и `bot_added` доступа не дают.
- AI ↔ продукт: продукт передаёт разрешённое окно, ядро возвращает
  типизированный результат, продукт валидирует и выполняет транзакцию; без
  модели всё работает на правилах; опасность — правила в транзакции приёма.
- Регион — данные `regions/`, а не код; жителю показываются только
  `verified` записи.
- Реальные выгрузки чатов — только локально, модели не отдаются; в git —
  только числа ([REALDATA-D5](docs/decisions.md#realdata-d5-2026-09-27)).

## Ссылки

[ROADMAP](ROADMAP.md) · [ARCHITECTURE](docs/ARCHITECTURE.md) ·
[CONTRACTS](docs/CONTRACTS.md) · [SCALING](docs/SCALING.md) ·
[OPERATIONS](docs/OPERATIONS.md) · [LICENSES](docs/LICENSES.md) ·
[decisions](docs/decisions.md) · [dev-b](docs/status/dev-b.md) ·
[dev-a](docs/status/dev-a.md) · [MAX_LIVE_SMOKE](docs/MAX_LIVE_SMOKE.md)
