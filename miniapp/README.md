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
