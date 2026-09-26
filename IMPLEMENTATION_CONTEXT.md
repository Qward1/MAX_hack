# ДомСигнал — implementation context

Состояние на 27.09.2026 (срез D5). Интегратор — DEV-B; обновляется после
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

Production на начало D5: `/version` = `39e3dcc` (UX-1 + D4). Выкладка D5 —
раздел D5 в [dev-b.md](docs/status/dev-b.md).

| Срез | Что | Статус | Чекпоинт / решения |
|---|---|---|---|
| FND-01, A-01, A-15, A-07, A-16, A-05/B-03, B-14 | backend, доступ УК → дом → объект, подключение чатов, заявки Ticket, личная доставка MAX, кабинет | MERGED · DEPLOYED · LIVE VERIFIED частично (P7a) | [ARCHITECTURE](docs/ARCHITECTURE.md), [CONTRACTS](docs/CONTRACTS.md) |
| A-10/B-09 | вход сотрудников (пароль + MFA), подключение УК и домов | MERGED · DEPLOYED · LIVE VERIFIED (вход, MFA, очередь) | dev-b.md «A-10» |
| P1–P6c (AI) | ядро окна, провайдер polza, роутер, явный путь, пассивное чтение, Signal Inbox, оценка качества | MERGED · DEPLOYED · LIVE VERIFIED (P7a, P6b, P6c) | [dev-a.md](docs/status/dev-a.md), [PASSIVE-CHAT](docs/decisions.md#passive-chat-2026-09-20) |
| D1 | житель по участию в чате, открытый доступ, личный бот | MERGED · DEPLOYED · LIVE VERIFIED (чекпоинт D1) | [RESIDENT-BY-CHAT](docs/decisions.md#resident-by-chat-2026-09-25) |
| D2 | сайт и вход, заявка УК с квотой чатов, дашборды, RU-MOW | MERGED · DEPLOYED · LIVE VERIFIED (чекпоинт D2) | [CHAT-QUOTA](docs/decisions.md#chat-quota-2026-09-26) |
| D3 | навигатор «Мой дом», объявления, рассылки, опросы, статус заявки в чате, сводка | MERGED · DEPLOYED · LIVE VERIFIED (чекпоинт D3, шаги 1–5) | [COMMUNITY-D3](docs/decisions.md#community-d3-2026-09-27) |
| UX-1 | единая визуальная система | MERGED · DEPLOYED (`39e3dcc`) | [UX_REVIEW](docs/UX_REVIEW.md) |
| D4 | регион и пояс дома, RU-PSK/RU-PRI данными, `/privacy`, совет дома, эксплуатация | MERGED · DEPLOYED (`39e3dcc`); живые шаги 1–5 — тест-кейсы владельца | [HOUSE-REGION](docs/decisions.md#house-region-2026-09-27) |
| D5 | параллельный разбор, пул БД, очистка очереди, здоровье очереди, дома пачкой, `region_pack new`, готовность справочника, реальные агрегаты и разметка, нагрузочные прогоны А–Д | IMPLEMENTED; MERGED и DEPLOYED — см. dev-b.md D5 | [QUEUE-SCALE](docs/decisions.md#queue-scale-2026-09-27), [BULK-HOUSES](docs/decisions.md#bulk-houses-2026-09-27), [SCALING](docs/SCALING.md) |

**Не проверено в настоящем MAX людьми:** живые шаги D4 (посторонний житель,
«Политика данных», совет дома, рассылка в личку и отписка, дом RU-MOW);
нажатия в рассылке, опросе, правке постов и сводке после D3 — транспорт
проверен в D5 (§7), нажатия — тест-кейсы владельца.

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
