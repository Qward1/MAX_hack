# MAX live smoke — BOOTSTRAP PREPARED / NOT LIVE VERIFIED

Implementation and deterministic tests do not establish end-to-end live connectivity.
Read-only token checks are complete, but no public webhook delivery or real MAX
event has been observed yet. `LIVE VERIFIED` therefore remains false.
Use an approved isolated bot, existing test groups and authorized test users.
Do not change the team's shared webhook or start polling with its token.

## Bootstrap status — 18 September 2026

- [x] The issued token was accepted by `GET /me`; username is
  `t480_hakaton_max_bot`.
- [x] `GET /subscriptions` returned an empty list; no subscription was changed.
- [x] The runtime trust store includes the Russian Trusted Root CA required by the
  current `platform-api2.max.ru` chain; TLS verification remains enabled.
- [x] Production config and deterministic webhook checks prove missing secret →
  401 and valid secret with `{}` → 422 before business persistence.
- [ ] A publicly reachable HTTPS hostname and VPS are not available in this
  environment, so external `/ready`, webhook auth and MAX delivery are pending.
- [ ] `POST /subscriptions` has deliberately not been called. Register only after
  the public HTTPS preflight in [the production runbook](../deploy/README.md).

## Configuration and prerequisites

Use the existing API + worker + private PostgreSQL + HTTPS reverse proxy.
`MAX_TRANSPORT=off` remains the local default. Only explicit `webhook` enables
inbound MAX and the production HTTP providers. Subscription registration is an
explicit guarded operator action; application startup never mutates it.

Set the issued `MAX_BOT_TOKEN` and `MAX_WEBHOOK_SECRET` through deployment secrets;
never place them in git, shell history, traces or evidence. Default API origin is
`https://platform-api2.max.ru`, timeout 5 seconds, connection TTL 900 seconds.
TLS certificate verification stays enabled. If MAX requires an additional CA,
install the approved CA in the runtime trust store; do not disable TLS validation.
Bot admin and `read_all_messages` are mandatory. Extra required permissions can
be configured; removing `read_all_messages` is rejected by Settings.

The fixture identities and seeded demo houses are not real permissions. Provision
verified ManagementCompany/HouseManagement and employee/resident access through
the approved existing process. Log in with server-validated MAX initData. There
is no production test-session bypass and no new full admin UI in A-07.

## End-to-end checklist

- [x] Issued token accepted; read real bot identity with documented `GET /me`.
- [ ] Group adding enabled in bot settings.
- [ ] Dedicated HTTPS `/max/webhook` available on port 443; API and worker share DB.
- [ ] Dedicated subscription uses `X-Max-Bot-Api-Secret`; missing/wrong secret gives
  401 with no persisted event. Register/change only the approved isolated subscription.
- [ ] Users manually prepare an existing test group (DomSignal creates no groups).
- [ ] Company admin/responsible starts `POST /api/v1/houses/{house_id}/chat-connections`.
  Retain the one-time correlation token privately. Use documented bot deep link
  `https://max.ru/<real_bot_username>?start=<correlation_token>`; validate the actual
  username and payload delivery on this bot/client.
- [ ] Connector follows the link; real `bot_started` binds its MAX identity, then
  adds the bot to that existing group. One open request per connector is allowed.
- [ ] Real `bot_added` is captured with actor, chat ID, timestamp and group type.
- [ ] Real chat ID persists once in MAXChat; no title/address inference takes place.
- [ ] `GET /chats/{chatId}/members/me` confirms bot membership/admin.
- [ ] Actual permissions include `read_all_messages` and configured requirements.
- [ ] `GET /chats/{chatId}/members/admins` confirms the connector's current admin role.
- [ ] Authorized company employee explicitly calls `/chat-connections/{id}/approve`
  with `{"confirm": true}`. External connector requires that company's approval.
- [ ] Binding is ACTIVE with version 1; request is completed, real IDs match.
- [ ] Existing authorized resident sends `/report water <test description>`; real
  group event creates a scoped manual Report/Incident. Ordinary conversation and
  unknown/unauthorized users do not create incidents. No NLP is introduced here.
- [ ] A second existing test chat binds to a different house/company; same command
  resolves its own management, and API reads remain isolated across companies.
- [ ] If approved and safe, remove the bot: binding suspends with BOT_REMOVED;
  queued old messages have no effect. Restore only through a new connection/version.
- [ ] Separately check live Mini App chat/initData on Web/iOS/Android. This version
  does not use chat/start_param as a grant or automatically create memberships.

Also exercise permission loss via the worker-callable `max.binding.health` job
(`chat_binding_id`). No periodic scheduler was added. Before every group report,
health is checked; timeout/unknown rights suspend the binding, requiring a new
connection. Pending connection verification retries via existing jobs (up to five
attempts, existing backoff); explicit approval performs a fresh verification too.

Capture commit SHA, environment/client versions, times and sanitized results for
each item. Mark LIVE VERIFIED only for the exact paths actually exercised. Do not
record tokens, message content from unrelated chats or participant lists.

## Documented provider contract (rechecked 18 September 2026)

- [Chat metadata / API origin](https://dev.max.ru/docs-api/methods/GET/chats/-chatId-)
- [Bot membership and permissions](https://dev.max.ru/docs-api/methods/GET/chats/-chatId-/members/me)
- [Current administrators](https://dev.max.ru/docs-api/methods/GET/chats/-chatId-/members/admins)
- [Updates](https://dev.max.ru/docs-api/objects/Update) and
  [Message](https://dev.max.ru/docs-api/objects/Message)
- [Webhook secret and delivery](https://dev.max.ru/docs-api/methods/POST/subscriptions)
- [List subscriptions](https://dev.max.ru/docs-api/methods/GET/subscriptions) and
  [delete one exact URL](https://dev.max.ru/docs-api/methods/DELETE/subscriptions)
- [Bot start payload](https://dev.max.ru/docs/chatbots/bots-coding/masterbot)

The production provider uses these three read methods only. No bulk participant
sync, speculative pagination, group creation or settings mutation is implemented.
An unexpected non-null admin pagination marker is explicitly unsupported and fails
closed. HTTP/response-mapping contract tests use MockTransport and synthetic data.

## Методы MAX — документальная сверка 18.09.2026

Прочитаны официальные страницы ниже; это **DOC CHECK**, не вызовы провайдера.
Наличие метода не подтверждает разрешение конкретного бота/получателя.

| Источник | Проверенная семантика → требование к будущим B-03/A-05/B-06/B-07 |
|---|---|
| [POST /messages](https://dev.max.ru/docs-api/methods/POST/messages) | Отправка пользователю/в чат, текст до 4000 символов; до 2 сообщений/с в один диалог/группу/канал. Ответ содержит message, HTTP 200 — созданное сообщение. `notify=false` подавляет push для диалога/группы; это не API подтверждения push/прочтения. |
| [PUT /messages](https://dev.max.ru/docs-api/methods/PUT/messages) | Изменяет сообщения бота по message_id, до 2 правок/с на чат. В DM без inline_keyboard — менее 7 суток; с inline_keyboard и в группе/канале — без ограничения давности. HTTP 200 может содержать `success=false` и message ошибки: проверять тело. null/отсутствие attachments не меняет их, пустой массив удаляет. |
| [POST /answers](https://dev.max.ru/docs-api/methods/POST/answers) | Ответ на callback пользователя, возможно обновление сообщения; до 2 ответов/с на чат. Проверять success в теле, HTTP 200 допускает неуспех. Ответ на callback не заменяет авторизацию и сохранение доменного действия. |
| [POST /subscriptions](https://dev.max.ru/docs-api/methods/POST/subscriptions) | HTTPS/443 с доверенным сертификатом, Update и X-Max-Bot-Api-Secret; HTTP 200 от webhook за ≤30 с. Повторы до 10, 60 с ×2,5; после 8 ч без успешного ответа автоматическая отписка. Настройка подписки тоже возвращает success, включая false при HTTP 200. Активная подписка исключает long polling. |
| [Mini App introduction](https://dev.max.ru/docs/webapps/introduction) | `https://max.ru/<botName>?startapp=<payload>`: payload ≤512 символов A–Z/a–z/0–9/_/-. Невалидный payload удаляется: приложение должно безопасно обработать отсутствие контекста. Использовать проверенное имя бота, opaque selector без приватного текста. |
| [MAX Bridge](https://dev.max.ru/docs/webapps/bridge) | shareContent — iOS/Android, не web; shareMaxContent открывается по клику пользователя. Для media sharing нужен mid предварительного сообщения бота. Capability detection и рабочая ссылка/копирование при отсутствии метода; открытие sharing/cancel не доказывают отправку. Медиа остаются A-14/Product/B-13. |

Токен передаётся в Authorization, API origin — platform-api2.max.ru; проверка TLS
включена. Sender учитывает лимиты методов и общий лимит платформы по актуальным
docs перед реализацией, обрабатывает 429/5xx/timeout/невалидное тело. Неизвестный
результат отправки не становится подтверждённым и не даёт слепой бесконечный retry.
Не придумывать API read receipts, push-подтверждения или права получателя.
Метод получения сообщения сам по себе не доказательство, что его прочёл человек.

Текущий официальный объект
[Update](https://dev.max.ru/docs-api/objects/Update) подтверждает нужные типы:
`bot_started`, `bot_stopped`, `bot_added`, `bot_removed`, `message_created`,
`message_callback`. Guarded CLI сначала сверяет `GET /me` и
`GET /subscriptions`, останавливается при любом чужом URL, проверяет публичные
`/ready`/401/422 и только затем вызывает POST. HTTP 200 без `success=true` не
считается успехом. Команды регистрации, повторной проверки, обновления тем же
POST и точечного DELETE приведены в [deploy runbook](../deploy/README.md).

## Ticket → MAX → Mini App — LIVE PENDING

Delivery code is now IMPLEMENTED IN BRANCH (A-05/B-03/personal B-06/B-07/B-08).
Deterministic HTTP+PG+worker/browser evidence is in [DEV-B](status/dev-b.md).
All live items below remain **NOT LIVE VERIFIED / PENDING TOKEN**.

Official documentation rechecked before implementation on 18 September 2026:
[send](https://dev.max.ru/docs-api/methods/POST/messages),
[edit](https://dev.max.ru/docs-api/methods/PUT/messages),
[answer](https://dev.max.ru/docs-api/methods/POST/answers),
[Update](https://dev.max.ru/docs-api/objects/Update),
[keyboard / NewMessageBody](https://dev.max.ru/docs-api/objects/NewMessageBody),
[Mini App links](https://dev.max.ru/docs/webapps/introduction),
[Bridge](https://dev.max.ru/docs/webapps/bridge),
[API changelog](https://dev.max.ru/docs-api/changelog-api).
The client-rendered official schema confirms OpenAppButton `web_app` (bot username
or bot link), optional contact_id and payload; payload is passed to initData.
CallbackUpdate has callback.user/callback_id/payload and nullable original message.
The current CallbackAnswer schema lists `message`, not a standalone notification
field. Therefore answer updates the current card. These shapes are tested locally.
The documented limits remain two send/edit/answer operations per second per
destination; our shared gate conservatively limits their combined rate to two.
No POST idempotency key/guarantee is documented. Send 5xx therefore stays unknown.

Additional live delivery checklist — all PENDING:

- [ ] Configure the approved bot username and attached Mini App; use the existing
  token/Authorization/configuration boundary and current platform-api2.max.ru TLS trust.
- [ ] Genuine validated initData confirms the intended User's MAX ID; legacy/demo
  MAX IDs do not automatically become confirmed production identities.
- [ ] Personal POST /messages to one allowed resident returns and persists a real mid.
- [ ] Inline keyboard has open_app plus the two short verification callbacks.
- [ ] open_app opens the attached Mini App; payload arrives as start_param and
  resolves the exact authorized Incident/current WorkAttempt server-side.
- [ ] Copied launch ref under another identity reveals no target data.
- [ ] Real resolved callback closes via A-16; unresolved reopens the same Ticket.
- [ ] Replay after button removal has no new effect; historical attempt stays historical.
- [ ] PUT /messages updates the original card and removes verification callbacks.
- [ ] POST /answers returns success=true and current feedback; false is recorded as failure.
- [ ] Mini App observation eventually edits the existing message without another POST.
- [ ] Observe push behavior separately; API acceptance alone is not push/read evidence.
- [ ] Two real dialogs progress independently; check conservative per-dialog rate behavior.
- [ ] Exercise allowed rate-limit/retry behavior safely, without stressing the shared bot.
- [ ] Mobile MAX and Web MAX each exercise open_app/start_param/callback/edit.
- [ ] Actual webhook secret rejects an invalid request before parsing/business work.
- [ ] If safely reproducible, API/worker restart retains retries and accepted provider IDs.
- [ ] Check older inline-keyboard message edit on the real client (documented DM
  keyboard messages have no age limit; non-keyboard messages have a seven-day limit).

Зависимости: A-16 — Ticket/WorkAttempt/ResultObservation/events/outbox intents;
B-14 — рабочий и resident UI; A-05/B-03 — доставка/повторы; B-06/B-07 —
карточки/callbacks/ссылки; A-09/B-08 — reminders/история. Owner всех этих задач
и B-01/B-11 live проверки — DEV-B. Это расширение smoke после их реализации,
не добавленная в A-07 функция; весь перечень ниже **NOT RUN / PENDING TOKEN**.

- [ ] На изолированном боте/стенде и разрешённом доме: Report → Incident → Ticket
  → WorkAttempt с конкретным отчётом → outbox intent. Для группы — `/report`.
- [ ] Worker проверяет актуальных получателей, management/binding и доступ,
  отправляет разрешённое сообщение; в группе нет private комментариев/контактов.
  Зафиксировать отдельно: intent создан / ожидает / API принял / ошибка или unknown.
- [ ] Реальный пользователь на Web/iOS/Android открывает соответствующую карточку
  Mini App. Ссылка не выдаёт права и не меняет бизнес-состояние; карточка делает
  свежий API read и показывает актуальную попытку, историю и allowed_actions.
- [ ] Пользователь проверяет результат и явно сохраняет ResultObservation;
  callback повторно проверяет actor/scope/актуальную попытку. История/состояние
  читаются из API, карточка обновляется. Прочтение человеком не выводится из API accepted.
- [ ] Проверить повтор callback, старую попытку, чужой дом, отзыв доступа и смену
  management/binding до отправки/открытия/действия; запрещённых эффектов и утечек нет.
- [ ] Подтверждение одним жителем и позднее возражение другого к последней попытке
  сохраняются раздельно; проверка закрытия/возобновления ждёт решения A-16.
- [ ] Реальные send/edit ответы валидируются; 200 + success=false не успех.
  Контролируемые сбои/таймауты и лимиты безопасно проверяются на уровнях A/B,
  без перегрузки live API. Сбой MAX не теряет Ticket; неизвестность доставки видна.
- [ ] Sharing cancel не считается отправкой; при отсутствии mobile-only функции
  работает fallback. В evidence указать доступные/недоступные клиенты отдельно.

Evidence уровней: **A** — unit/contract, тестовые адаптеры и записанные входы;
**B** — настоящий HTTP, services, PostgreSQL и worker (MAX adapter может быть тестовым);
**C** — реальные MAX провайдер/клиенты, а для принятого AI-среза отдельно live LLM.
A/B не заменяют C; transport=off не реальная интеграция. Наличие рабочего токена
и пустого списка subscriptions не является доставкой события: C остаётся
NOT RUN / PENDING PUBLIC HTTPS. Сохранять ref, конфигурацию без секретов, роли, тестовые
данные, клиент/версию, время, ожидаемый и фактический результат каждого шага.
Локальный запуск не перепривязывает общий webhook; reset разрешён только для
явно выбранного собственного тестового окружения. В этом docs-запуске live не выполнялся.
