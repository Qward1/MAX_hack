# API ДомСигнала

HTTP API обслуживает мини-приложение MAX, кабинеты УК и платформы и вебхук бота.
Полное описание методов и схем — OpenAPI 3.1; этот документ объясняет то, чего
из схемы не видно: вход, роли, жизненный цикл заявки, повторы и ошибки.

| | |
|---|---|
| Адрес | `https://domsignal.176-108-244-168.sslip.io` (методы — `/api/v1/…`) |
| OpenAPI 3.1 | `/openapi.json` работающего сервиса = [`docs/openapi.json`](openapi.json) (сверяется в CI: `scripts/export_openapi.py --check`); интерактивно — `/docs` |
| Проверки для организаторов | [`DATA-API.yaml`](../DATA-API.yaml), прогон — [`scripts/data_api_check.py`](../scripts/data_api_check.py) |
| Тестовые данные | [`docs/api/test_data.json`](api/test_data.json): демо-УК, дом, чужая УК, роли, примеры сообщений |
| Служебные адреса | `/health` (процесс жив), `/ready` (есть база), `/version` (коммит и версии справочника регионов) |

## Вход

| Кто | Как | Что получает |
|---|---|---|
| Житель | Мини-приложение отправляет подписанные данные запуска MAX: `POST /api/v1/auth/max {"init_data": "…"}`. Подпись (HMAC от токена бота) проверяет сервер | `{"access_token", "token_type": "bearer", "expires_at"}` → заголовок `Authorization: Bearer …` |
| Сотрудник УК или платформы | `GET /api/v1/auth/employee/session` → `POST …/login {login_name, password}` → `POST …/mfa/challenge {code}` (TOTP, RFC 6238) | cookie `__Host-domsignal_employee` (Secure, HttpOnly, SameSite=Lax) и `csrf_token` в ответе |
| MAX (вебхук) | `POST /max/webhook` с заголовком `X-Max-Bot-Api-Secret` | без секрета — 401 |
| Самопроверка витрины | `GET /api/v1/showcase/health` с `X-Showcase-Check-Token` | без токена адрес не существует (404) |

Для сотрудника каждый изменяющий запрос несёт `X-CSRF-Token` и `Origin`, равный
адресу сервиса. Сессия — 30 минут простоя и 8 часов всего; выход —
`POST /api/v1/auth/employee/logout`. Защита входа: пароль от 12 символов, один код
TOTP не принимается дважды, больше 30 попыток за 5 минут по логину или новых входов
с одного адреса (production; локально — 10) — 429 `auth_rate_limited` на 5 минут; коды восстановления
одноразовые. Тестовый вход `POST /api/v1/auth/test-session` работает только на
локальном стенде — production его отвергает (503).

## Роли и что им доступно

Права проверяются на сервере в каждом запросе: организация → действующее
управление домом → назначение на дом → действие (`src/domsignal/core/access.py`).
Ссылка, `house_id` в адресе или участие бота в чате доступа не дают.

| Роль | Откуда права | Основные методы |
|---|---|---|
| Житель | участие в домовом чате MAX или выбор дома с открытым доступом | `GET /me`, `GET /houses/{id}/incidents`, `POST /houses/{id}/reports/preview` → `…/submit`, `POST /incidents/{id}/join`, `POST /work-attempts/{id}/observations` («Исправлено» / «Проблема осталась»), черновики обращений `/appeal-drafts`, опросы `/polls/{id}/vote` |
| Член совета дома | отметка администратора УК | `/houses/{id}/council/announcements`, `/houses/{id}/council/polls` |
| Оператор / ответственный | назначение на дом в УК | `GET /tickets?house_id=`, `GET /tickets/{id}`, действия `/tickets/{id}/accept|start|work-attempts|clarify|wait-external|resume|cancel`, `GET /signals`, `/signals/{id}/create-ticket|join|route-external|dismiss` |
| Администратор УК | администратор организации | `/companies/{id}/overview|houses|staff|employee-invitations|broadcasts|reception-slots|dashboard(.csv)`, подключение чатов `/houses/{id}/chat-connections`, `/chat-connections/{id}/approve` |
| Администратор платформы | отдельный аккаунт платформы | `/platform/dashboard|health|companies|company-applications|house-management-requests|region-packs|audit`; **текстов жителей и заявок не видит** |

Чужой объект неотличим от несуществующего — **404**; раздел не своей роли — **403**.

## Жизненный цикл заявки

```text
new ──accept──► accepted ──start──► in_progress ──work-attempts──► verification_pending
 │                                     ▲                                  │
 │                                     └──── житель: «Проблема осталась» ─┤
 │                                                                         │
 └── cancel (с причиной) ─► cancelled          житель: «Исправлено» ──► closed
Боковые: needs_clarification / waiting_external ──resume──► in_progress
```

- Отчёт исполнителя (`work-attempts`) заявку **не закрывает**: закрывает только
  подтверждение жителя; возражение возвращает ту же заявку (тот же `T-N`) в работу.
- Каждое действие несёт `expected_version`: устаревшая версия → 409
  (`ticket_conflict` / `stale_version`), двойной клик ничего не удваивает.
- Разрешённые сейчас действия — в `allowed_actions` карточки заявки; интерфейс
  показывает только их, сервер проверяет переход ещё раз (`core/tickets.py`).
- История заявки — `GET /tickets/{id}/events`, записи не изменяются.

## Повторы и идемпотентность

`POST`-методы жителя и сотрудника принимают `Idempotency-Key` (UUID). Тот же ключ
с тем же телом возвращает сохранённый результат (у действий с заявками и сигналами —
с пометкой `replayed: true`), с другим телом — 409 `idempotency_conflict`. Проверено 28.09.2026: повтор `POST /reports` вернул тот же
инцидент, другой текст с тем же ключом — 409. Повторная доставка события MAX
отбрасывается по идентификатору события (`MaxWebhookService.accept`, таблица
`inbox_receipts`); исходящие сообщения уходят через outbox и при сбое сети не
дублируются.

## Ошибки

Все ошибки — RFC 7807, `Content-Type: application/problem+json`:

```json
{"type": "https://domsignal.local/problems/authentication_required",
 "title": "Authentication required", "status": 401,
 "detail": "A bearer session is required", "code": "authentication_required",
 "retryable": false, "trace_id": "8a52c296-…", "field_errors": null}
```

| HTTP | `code` | Когда |
|---|---|---|
| 401 | `authentication_required`, `invalid_init_data` | нет сессии, подпись MAX неверна |
| 403 | `house_access_denied`, `showcase_protected` | не своя роль или дом; проверочному аккаунту запрещено ломать витрину |
| 404 | `resource_not_found`, `http_404` | объекта нет или он чужой; нет такого метода |
| 409 | `ticket_conflict`, `stale_version`, `idempotency_conflict`, `signal_decided`, `poll_closed`, `draft_filed` … | устаревшая версия, повтор ключа, объект уже в другом состоянии |
| 422 | `validation_error` | поля запроса; подробности в `field_errors[]` |
| 429 | `auth_rate_limited` | слишком много попыток входа |
| 503 | `feature_unavailable` | возможность выключена на этом стенде |

`trace_id` совпадает с `request_id` в журнале сервиса (строка `http_request`) — по
нему находится запрос при разборе.

## Примеры

```bash
H=https://domsignal.176-108-244-168.sslip.io
curl -s $H/ready                                  # {"status":"ready"}
curl -s $H/version                                # {"version":"0.1.0","commit":"…","region_packs":{…}}
curl -s $H/api/v1/capabilities                    # environment, features.max_live=true, bot_url
curl -s -o /dev/null -w "%{http_code}\n" $H/api/v1/tickets?house_id=6edbf50b-4bb4-4a74-a6fd-40351010802e   # 401
curl -s -X POST $H/api/v1/auth/max -H 'Content-Type: application/json' -d '{"init_data":"x"}'           # 401 invalid_init_data
```

Вход сотрудника и чтение очереди с ролью — готовая реализация в
[`scripts/data_api_check.py`](../scripts/data_api_check.py) (`login()`): сессия,
пароль, код TOTP, cookie и CSRF. Раннер выполняет все 24 проверки `DATA-API.yaml`,
12 из них — со входом по TOTP.
