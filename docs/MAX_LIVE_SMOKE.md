# A-07 MAX live smoke — PENDING TOKEN / NOT VERIFIED

Implementation and deterministic tests do not establish live connectivity.
No checklist item below has been executed against a real MAX bot/chat.
Use an approved isolated bot, existing test groups and authorized test users.
Do not change the team's shared webhook or start polling with its token.

## Configuration and prerequisites

Use the existing API + worker + private PostgreSQL + HTTPS reverse proxy.
`MAX_TRANSPORT=off` remains the local default. Only explicit `webhook` enables
inbound MAX and the read-only provider. Outbound MaxTransport is still off;
A-07 neither broadcasts messages nor registers subscriptions automatically.

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

## Checklist (all PENDING)

- [ ] Issued token accepted; read real bot identity with documented `GET /me`.
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

## Documented provider contract (checked 18 September 2026)

- [Chat metadata / API origin](https://dev.max.ru/docs-api/methods/GET/chats/-chatId-)
- [Bot membership and permissions](https://dev.max.ru/docs-api/methods/GET/chats/-chatId-/members/me)
- [Current administrators](https://dev.max.ru/docs-api/methods/GET/chats/-chatId-/members/admins)
- [Updates](https://dev.max.ru/docs-api/objects/Update) and
  [Message](https://dev.max.ru/docs-api/objects/Message)
- [Webhook secret and delivery](https://dev.max.ru/docs-api/methods/POST/subscriptions)
- [Bot start payload](https://dev.max.ru/docs/chatbots/bots-coding/masterbot)

The production provider uses these three read methods only. No bulk participant
sync, speculative pagination, group creation or settings mutation is implemented.
An unexpected non-null admin pagination marker is explicitly unsupported and fails
closed. HTTP/response-mapping contract tests use MockTransport and synthetic data.
