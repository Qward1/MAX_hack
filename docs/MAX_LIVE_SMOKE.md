# MAX live smoke — MINI APP AUTHENTICATION/CONTEXT LIVE VERIFIED (MAX WEB)

## Mini App identity continuation — 19 September 2026

This checkpoint supersedes the older Mini App binding blocker below.
**LIVE VERIFIED:** organizers bound `t480_hakaton_max_bot`; the operator opened
the resident frontend inside MAX Web and saw the no-houses state.

Existing deployed code (START `53ee8b5`) already loads official MAX Bridge and
posts raw initData to server-side HMAC/age validation; no auth bypass or new auth
algorithm is needed. Official [validation](https://dev.max.ru/docs/webapps/validation)
and [Bridge](https://dev.max.ru/docs/webapps/bridge) were rechecked on 19 September.
`initDataUnsafe` is unused. Signed chat/start_param are never membership authority.

Production evidence from that real opening:

- `2026-09-19T17:28:29.767350676Z`: `POST /api/v1/auth/max` → 200.
- `2026-09-19T17:28:29.875809246Z`: `GET /api/v1/me` → 200.
- Canonical User `d6d46c79-5001-433f-be7e-867659d6e972`, MAX user `294889720`,
  display name Владислав; verified_at `2026-09-19T17:28:29.761679+00:00`.
- This identity matches destination `294889720` in the previous genuine
  bot_started operational receipt. User has no demo_alias or platform_role.
- One production session, zero Houses and zero ResidentMemberships at inspection.
  MembershipService for that user returned `houses: []`.

Thus real initData receipt, signature PASS, auth_date PASS and canonical identity
are **LIVE VERIFIED** through the mandatory validation route and its committed
side effects; raw credentials were not retained or replayed. Empty houses were
correct domain access, not a failed MAX authentication. `/me` embeds houses;
there is no separate `/me/houses` route.

Added operator-only `domsignal.tools.live_fixture` for the user's explicitly
authorized singleton test scope: validated existing User only; no staff role,
test session, demo identity or client authority. It uses ManagementService and
normal ResidentMembership/AccessPolicy, with an operator audit and revoke/delete
commands. See [runbook](../deploy/README.md#7-explicit-isolated-live-resident-scope).

### Isolated fixture — DEPLOYED / CLIENT REOPEN PENDING

Code commit `d4b67769f94ed3a41c26e0934fa9ba8951f46522` is pushed to
`dev/b-experience` and deployed. VPS has no noninteractive GitHub credential, so
the verified commit bundle was transferred over existing SSH and fast-forwarded;
no credential copied or main merge performed. Production runtime image:
`sha256:a6a63aed17813fb1780655a966ded5c35dd698754658d81dd81bd00e858b5338`.
`BUILD_COMMIT` matches the code commit, environment file remains mode 600.

At `2026-09-19T17:43:43.629875+00:00`, the operator CLI created exactly:

| Object | Persisted ID |
|---|---|
| House, labelled «ДомСигнал — LIVE TEST» | `6edbf50b-4bb4-4a74-a6fd-40351010802e` |
| Separate ManagementCompany | `9f0306fa-9660-40ab-8527-f1e361d48d61` |
| Active HouseManagement, ticket intake enabled | `3119b924-0a47-49a6-975d-2c0c5546894d` |
| Explicit ResidentMembership for the real user above | `636ba083-db30-4ec4-b41a-50b821ddba54` |

Audit receipt `operator:live-smoke-house:v1` records operator
`codex-user-authorized` and reason `task-01a0bab9-explicit-single-live-test-house`.
This operator record is not a MAX event. No employee grant or platform role exists.
After creation DB counts: users/sessions/houses/companies/managements/resident
memberships each 1; organization memberships, ChatBindings, Reports and Tickets 0.

**Production operator service check:** MembershipService returns that single house
with resident role. OperationContext pins its tenant and management, with only
`report.create`, `incident.read`, `work.read`, `work.observe`. Board read succeeds
with zero incidents; an unknown house is masked as 404. There is no foreign tenant
in this fresh production DB; two-tenant negative cases are deterministic evidence.
These direct read-only service checks are **not** a MAX-client board/reload claim.

API and DB healthy, worker and Caddy running; public HTTPS `/ready` 200, anonymous
`/api/v1/me` 401, disabled test-session probe 503; no session created by that probe.
ALLOW_TEST_SESSION=false and DEMO_SEED=false, no fresh error/traceback/500 lines.
The sole real session was source=max and expired at 17:43:29 UTC. Requested one
fresh real MAX reopening; no raw initData or bearer replay was performed.

**DETERMINISTIC VERIFIED:** 68 targeted tests (2 fixture, 16 tenant access,
38 A-07, 11 initData, 1 production bootstrap); backend 100 unit/contract tests,
ruff and mypy (78 source files); OpenAPI export/TS drift and region validation;
frontend production build; full local and VPS Docker production builds;
Gitleaks v8.24.3 staged-patch scan (no leaks), `git diff --check`.

**LIVE VERIFIED in MAX Web:** actual House Board/context and reload, as detailed below.
Group capability, bot_added, authorized ConnectionRequest/ChatBinding, real report,
Ticket/WorkAttempt, personal product notification, open_app/start_param,
callback/ResultObservation, close/reopen and source-message edit remain pending.
Public `group_mode=false` is an application feature flag, not proof that organizers
disabled the bot's group capability. Do not infer or activate a binding from it.

### Real reopening and reload — Mini App authentication/context LIVE VERIFIED

Operator replied «Готово». MAX Web freshly loaded the root and bundle at 17:44:47
UTC, then auth/max 200 at 17:44:49.625196282Z, me 200 at 17:44:49.737007452Z
and the exact authorized house board GET 200 at 17:44:49.847838368Z.
The same canonical User has verified_at 17:44:49.618527+00:00 and a second
source=max session expiring at 17:59:49.618573+00:00. The normal me read model
still contains only the test house and resident role. No extra identity/role.

Separate reload was performed through the MAX menu. Root GET 200 at 17:47:33 UTC,
cached assets 304, auth/max 200 at 17:47:34.096788723Z, me 200 at
17:47:34.318183235Z and exact test-house board GET 200 at 17:47:34.419205607Z.
The operator confirmed the «ДомСигнал — LIVE TEST» board remained visible.
UI confirmation is human evidence correlated with actual server requests, not a
browser fixture: tool inventory exposes only empty Codex IAB, not that MAX tab.
This verifies MAX Web; native iOS/Android and notification launch are not asserted.

Read-only provider me still identifies the correct bot but exposes no group
allow/deny switch. GET/chats returned an empty array, which is **not usable group
capability or membership evidence**: current official
[GET/chats](https://dev.max.ru/docs-api/methods/GET/chats) is unsupported since
June 2026. Use real bot_added and per-chat membership/admin methods. The group-add
switch belongs to the organizer's partner portal
([official settings](https://dev.max.ru/help/chatbots)); default is off, but this
bot's current setting is UNKNOWN. Requested actual addition/admin assignment in an
existing test group to resolve this client-only gate. No binding activated.

## Production bootstrap — 19 September 2026 (Europe/Moscow)

**DEPLOYED:** API, worker, PostgreSQL and Caddy are running on `domsignal-prod`
(`176.108.244.168`), checkout `/opt/domsignal`, branch `dev/b-experience`.
Initial deployed application SHA: `7d941b94fde0bd9b06fb8b08d969a2417e8b7c1b`.
The resumed bootstrap started at `b986aeda249316d75ad2a2c9620a803033e96a69`.
This checkpoint adds a production Caddy DNS alias and updates deployment evidence;
its full deployed checkout SHA is recorded in `deploy/.env.production` as
`BUILD_COMMIT` and can be checked with `git rev-parse HEAD` on the VPS.
Built backend image: `sha256:3623dec69b96727577aedd33299e5143e66d918a3a64b389b52fca0e4d98c141`.
No merge to main, writes to DEV-A, local database copies or synthetic business data.

- VPS: Ubuntu 24.04.4 LTS, x86_64, 4 vCPU, 7.8 GiB RAM, 55 GiB root disk
  (49 GiB available before image pulls), no swap; Europe/Moscow; NTP synchronized.
- Existing project SSH key works with BatchMode and strict host verification.
- Installed Docker Engine 29.8.1 and Compose plugin 5.5.1; git/curl/CA/openssl present.
- Fixed missing host DNS resolvers using a persistent systemd-resolved drop-in;
  fixed the unresolvable Ubuntu apt mirror by using the official Ubuntu archive.
- DNS A lookup: `domsignal.176-108-244-168.sslip.io` -> `176.108.244.168`.
- UFW enabled: TCP 22/80/443 only. PostgreSQL has no host port; API binds loopback.
- Fresh production secrets generated on the VPS; environment file mode 600 and
  gitignored. Nested `.env` files are now excluded from the Docker build context.
- Production Compose `config --quiet` and in-memory assertions passed without
  printing credentials. APP_ENV=production, test auth/demo seed disabled,
  MAX_TRANSPORT=webhook, strong session/webhook secrets; real HTTP messaging provider.
- All migrations completed through `2aea407269aa`; seed exited 0 with disabled notice.
  API and DB healthy; Caddy and worker running; worker process/DB reachability pass,
  no automatic restart loops. Worker has no Docker healthcheck in the existing configuration.
- Users/jobs/tickets/work attempts/deliveries remain empty; no test DB copied.
  One genuine `bot_started` receipt and its operational smoke result are persisted.

**DETERMINISTIC VERIFIED:** 17 targeted production bootstrap, subscription and MAX
provider tests pass. Quiet Compose validation and fail-closed configuration pass.
Controlled authenticated replay of the actual event identity returns duplicate=true,
job_id=null, with the inbox count still one and job count unchanged. This is an
operator replay, not evidence of a second delivery initiated by MAX.

**LIVE VERIFIED:** production container GET `/me` returned
`user_id=402577719`, `username=t480_hakaton_max_bot`, `is_bot=true`, with TLS
verification enabled. Public TLS, guarded subscription, real inbound `bot_started`
and real outbound provider acceptance are verified as detailed below. This does
not verify product Ticket delivery, callbacks, groups, Mini App binding or message reading.

### Public HTTPS and subscription — PASS

The operator attached the web security group while retaining SSH access. Public
HTTP now returns 308 and HTTPS `/ready` returns 200 with `{"status":"ready"}`.
Checks from outside the VPS confirmed webhook `{}` without secret -> 401 and
with the production secret -> 422. Public capabilities report test_auth=false.

Caddy obtained a trusted Let's Encrypt YE1 certificate, SAN
`domsignal.176-108-244-168.sslip.io`, valid until 2026-12-17 20:34:07 UTC.
External TLS 1.3 and OpenSSL chain/hostname verification passed; the server sends
four certificates. No self-signed certificate or disabled verification was used.

The cloud public-IP loopback still times out from the VPS itself. The production
overlay therefore gives Caddy the PUBLIC_DOMAIN alias on the Docker network;
container preflight reaches the same HTTPS virtual host with normal certificate
verification. External checks remain separate and are required before registration.

Safe utility `list` first confirmed `[]`. After all checks passed, `register`
returned registered; another `list` confirmed exactly one subscription:
`https://domsignal.176-108-244-168.sslip.io/max/webhook` with exactly
`bot_started`, `bot_stopped`, `bot_added`, `bot_removed`, `message_created`,
`message_callback`. Names were rechecked against official
[Update](https://dev.max.ru/docs-api/objects/Update) and
[POST subscriptions](https://dev.max.ru/docs-api/methods/POST/subscriptions).

### Real event, message and restart — PASS

After the operator pressed Start, the production webhook returned 200 and persisted
typed `bot_started` at 2026-09-18 21:39:42.616290 UTC (19 September MSK).
Event ID: `max:9c4f4ba8af7819c343aeb9543b2c9a2387e5e6bdde33bcf81e8b13426fcde119`.
Authentication is mandatory before parsing; previous operator probes contained only
invalid `{}`. This successful event followed the actual MAX interaction.

The inbox intentionally stores only chat_id, not raw webhook JSON or correlation
secrets. GET `/chats/{chatId}` returned the active dialog and its real non-bot user.
Its last_event_time and verified user/chat identifiers reconstructed the exact
same parser event hash before the controlled duplicate POST was attempted.
Duplicate=true and unchanged receipt/job counts verified deduplication.

Production `HttpMaxMessagingProvider.send_personal_message` sent exactly:
«ДомСигнал подключён. Проверка MAX-бота выполнена.»
MAX POST `/messages` was accepted with provider ID
`mid.00000000066d71cf01a0b678f3ea6fad`. GET of that message confirmed the same
ID, text and intended recipient. Reading/push display is not asserted.

The operation was claimed before send and its actual acceptance/message ID saved
in the real receipt's `payload.bootstrap_smoke`. This is operational smoke
evidence, not a Ticket NotificationDelivery or a confirmed app User identity.
No Ticket, WorkAttempt, app user, membership or synthetic delivery was created.
The send claim prevents an accidental automatic resend of this operator smoke.

API and worker were restarted via production Compose. HTTPS preflight and the
single expected subscription still passed; the event and accepted message ID
survived. API/DB are healthy, worker process and DB connectivity passed, and recent
API/worker/Caddy logs contained no error/traceback/500 lines or credentials.

### Remaining gates

- Callback: PENDING PRODUCT LIVE SCENARIO; existing handler needs a genuine
  Ticket/WorkAttempt and accepted delivery. Do not manufacture a production Ticket.
- Group capability: UNVERIFIED; `/me` exposes no group capability flag. No group
  addition attempted and GET `/chats` returned an empty list. If disabled,
  PENDING ORGANIZER ACTION; A-07 live remains pending. No user action requested now.
- **PENDING ORGANIZER ACTION:** Mini App binding. Resident entry is `/`, so the
  exact URL to hand to organizers is `https://domsignal.176-108-244-168.sslip.io/`.
  HTTPS 200 and the resident bundle were checked. Binding, real initData,
  open_app/start_param and Web/iOS/Android client behavior remain NOT LIVE VERIFIED.

The previous SSH and public-ingress blockers are resolved. No further operator
action is needed for this bootstrap. Future checks must not recreate SSH keys,
regenerate production secrets, resend the accepted smoke, or delete unknown subscriptions.

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

Additional product Ticket delivery checklist — all PENDING (separate from the
plain-text bootstrap send verified above):

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
не добавленная в A-07 функция; весь перечень ниже **NOT RUN / PENDING PRODUCT LIVE SCENARIO**.

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
и списка subscriptions недостаточно для проверки продуктовой цепочки: её уровень C
остаётся NOT RUN / PENDING PRODUCT LIVE SCENARIO. Сохранять ref, конфигурацию без секретов, роли, тестовые
данные, клиент/версию, время, ожидаемый и фактический результат каждого шага.
Локальный запуск не перепривязывает общий webhook; reset разрешён только для
явно выбранного собственного тестового окружения. Current bootstrap evidence above supersedes historical prerequisite status; product live scenarios remain unverified.
