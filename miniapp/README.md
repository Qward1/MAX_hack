# Mini app — B-02

Продолжение FND-01: React 19, MAX UI 0.5.0, Vite, generated C0 types и fetch.
Production UI всегда использует настоящий API. Тестовые данные находятся
только в `src/test` и `tests/browser`, вне entry point.

## Реальная функциональность

- Board: дома из `/api/v1/me`, серверный порядок карточек, `limit/offset`,
  статусы, число **сообщений**, demo marker. Сводка относится к текущей странице.
- Detail: отдельный API read, полное описание, сообщения, дата, nullable срок,
  раскрываемый источник. URL хранит navigation context; reload снова загружает
  данные через auth/API. URL не предоставляет доступ.
- `useResource`: отмена и защита от запоздалых ответов, ручной refresh, stale
  notice после минуты/возврата в окно, retry, удаление старых данных при
  401/403/404. HTTP client ограничивает запрос 20 секундами.
- Сохранён ручной ReportForm FND-01 без анализа/обращений. Повтор того же
  payload после неопределённого результата использует прежний Idempotency-Key.

## Визуальный слой и MAX

MAX UI: `MaxUI`, `Typography`, `Panel`, `Flex`, `Button`, `Textarea`.
Semantic layer: `StatusBadge`, `SourceChip`, `IncidentCard`, `StatePanel`,
`NextAction`, `InfoRow`, `Timeline`, `DemoBadge`, `PageHeader`.
CSS добавляет ширину/отступы/акценты на токенах MAX. Тема определяется
провайдером; собственного переключателя нет.

Единственный доступ к `window.WebApp` — `src/shared/max/bridge.ts`: metadata,
capability detection, BackButton с отпиской, `openLink`/`openMaxLink`.
Source links сохраняют обычный browser fallback. Native sharing не используется
в пользовательском сценарии; dev-only diagnostics только сообщает доступность
метода. Диагностика удаляется из production bundle.

Источники: [MAX UI](https://dev.max.ru/ui),
[MAX Bridge](https://dev.max.ru/docs/webapps/bridge), установленные `.d.ts`
версии 0.5.0. Наследуем официальный `--font`, поскольку корневой стиль этой
версии ссылается на отсутствующий `--family-base`.

## A-01 / C0.1 binding

Producer/OpenAPI/generated TS сведены в `dev/b-experience` (18.09.2026).
B-02 повторно проверена на реальном HTTP/PostgreSQL и reload. `allowed_actions`
теперь descriptors; текущий producer отдаёт `[]`. Открытие карточки — обычная
навигация, доступ повторно проверяет API. Неизвестные actions игнорируются;
неподдержанные handlers не создают CTA или planned disabled buttons.

SourceChip читает `origin` напрямую, отдельно от verification. Counts разделены:
сообщения/report_count и уникальные авторы/participant_count (nullable). Место,
обновление и срок остаются неизвестными при null. Route/appeal/lifecycle events
не выдумываются; отображаются реальные reports. reported label по-прежнему
означает только пользовательскую отметку, endpoint filing ещё отсутствует.

House selector передаётся в detail API; при нескольких домах пользователь
выбирает явно. Capabilities включает пять B-00 flags; miniapp=false скрывает
экраны. Errors читают retryable/trace_id/field_errors, без legacy body fields.
Полный контракт и ограничения: [CONTRACTS](../docs/CONTRACTS.md).
Live MAX Web/iOS/Android остаётся NOT VERIFIED.

## Проверки

Используйте Node.js 24, как в foundation:

```sh
npm ci
npm run typecheck
npm test -- --run
npm run build
```

Отдельного frontend lint в foundation нет. Browser tests требуют построенного
приложения и C0 backend, по умолчанию `http://127.0.0.1:8017`.
**Используйте отдельную local/test БД**: real API test создаёт report и сессии
`demo`/`outsider`. MAX transport должен быть off. Миграция/seed описаны в
корневом README; для данного порта используйте `uvicorn ... --port 8017`.

```sh
npx playwright install chromium
npm run test:browser
```

Для установленного Chrome задайте `PLAYWRIGHT_CHANNEL=chrome`; другой URL —
`PLAYWRIGHT_BASE_URL`. Тесты блокируют MAX CDN: нестабильные внешние сервисы
не требуются. Только torture/error ветки подменяют HTTP; real API test работает
с PostgreSQL. Browser axe включает contrast; jsdom smoke проверяет семантику.
Артефакты — ignored `test-results/`.

Проверены Chromium, 320/430/1280px, обе темы, overflow, длинные данные,
Enter/Space для native summary, Tab/Shift+Tab, ссылки и Back. Это не live
проверка клиентов MAX iOS/Android/web: такая среда в сессии недоступна.

## B-14 — employee entry и browser fixtures

`/admin/` — отдельный HTML entry того же Vite build, без загрузки MAX UI/Bridge.
`/?incident=<id>` остаётся resident entry. В local/test backend с test_auth
администратор использует `a16-admin`; выбор роли явно помечен как тестовый.
Resident fixture открывается через `?test_actor=a16-resident&incident=<id>`.
Backend production игнорирует этот способ входа: нужен действующий bearer token,
вводимый в памяти на экране входа. Полный web-auth/MFA — отдельная A-10/B-09.

Для **полного** browser suite требуется отдельная PostgreSQL DB (отличная от
integration DB, поскольку pytest очищает её), существующие seeds и явное согласие
на тестовые fixture mutations. Из корня репозитория, с Node 24/Python 3.12/uv:

```sh
# DATABASE_URL указывает только на созданную для этого теста PostgreSQL DB.
export APP_ENV=test MAX_TRANSPORT=off B14_BROWSER_FIXTURES=1
uv run alembic upgrade head
uv run python -m domsignal.tools.seed_demo
uv run python -m domsignal.tools.seed_tickets
npm --prefix miniapp run build
uv run uvicorn domsignal.main:create_app --factory --host 127.0.0.1 --port 8030
# В другом терминале с тем же DATABASE_URL и test environment:
export PLAYWRIGHT_BASE_URL=http://127.0.0.1:8030
npm --prefix miniapp run test:browser
```

PowerShell использует `$env:APP_ENV='test'` и аналогичные присваивания.
Для установленного Chrome задайте `PLAYWRIGHT_CHANNEL=chrome`; иначе установите
Chromium существующей командой Playwright. Только B-02 можно запустить через
`npm --prefix miniapp run test:browser -- experience.spec.ts` без B14 fixtures.

`tests/browser/ticket_fixture.py` — CLI только для isolated test DB, с двумя
явными gates, не runtime endpoint. Добавляет синтетическое назначение оператора,
связанный Report для конфликта наблюдений, меняет/revokes собственные fixtures,
читает PostgreSQL evidence; не truncates и не использует live MAX.
Browser scenario сопоставляет persisted Ticket.version/status/attempt counts
с HTTP и UI после reload. Uncertain POST проверяется реальным commit с потерей
HTTP response; повторное тело/key и одна WorkAttempt подтверждены отдельно.
Readonly/adversarial HTTP подмены используются только для ошибок, неизвестных
значений и длинного текста. Сквозной путь и access checks идут в настоящий API.

## Браузерный стенд: переменные, без которых падают чужие спеки

Проверено на P5 (23.09.2026). Стенд — отдельная PostgreSQL DB (не та, что у
`pytest`, он её очищает) и один процесс API **без воркеров**: фикстуры сами
прогоняют задачи, и фоновые пулы стенда им только мешают.

| Переменная | Значение | Зачем |
|---|---|---|
| `APP_ENV` | `test` | тестовая сессия и фикстуры |
| `B14_BROWSER_FIXTURES` | `1` | иначе `ticket_fixture.py` и `signal_fixture.py` отказываются работать |
| `DATABASE_URL` | своя БД стенда | та же у API и у фикстур |
| `PUBLIC_BASE_URL` | ровно `PLAYWRIGHT_BASE_URL` (`http://127.0.0.1:8031`) | CSRF сверяет `Origin` кабинета именно с ним; иначе каждый POST — 403 |
| `AUTH_MFA_ENCRYPTION_KEY` | валидный ключ Fernet, общий у API и фикстур | иначе привязка второго фактора в `employee-auth.spec` падает на шаге QR |
| `PASSIVE_CAPTURE_ENABLED` | `true` | переключатель чтения чата в кабинете (`signal_fixture.py` включает приём у себя сам) |
| `MAX_TRANSPORT` | `off` | никаких сетевых вызовов MAX |
| `PYTHONPATH` | корень репозитория | `administration_fixture.py` импортирует `tests.fakes` |
| `PLAYWRIGHT_CHANNEL` | `chrome` | установленный Chrome вместо скачивания Chromium |

Перед каждым полным прогоном очистите **свой** `auth_rate_limits`
(`DELETE FROM auth_rate_limits`): все входы идут с `127.0.0.1`, и повторные
прогоны подряд упираются в ограничитель попыток (10 на идентификатор, 50 на IP
за 300 с).

```sh
uv run alembic upgrade head
uv run python -m domsignal.tools.seed_demo
uv run python -m domsignal.tools.seed_tickets
npm --prefix miniapp run build
uv run uvicorn domsignal.main:create_app --factory --host 127.0.0.1 --port 8031
# во втором терминале, с теми же переменными:
PLAYWRIGHT_BASE_URL=http://127.0.0.1:8031 npm --prefix miniapp run test:browser
```

`tests/ui-lint.spec.ts` (F1 §2.5) — проверка вёрстки всех экранов на 5 ширинах
в двух темах (правила — `docs/UX.md`, «Проверка вёрстки»); полный проход —
около 20 минут. Сузить: `UI_LINT_ONLY="^(site-|platform-)"`,
`UI_LINT_WIDTHS=390,1280`, `UI_LINT_THEMES=light`. `tests/browser/f1.spec.ts` —
статус и новый дом появляются без перезагрузки не позже 20 с, 403 раздела не
теряет сессию.

`signals.spec.ts` (P5) засевает сигналы настоящим путём P4 через
`tests/browser/signal_fixture.py`: события вебхука → `parse_update` +
`MaxWebhookService.accept` → окно → разбор правилами, без INSERT в `signals`.
Фикстура сама создаёт синтетический дом, оператора `p5-operator` и чат (через
A-07 с заглушкой проверки прав MAX), а в начале прогона закрывает оставшиеся
открытыми сигналы своего дома. Лимит слабых сигналов на дом в сутки у фикстуры
поднят: иначе после нескольких прогонов за день новые слабые сигналы честно
уходят в Audit Pool и в очереди их нет.

Два спека по умолчанию пропускаются: `notifications.spec.ts` (нужен
`ND_FIXTURES=1` и рантайм доставки) и `administration.spec.ts` (нужен
`B09_BROWSER_FIXTURES=1`). B09 на HTTP-стенде без MAX проходит проверки
разделов кабинета, но на шаге «Подтвердить подключение» API заново проверяет
чат настоящим провайдером MAX, которого на таком стенде нет.
