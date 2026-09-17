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

## C0 / B-00 — блокер полного acceptance

`view` — единственный серверный action. `NextAction` поддерживает известные
object descriptors, но CTA требует также реального handler. Component tests
действий обращения не означают готовности их endpoints. Неизвестные действия
игнорируются, permissions никогда не вычисляются из status.

`rule.verification_status` не равен provenance B-00. Только `demo` имеет
однозначное соответствие; остальные C0 rules нейтральны. Четыре origin types
поддержаны semantic-компонентом, но producer их не возвращает. Будущие статусы
проверены как входы UI, а не как реализованные lifecycle transitions.

Нет данных для location, affected/participant count, responsible organisation,
полного route/filing/appeal. `report_count` не подменяет число жителей.
Фильтры и отсутствующие mutation endpoints не добавлены. C0 без `retryable`
допускает transport retry при network/408/429/5xx и refresh при 409;
explicit `retryable=false` учитывается.
Expected/actual/impact: [handoff](../docs/status/dev-b.md),
[контракт](../docs/CONTRACTS.md). Backend DTO/OpenAPI/БД в B-02 не изменены.

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
