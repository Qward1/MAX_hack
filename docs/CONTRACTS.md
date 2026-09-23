# ДомСигнал — UX/API contract v0.1

## Responsibility Router и ActionCard — A-02, срез P3a

Детерминированный слой «кто отвечает и какой следующий шаг».
**Модель в нём не участвует:** вход — код подтипа и `location_scope` из
внутреннего контракта AI плюс серверный контекст дома. Организации, каналы,
телефоны и ссылки берутся только из справочника `regions/`. HTTP-границы в этом
срезе нет: DTO живут в `src/domsignal/contracts/routing.py` и появятся в
OpenAPI вместе с эндпоинтами следующего среза, поэтому дрейфа схемы нет.

### Слои справочника

`regions/_federal/responsibility.yaml` → `regions/<REGION>/responsibility.yaml`
→ муниципальная секция внутри файла региона → дом (таблица
`house_routing_profiles`). Нижний слой уточняет верхний: запись с тем же `id`
переопределяет, новая — добавляется. Каждый файл проверяется
`regions/responsibility.schema.json`, памятки — `regions/safety.schema.json`;
обе проверки входят в `scripts/validate_region_pack.py` и в
`scripts/check.py --scope contracts`. Существующий `regions/demo/pack.yaml`
и его схема не изменены.

### Видимость по статусу проверки

| `verification.status` | Кому видно |
|---|---|
| `verified` | Всем. Обязаны быть `verified_at` и `source_title`. |
| `demo` | Только домам с `is_demo`, с пометкой «Тестовые данные». |
| `needs_verification` | **Никогда.** В маршруте остаётся только счётчик `hidden_unverified_channels`. |

Непроверенная организация не называется даже во внутреннем поле маршрута.
Канал, у которого регион дома входит в `unavailable_regions`, исключается
(например, ПОС не предлагается для `RU-MOW`). Запись с `verified_at` старше
180 дней получает `stale: true` и показывается с пометкой «требует проверки»,
действие при этом остаётся доступным.

### `ResponsibilityRoute`

`route_type` (`uk_internal | municipality | resource_supplier |
emergency_service | regional_operator | other_authority | unknown`),
`organization_id`/`organization_name` (null, если организация не проверена),
`channels[]` (только видимые), `basis` (`rule_id`, текст, источник,
`verified_at`, `verification_status`), `directory_version`,
`directory_verified_at`, `automatic_integration` (true только для
`uk_internal`), `can_create_ticket`, `can_prepare_appeal`,
`requires_operator_choice`, `alternatives[]`, `match` (`rule | default | none`),
`hidden_unverified_channels`, `stale`.

`can_create_ticket` означает «у дома есть действующий период управления
(`HouseManagement`) на текущий момент». Это необходимое, но не достаточное
условие: `TicketService` дополнительно требует `ticket_intake_enabled` и
перепроверяет его в момент создания. Маршрут не заменяет эту проверку и не
утверждает, что заявка создана.

Порядок вычисления: неизвестный подтип → `other.unspecified`; правило
`emergency_service` (запах газа остаётся вызовом службы при любой территории);
`house_common` при активном управлении подключённой УК → `uk_internal`;
`house_territory` → по `territory_policy` дома (`uk`, `municipal`,
`mixed|unknown` → `requires_operator_choice`); правила справочника по приоритету
и слою, несколько равноправных → `requires_operator_choice` с `alternatives`;
подтипы общего имущества (`uk_default`) → `uk_internal`; иначе `unknown`.
Нет правила — `unknown`, а не догадка. Ошибка справочника или БД тоже даёт
`unknown` (`directory_version: unavailable`); сервис маршрута не бросает
исключений и не меняет `/ready`.

### `ActionCard`

Собирается детерминированно (`generated_by: rules`) из маршрута, аудитории
(`resident | operator`) и источника (`chat | explicit`): `title`,
`explanation`, `safety`, `facts[]` (только с источником), `actions[]`,
`disclaimer`, `demo_notice`. `ActionCardAction` — `type`, `label`, `enabled`,
`reason`, `url`, `phone` в стиле существующего `ActionDescriptor`; DTO инцидента
не меняется. `enabled=false` всегда сопровождается причиной: непроверенный
канал, незаполненная ссылка входа или отсутствие подключённой УК.

Блок `safety` приходит из `regions/_federal/safety.yaml` (продуктовые данные,
не модель) и показывается при любом маршруте, если есть признак опасности;
вызов 112 становится первым действием. Пошаговых инструкций без официального
источника в памятке нет — структура `steps[]` есть, но заполняется только
записью с источником.

**Запрещённые формулировки** в любом тексте карточки: «заявка отправлена»,
«обращение отправлено», «обращение зарегистрировано», «передано в», «срок
исполнения», «обязан». Продукт не подаёт обращение за человека и не
подтверждает внешнюю регистрацию: официальный канал открывает сам человек,
дальше остаётся «Житель отметил подачу».

## Явный путь и черновик обращения — A-04 + A-17/Product, срез P3b

HTTP-граница маршрутизации из P3a открывается этим срезом: DTO
`ResponsibilityRoute`, `ActionCard`, `RouteChannel`, `SafetyBlock` и
`RouteFact` впервые попадают в OpenAPI. Изменения аддитивны: ни одно поле и ни
один путь не удалены.

### Приём `/report`

Две формы одной команды. Если второе слово — валидный код категории
(`elevator | water | lighting | waste | other`), работает **прежний** ручной
путь без разбора. Иначе всё после `/report ` — свободный текст: в транзакции
приёма создаётся запись `explicit_intakes` и ставятся две задачи —
`ai.report.analyze` (пул `ai`, приоритет 30) и `report.fallback` (пул
`operational`, первая попытка через 30 с, приоритет 50). Запись захватывается
атомарно, поэтому ровно одна задача доводит дело до результата. Свободный текст
короче 5 символов игнорируется так же, как раньше игнорировался `/report` без
описания.

**Результат не зависит от живости AI-пула.** Остановленный `ai-worker`
задерживает разбор не более чем на задержку сторожа и не отменяет его.

### Решение по маршруту

| Маршрут | Заявка УК | `route_outcomes.decision` | `explicit_intakes.result_kind` |
|---|---|---|---|
| `uk_internal` + уверенная зона | создаётся с категорией разбора | `ticket` | `ticket` |
| `uk_internal` без уверенной зоны | создаётся как `other` | `needs_clarification` | `needs_clarification` |
| `municipality`, `resource_supplier`, `regional_operator`, `other_authority`, `emergency_service` | **не создаётся** | `external` | `external_route` |
| `unknown` / `requires_operator_choice` | создаётся как `other` | `needs_clarification` | `needs_clarification` |
| автор не найден среди жителей | не создаётся | записи нет | `ignored` |

При непустых `danger_kinds` личное сообщение с блоком безопасности и телефоном
112 уходит **при любом маршруте** и стоит первым в тексте.

`classification_mode` отражает происхождение классификации: `model`, когда
ответ модели прошёл наш валидатор, иначе `rules`. `manual` остаётся значением
ручного пути.

### Доставка карточки маршрута

Новое назначение доставки `purpose = route_action_card` в **существующей**
цепочке outbox → `notification_deliveries`. Второго транспорта нет,
`launch_ref` общий (префикс `r_` вместо `w_`). Доставка относится к
`route_outcome_id`, а не к заявке: внешний маршрут заявку не создаёт, поэтому
`notification_deliveries.ticket_id` стал nullable, и ровно один из двух
предметов обязателен.

Текст сообщения детерминированный и снимается в момент разбора: заголовок
маршрута, основание с источником, один-два факта канала с источником,
дисклеймер. **Текст модели (`clean_description`) в сообщение не попадает** —
он нужен только в черновике, где его правит человек. Запрещённые формулировки
P3a действуют и здесь.

### Новые endpoints

| Method/path | Request → response |
|---|---|
| `POST /api/v1/houses/{house_id}/reports/preview` | `{description}` → `{analysis, action_card}`. Синхронно, **только правила**, без побочных эффектов. |
| `POST /api/v1/incidents/{incident_id}/join` | `Idempotency-Key` → актуальный `IncidentDetail`. Новый `Report` под тем же `Incident`; новый Ticket **не** создаётся; закрытый инцидент → `409 incident_closed`. |
| `POST /api/v1/appeal-drafts` | `{house_id, route_outcome_id \| report_id}` → `AppealDraftView` (`201`). Один черновик на один исход маршрутизации у автора. |
| `GET /api/v1/appeal-drafts/{draft_id}` | → `AppealDraftView`; чужой черновик → `404`. |
| `PATCH /api/v1/appeal-drafts/{draft_id}` | `{text, version}` → `AppealDraftView`; устаревшая версия → `409 stale_version`, сохранённый текст не затирается. |
| `POST /api/v1/appeal-drafts/{draft_id}/mark-filed` | необязательный `{reference}` → `AppealDraftView` с `provenance.origin = user_reported`. |

`ReportPreview.analysis` содержит `subtype`, `category`, `location_scope`,
`entrance`, `floor`, `since`, `danger_kinds`, `mode` (`model | rules | manual`),
`confident` и `reason`. Место и «с какого времени» отдаются только при наличии
дословной цитаты.

### Изменённые DTO

- `ReportCreated` += `action_card` (nullable, аддитивно) — та же
  детерминированная карточка, что в предпросмотре. В квитанции
  идемпотентности карточка не сохраняется: она собирается заново при каждом
  чтении, потому что справочник мог обновиться.
- `ClassificationMode` += `rules`, `model`.
- `CapabilityFlags` += `ai_analysis` (`LLM_PROVIDER != rules`). Выключенный
  флаг **не** скрывает явный путь: правила работают всегда.
- `IncidentLocation` += `observed_since`; read-model отдаёт `entrance`,
  `floor`, `label` и `observed_since` из сохранённых полей `incidents`.
  Значения попадают туда только вместе с цитатой, при чтении текст не
  разбирается.

### Черновик обращения

`mark-filed` записывает **только** утверждение жителя и отдаёт
`provenance.origin = user_reported` с пояснением «внешней системой не
подтверждено». Повторная отметка не меняет первую и не создаёт второго
события. Продукт не открывает официальный канал за человека: при незаполненной
ссылке действие `open_official_channel` приходит с `enabled: false` и причиной.

Требование канала «Госуслуги. Решаем вместе» — одна проблема, одно обращение —
закреплено уникальностью `(route_outcome_id, author_id)`.

### Пулы воркеров и бюджет

Один образ, пул выбирается параметром запуска: `python -m domsignal.worker.main
--pool operational|ai` (по умолчанию `operational`). Пул определяется видом
задачи по префиксу `ai.`, а не составом обработчиков, поэтому задача
незнакомого вида достаётся ровно одному пулу и честно проваливается, а не
остаётся в очереди навсегда. Доставка уведомлений живёт только в операционном
пуле.

Дневной бюджет вызовов модели — счётчик `ai_call_budget` в PostgreSQL:
атомарный инкремент с проверкой лимита, строка `scope_key = ''` хранит общий
дневной счёт, остальные — доли чатов. Значения по умолчанию: 1000 вызовов в
сутки, 20 % на чат. Отказ доли откатывает и общий счёт. Исчерпанный бюджет даёт
`execution.state = fallback_budget` **без обращения** к провайдеру. Таймаут
вызова берётся из профиля модели (`models.v1.yaml`); `LLM_TIMEOUT_SECONDS`
переопределяет его только если задан явно.

## Экран жителя: форма, карточка маршрута и черновик — срез P3c

Первый срез, где житель видит результат работы роутера. Backend расширен ровно
настолько, насколько без этого экрана не существует; изменения аддитивны.

### Новые endpoints

| Method/path | Request → response |
|---|---|
| `POST /api/v1/houses/{house_id}/reports/submit` | `Idempotency-Key` + `{description, category?}` → `ReportSubmitted` (`201`). Разбор синхронный и **только правилами**; решение принимает та же функция, что и чатовый путь. |
| `GET /api/v1/route-outcomes/{outcome_id}` | → `RouteOutcomeView`. Доступ только автору исхода в пределах дома; чужой и несуществующий дают одинаковый `404`. |

`ReportSubmitted` = `{route_outcome_id, decision, analysis, action_card, report}`.
`report` пуст для внешнего маршрута: заявка управляющей компании там не
создаётся. `decision` повторяет `route_outcomes.decision`.

`RouteOutcomeView` = `{id, house_id, created_at, decision, route_type,
action_card, incident_id, appeal_draft_id, directory_changed}`. Карточка
**пересобирается по текущему справочнику**, а не берётся из снимка доставки:
справочник мог обновиться. Если текущий `route_type` разошёлся с сохранённым,
`directory_changed = true`, и интерфейс показывает одну честную строку.

### Решение по маршруту для формы

Таблица P3b действует без изменений: `uk_internal` + уверенная зона → заявка;
`uk_internal` без уверенной зоны, `unknown` и `requires_operator_choice` →
заявка `other` и `needs_clarification`; внешние маршруты → заявки нет.
Выбор из списка не меняет **решение**, но названная человеком категория не
заменяется на `other`, а `classification_mode` становится `manual`.

`RouteOutcome` получил `author_id` (кто автор исхода) и `submitted_text` (слова
жителя из формы). У чатового пути текст по-прежнему живёт в `explicit_intakes`,
поэтому `AppealDraftService` берёт описание из `submitted_text` только когда
записи приёма и заявки нет — иначе черновик внешнего обращения из формы остался
бы без сути проблемы.

### Кандидаты в дубли

`ReportPreview` += `duplicates: list[DuplicateCandidate]` (максимум 3).
Правило детерминированное и без модели: тот же дом и тот же период управления,
открытый статус (`detected|open|reported|overdue|escalated`), та же продуктовая
категория, создана не позже 14 суток назад, сортировка по `created_at` убыв.

`DuplicateCandidate` = `{incident_id, title, category, status, created_at,
report_count, participant_count, match_reason}`; `match_reason` — короткая
строка из шаблонов продукта, не свободный текст.

Когда кандидаты есть, `ActionCardBuilder` получает `existing_ticket_ref`
(заголовок первой проблемы) и в карточке появляется `join_existing`.
**Идентификатор для перехода интерфейс берёт из `duplicates`**, а не из
заголовка. Автоматического слияния нет ни на одном пути: пока житель не выбрал
сам, не отправляется ничего.

### Резолвер запуска

`GET /api/v1/notification-launch/{ref}` принимает `r_[A-Za-z0-9_-]{32}` наравне
с `w_`. `NotificationLaunch` расширен аддитивно: `kind` (`ticket | route_card`,
по умолчанию `ticket`), `route_outcome_id`, а `incident_id` стал nullable — у
внешнего маршрута заявки нет. Проверки те же: получатель доставки, членство в
доме и актуальные права; любое несовпадение — `404` без различий в тексте.

### Флаги возможностей

`CapabilityFlags.routes` — справочник региона загружен и роутер собран;
`CapabilityFlags.appeals` — черновики доступны. Оба вычисляются из
`RoutingService.available`. Mini app прячет новые экраны при `false`, и доска
B-02 этим не затрагивается.

## Пассивное чтение подключённого чата — A-17/Product, срез P4

Подключённый чат читается целиком: реплики складываются в окна, окно
разбирается одним вызовом ядра, из окна рождаются сигналы с цитатами, а
опасность замечается ещё в транзакции приёма — без модели и без сети.
**HTTP-границы для сигналов в этом срезе нет** (её вводит P5): OpenAPI и
сгенерированный TS не меняются. Проверка и показ — read-only инструментом
`python -m domsignal.tools.signals_preview --house <id> [--pool inbox|audit]`.

### Приём и структурный фильтр

`MaxEvent` получил `mid` (`message.body.mid`) и `reply_to_mid`. Ссылка на
исходное сообщение берётся только из документированного `Message.link`
(`LinkedMessage`: `type` = `forward | reply`, `message` = `MessageBody` с `mid`):
`reply_to_mid` заполняется только для `type = reply` и валидного `mid`, любая
другая форма даёт `None` — ссылку продукт не угадывает. Идентичность события
по-прежнему считается от `mid`.

В транзакции вебхука, после ветки `/report`, реплика кладётся в буфер
`chat_messages` только если: глобальный `PASSIVE_CAPTURE_ENABLED`, привязка
`active`, событие не раньше `activated_at`, у привязки
`passive_capture_enabled`, тип чата `chat`, отправитель не бот, текст не
пустой, есть `mid`, и это не команда боту (`/report …`, `/start` — у них свой
путь). Всё остальное отбрасывается молча и без следа. Пара `max_chat_id + mid`
уникальна: повтор вебхука второй строки не создаёт. Текст обрезается до 4000
символов с флагом `text_truncated`; `author_ref` — устойчивый псевдоним автора
в пределах дома (`ai.masking.author_alias`: «A», «B», …, номер не
переиспользуется, связь с человеком — только в `chat_author_aliases`).

Ошибка в правилах, сборщике окон или роутере приём не роняет: каждый шаг идёт
в своей точке сохранения, исключение логируется кодом, реплика остаётся в
буфере, вебхук отвечает 200.

**Правок и удалений сообщений продукт не видит.** MAX присылает
`message_edited` и `message_removed`, но подписка ДомСигнала — ровно шесть видов
(`bot_started`, `bot_stopped`, `bot_added`, `bot_removed`, `message_created`,
`message_callback`; `tools/max_subscription.py`). Удалённая или исправленная в
чате реплика остаётся в буфере в исходном виде до конца срока хранения; это
единственная защита, и она описана здесь прямо.

### Контур 1: опасность в транзакции приёма

`screen_message_for_danger(text, line_id=mid)` — чистая функция ядра, по
полному тексту, до окна и до любой обрезки. Продукт её не дублирует и не
расширяет.

| Срабатывание | Что происходит |
|---|---|
| есть без `negated` | Предварительный критический сигнал (`strength=critical`, `source=rules`, флаг `preliminary`, цитата, вид опасности); окно закрывается сразу; `ai.window.analyze` с приоритетом 20; оповещение операторов — задача `signal.alert` приоритета 10 в операционном пуле; памятка в чат |
| только `displaced` («в соседнем доме», «в прошлом году») | Предварительный критический сигнал с флагом `displaced`, **без памятки**; ждёт вердикта окна |
| только `negated` | Ни сигнала, ни памятки; событие `danger_negated` без текста |

Повторное сообщение об опасности того же вида в том же доме в течение 30 минут
присоединяется к открытому критическому сигналу (счётчики, цитата) и не
создаёт второго оповещения. Памятка того же вида в тот же чат не повторяется
чаще раза в 30 минут.

Получатели оповещения — сотрудники текущей УК дома с подтверждённым
отображением в MAX, чей доступ к дому подтверждает существующая политика
(`MembershipService.require_house` + `ticket.read`). Новой модели доступа нет.
Получателей нет — доставка `skipped` с причиной `NO_RECIPIENTS`, сигнал всё
равно в очереди. Транспорт тот же: outbox → `notification_deliveries`.

### Сборщик окон

Состояние окна — `conversation_windows` (`open → closed → analyzing → done`,
одно открытое окно на привязку). Политика — ядра: `WindowPolicy` и
`split_stream`; значения — из настроек `PASSIVE_WINDOW_SILENCE_SECONDS` (120),
`PASSIVE_WINDOW_MAX_LINES` (10), `PASSIVE_WINDOW_MAX_AGE_SECONDS` (300).

- Реплика присоединяется к открытому окну, если политика ядра не отделяет её;
  иначе окно закрывается (`silence | max_age | max_lines`) и открывается новое.
- Десятая реплика и опасность закрывают окно прямо в транзакции приёма.
- Тишину проверяет отложенная задача `chat.window.tick` (операционный пул) на
  `min(last_line_at + тишина, first_line_at + возраст)`. Одна задача на окно:
  её идентификатор лежит в `tick_job_id`, тик либо закрывает окно, либо
  переносит себя, не расходуя попытку. Повторный тик по закрытому окну ничего
  не делает; окно и задача переживают перезапуск воркера.

### Разбор окна в AI-пуле

`ai.window.analyze` (добавлен в `AI_JOB_KINDS`): короткая транзакция захвата
`UPDATE … SET state='analyzing' … WHERE state='closed' OR (state='analyzing'
AND claimed_at < now() - 600s)`; чтение реплик окна, до пяти предыдущих реплик
чата как контекста (`is_context=True`), до десяти открытых сигналов и заявок
дома (`OpenItem`) и подсказки подъезда из `scope_value` привязки; **один**
`WindowAnalyzer.analyze(window)` вне транзакции; короткая транзакция записи,
которая сначала переводит окно в `done` при своём `claimed_by` — поэтому гонка
двух задач и повторный запуск дают один набор сигналов. Бюджет —
`PostgresBudgetGuard` с долей на привязку; исчерпан — вызова нет,
`execution_state = fallback_budget`, результат правил. Чтение выключено к
моменту разбора — окно закрывается как `capture_stopped` без сигналов.

Что продукт делает с результатом (силу не пересчитывает, fusion не
переопределяет):

- `filtered` и выборка аудита → `disposition = audit_pool` (`audit_reason`
  `filtered | audit_sample`); остальное — `inbox`.
- Слабых сигналов в очереди дома — не больше `PASSIVE_WEAK_DAILY_LIMIT` (10) за
  сутки; переполнение → `audit_pool`, `audit_reason = weak_overflow`.
- Склейка ветки: сигнал с тем же ключом (`подтип | dedupe_scope таксономии |
  подъезд`) и открытым статусом (`new | in_review`) в пределах
  `PASSIVE_DEDUPE_DAYS` (7) не создаёт второй строки: растут счётчики реплик и
  уникальных авторов, добавляются цитаты (всего не больше трёх), обновляется
  `last_seen_at`, сила только растёт. Реплика без подъезда не склеивается с
  объектом в известном подъезде. Отброшенное (`filtered`) не склеивается с
  сигналами очереди. Слияния заявок нет — это решение оператора (P5).
- Предварительный критический сигнал примиряется с вердиктом окна по реплике
  опасности: подтип, место и признаки берутся из окна; понижение — только если
  ядро понизило опасность по опровержению с валидной цитатой и оставило событие
  `emergency_downgraded` (причина и цитата лежат и в событии, и в
  `emergency.downgrades`). Иначе сигнал остаётся критическим
  (`emergency_kept`). Семантическая опасность, найденная только окном, даёт
  оповещение операторов и **не** пишет в чат.
- Маршрут считает `RoutingService.route_for_house` при создании сигнала и при
  смене подтипа; результат — `route_outcomes` с `source = passive` и
  `signal_id`. `decision` = `external` для внешних маршрутов, иначе
  `needs_clarification`: заявку или внешний маршрут выбирает оператор.
  ActionCard собирается при показе и не хранится.
- Все `audit_events` ядра пишутся в `signal_events` как есть, с версиями
  таксономии, правил, схемы, промпта и модели.
- Заявка УК или обращение из пассивного сигнала автоматически не создаются.

### `signals` и связанные таблицы

`signals`: `id, house_id, chat_binding_id, window_id, subtype,
product_category, object_label, entrance/floor/since` (значение + цитата +
`line_mid`), `location_scope` + `location`, `facets` (значения и цитаты),
`strength, strength_reason, disposition, audit_reason, source, flags,
emergency` (виды, источники, доказательства, понижения), `dedupe_key, status`
(`new | in_review | converted | routed_external | dismissed`),
`report_count, author_count, first_seen_at, last_seen_at, route_outcome_id`.
`signal_quotes` — не больше трёх дословных цитат (до 300 символов) с
псевдонимом и временем. `signal_lines` — роль реплики окна и её связь с
сигналом, без текста. `signal_events` — события аудита окна и сигнала.

### Голос бота в чате — ровно два сообщения

`MaxMessagingProvider.send_chat_message(chat_id, message)` — тот же
документированный `POST /messages`, что и личное сообщение, но с `chat_id`
вместо `user_id`; ответ принимается только если созданное сообщение лежит в
этом групповом чате (`recipient.chat_type = chat`), иначе исход неизвестен.
Доставка — существующий outbox (`chat.message.v1`) → `notification_deliveries`
(`purpose = chat_reading_notice | chat_safety_memo`, предмет — привязка,
получателя-человека нет) с теми же повторами, шлюзом адресата (не больше двух
сообщений в секунду в один чат) и состояниями. При `MAX_TRANSPORT=off`
отправитель инертен. Перед отправкой перепроверяются активность привязки, её
версия и включённое чтение; иначе доставка `superseded`.

1. **Сообщение о чтении чата** — один раз на привязку и её версию (dedupe
   `chat_notice:<binding>:<version>`), в момент включения чтения: кто
   подключил (управляющая компания), что бот читает сообщения, чтобы замечать
   проблемы дома, что он почти никогда не пишет сам, что сообщение в чате не
   является официальным обращением, кто может отключить чтение. Без сроков,
   гарантий и ссылок.
2. **Памятка безопасности** — только при срабатывании правил без `negated` и без
   `displaced`; текст — проверенный блок `regions/_federal/safety.yaml` (112 и
   его источник), не модель. Нет блока в справочнике — памятки нет.

Запрещённые формулировки (`FORBIDDEN_PHRASES`) действуют и здесь; модуль
шаблонов `services/chat_voice.py` входит в контрактный тест. Оповещение
оператора — личное сообщение (`purpose = signal_alert`) без кнопки: экрана
очереди до P5 нет, а кнопка в никуда запрещена.

### Выключатель, срок хранения, журналы

- Глобальный `PASSIVE_CAPTURE_ENABLED` (по умолчанию `false`) и
  `chat_bindings.passive_capture_enabled` (по умолчанию `false`). Выключено —
  реплики не сохраняются вовсе. Переключает сотрудник с `chat.connect`
  (`python -m domsignal.tools.passive_capture --binding … --actor …
  --enable|--disable`); включение при выключенном глобальном признаке
  отклоняется (`passive_capture_disabled`). Выключение сразу прекращает приём и
  оставляет собранные сигналы.
- `chat.buffer.purge` (операционный пул) ставится при старте операционного
  воркера и переносит себя каждый час: удаляет разобранные реплики, кроме пяти
  последних разобранных на чат (контекст), всё старше `PASSIVE_BUFFER_HOURS`
  (72, больше задать нельзя) независимо от состояния и роли реплик без сигнала
  старше того же срока. Пропуск запуска приём не ломает.
- **Что мы храним.** Сырые реплики — только во временном буфере и не дольше
  срока. После него от разговора остаётся лишь то, что привязано к сигналу:
  до трёх дословных цитат с псевдонимом автора и временем, счётчики реплик и
  уникальных авторов, роли реплик без текста и события аудита. Связь
  псевдонима с человеком — только локально, в `chat_author_aliases`.
- В журналы не попадают ни текст реплик, ни `external_user_id`: только
  идентификаторы окон, сигналов, привязок и коды состояний (контрактный тест
  проверяет ключи `extra`).

### Задачи и пулы

| Вид | Пул | Приоритет |
|---|---|---|
| `signal.alert` | operational | 10 |
| `ai.window.analyze` (окно с опасностью / обычное) | ai | 20 / 60 |
| `chat.window.tick` | operational | 40 |
| `chat.buffer.purge` | operational | 90 |

Выключенный AI-пул не задерживает ни приём, ни оповещение, ни памятку: они в
транзакции приёма и в операционном пуле.

### Миграция `20260922_0008`

Аддитивна: таблицы `chat_messages`, `conversation_windows`, `signals`,
`signal_quotes`, `signal_lines`, `signal_events`, `chat_author_aliases`;
`chat_bindings.passive_capture_enabled` (default `false`);
`route_outcomes.signal_id` и `source += passive`;
`notification_deliveries.signal_id`, `chat_binding_id`, `recipient_user_id`
nullable, назначения `signal_alert | chat_reading_notice | chat_safety_memo`,
предмет доставки — ровно один из четырёх. Downgrade отказывает, пока есть
данные пассивного чтения или включённое чтение, — как в P3b.

## Очередь сигналов оператора — срез P5

**IMPLEMENTED IN BRANCH** (`agent/b/p5-inbox`). Сигнал никогда не становится
заявкой сам: заявку, присоединение, внешний маршрут, выбор маршрута или
закрытие выбирает оператор, и каждое решение записано с автором, временем и
причиной. Контракт аддитивен: пути и схемы только добавлены.

### Доступ

Модель доступа прежняя. Чтение — право `ticket.read` (как очередь заявок),
решения — `ticket.work` (как создание и приём заявки); нового права нет. Сигнал
относится к периоду управления через привязку чата, поэтому новая УК дома не
видит сигналов из чата прежней. Порядок проверок как у заявок B-14: чужой дом и
чужой период управления — маскирующий `404`, дом доступен, но нет права —
`403`. Audit Pool (`disposition = audit_pool`) не отдаётся ни списком, ни по
идентификатору (`404`).

### Endpoints

| Method/path | Request → response |
|---|---|
| `GET /api/v1/signals` | `house_id?`, `status` (повторяемый), `strength` (повторяемый), `limit` ≤ 100, `offset` → `SignalList`. Только Inbox; порядок `critical → strong → medium → weak`, внутри — `last_seen_at` убыв. Без `house_id` — все дома сотрудника с серверным `page.total`. `counts` — по силе при тех же доме и статусе без фильтра силы; `attention` — открытые критические сигналы области (число, самый свежий, его время). |
| `GET /api/v1/signals/{id}` | → `SignalView` |
| `POST /api/v1/signals/{id}/create-ticket` | `{expected_version, category?, description?}` → `SignalMutation`. `ReportService.create_in_context` в контексте сотрудника (`classification_mode = manual`), дальше — обычный жизненный цикл Ticket. Описание по умолчанию — `ticket_draft.description`. Место с цитатой переносится в `incidents.location_*`. Статус `converted`, `report_id`/`incident_id`. Приём заявок выключен — `409 signal_action_unavailable`. |
| `POST /api/v1/signals/{id}/join` | `{expected_version, incident_id}` → новый `Report` под открытой проблемой того же дома и периода управления; второй Ticket не создаётся. Чужая проблема — `422` с `field_errors[incident_id]`, закрытая — `409 incident_closed`. |
| `POST /api/v1/signals/{id}/route-external` | `{expected_version}` → `routed_external` и снимок маршрута. Только для внешних маршрутов (`municipality`, `resource_supplier`, `regional_operator`, `other_authority`, `emergency_service`), иначе `409 signal_action_unavailable`. Продукт никуда ничего не отправляет. |
| `POST /api/v1/signals/{id}/choose-route` | `{expected_version, route_type}` → `in_review`. Только когда роутер вернул `unknown` или `requires_operator_choice`; допустимы `alternatives` роутера, а при `unknown` — все типы, кроме `unknown` (`SignalView.route_choices`). Недопустимый тип — `422` с `field_errors[route_type]`; маршрут определён справочником — `409`. Свободного текста организации нет: лишнее поле — `422`. |
| `POST /api/v1/signals/{id}/dismiss` | `{expected_version, reason, note?}`, `reason ∈ not_a_problem | duplicate | resolved | out_of_scope | spam`, `note` ≤ 500 → `dismissed`. Без причины — `422`. |
| `POST /api/v1/chat-bindings/{id}/passive-capture` | `{enabled}` → `PassiveCaptureView`. Тот же `PassiveCaptureService.set_capture`, что у CLI P4: право `chat.connect`, включение ставит сообщение о чтении чата один раз на версию привязки, при выключенном `PASSIVE_CAPTURE_ENABLED` — `409 passive_capture_disabled`. |

Все пять решений требуют `Idempotency-Key`. Порядок: доступ (`404`/`403`) →
квитанция (тот же ключ и тело — прежний результат с `replayed = true`, другое
тело — `409 idempotency_conflict`) → `expected_version` (`409 stale_version`) →
статус (решённый сигнал — `409 signal_decided`) → проверка действия. Переход
статусов проверяет сервер: из `new | in_review` в `converted | routed_external |
dismissed`; `choose-route` оставляет сигнал открытым (`in_review`).
`SignalMutation = {signal, replayed, effect_version}`.

`signals.version` растёт при каждом решении и при каждом изменении сигнала
движком P4 (новые реплики ветки, примирение, пересчёт маршрута): решение по
устаревшему снимку получает `409` и перечитывает карточку.

### `SignalView`

Поля `SignalSummary` (id, дом и адрес, `subtype` и `subtype_label` — подпись
таксономии, а до разбора окна — «Признак опасности», `object_label`,
`category`, сила и `strength_reason` — причина силы шаблоном продукта, статус,
счётчики реплик и уникальных авторов, `first_seen_at`/`last_seen_at`,
`first_quote`, `place`, текущий `route_type` и `route_source = router |
operator`, `danger_kinds`, `version`) плюс:

- `territory` — территория и её цитата; `place` — подъезд, этаж, «с какого
  времени» **только со значением и цитатой из собственной реплики сигнала**:
  цитата из реплики контекста (прошлого разговора чата) не показывается и в
  заявку не переносится;
- `quotes` — до трёх дословных цитат (псевдоним «Житель A», время, текст);
- `danger` — виды, подписи, источники `rules | semantic`, доказательства;
  при `evidence_unverified` вместо цитат разбора — сами реплики жителей из
  `signal_quotes`; флаги `preliminary`, `displaced`, `downgraded`;
- `action_card` — ActionCard `audience = operator`, собранная сейчас по
  текущему справочнику; при выборе оператора — по выбранному типу
  (`RoutingService.route_of_type`: организацию и канал подставляет справочник,
  если знает правило этого типа, иначе они пусты);
- `route_choices`, `route_chosen_by`, `route_chosen_at`;
- `join_candidates` — правило P3c (дом и период управления, открытый статус,
  та же категория, не старше 14 суток, до трёх); первой стоит проблема, в
  которую уже превращён такой же сигнал (тот же ключ склейки);
- `ticket_draft` — категория и описание по умолчанию: подпись подтипа,
  счётчики, место с цитатой и дословные цитаты. Текста модели в нём нет;
- `linked` — связанная проблема, её Report и Ticket (`T-N`);
- `decision` — кто, когда, причина и комментарий, снимок маршрута решения
  (тип, организация, канал, основание, источник, дата проверки, версия
  справочника);
- `allowed_actions` — `create-ticket | join | route-external | choose-route |
  dismiss` в порядке карточки маршрута; выключенное действие — с причиной;
  у решённого сигнала список пуст;
- `events` — безопасное подмножество `signal_events`: вид, подпись и время, у
  решений — автор. Деталей и версий модели нет.

### Хранение

Миграция `20260923_0009` аддитивна: `signals.version` (≥ 1, по умолчанию 1),
`decided_by`, `decided_at`, `decision_reason`, `decision_note` (≤ 500),
`report_id`, `incident_id`; CHECK «решённый статус ⇔ есть `decided_at`» и
допустимые причины. `signal_events.actor_id` — автор решения.
`conversation_windows.analyzed_by = ai | fallback`. `route_outcomes.basis`
(JSONB) и `directory_version` — снимок маршрута решения; исход решения
записывается с `author_id` оператора и `source = passive`, сигнал указывает на
последний исход. Downgrade отказывает, пока есть решения, выбор маршрута или
снимки.

### Доделки P4

- **Сторож разбора окна.** При закрытии окна в операционный пул ставится
  `chat.window.fallback` (приоритет 50) с задержкой
  `PASSIVE_ANALYSIS_FALLBACK_SECONDS` (90). Он делает тот же атомарный захват,
  что `ai.window.analyze`, и разбирает окно только правилами, без модели и
  бюджета. Кто захватил первым — тот и пишет; второй тихо выходит. Застал окно
  в разборе — переносит себя на 60 с, пока чужой захват не станет брошенным.
- **Настройки вместо констант:** `PASSIVE_DANGER_GROUP_MINUTES` и
  `PASSIVE_CHAT_MEMO_PAUSE_MINUTES` (по умолчанию 30).
- **Маршрут опасности до разбора.** `match.danger_kinds` в
  `regions/responsibility.schema.json`: правило совпадает по подтипу **или**
  по пересечению видов опасности, `location_scopes` остаётся фильтром, хотя
  бы один из `subtypes`/`danger_kinds` непуст. `danger_kinds` допустимы только
  у правил `emergency_service` (схема, разбор справочника и
  `scripts/validate_region_pack.py`). `federal.gas_smell.emergency` получил
  `danger_kinds: [gas]`: предварительный сигнал о газе сразу идёт в 112, а
  «затопило» маршрут не меняет. Правила `smoke_fire` нет: в 488-ФЗ нет статьи,
  прямо относящей пожарную охрану к службам вызова по 112 (ст. 3 ч. 2
  определяет их общим образом, перечень определяет Правительство — ст. 6 ч. 1
  п. 2).
- **Ссылка в оповещении оператора** — строка текста
  «Сигнал в кабинете: `PUBLIC_BASE_URL`/admin/?section=signals&signal=<id>»,
  без кнопки. Доступ проверяет сам кабинет.
- **Выключатель в кабинете** — endpoint выше; `ChatSummary` +=
  `passive_capture_enabled`, `CapabilityFlags` += `passive_capture`.

`Surface` += `signals` (у администратора УК и оператора, рядом с «Заявки»).
`TestSessionRequest.actor` += `p5-operator`, `p5-admin` — синтетические
участники браузерного стенда; в production тестовая сессия выключена.

## A-10 employee web-auth contract — 19.09.2026 branch slice

Prefix `/api/v1/auth/employee`:

| Method / suffix | Input / result |
|---|---|
| GET `/session` | Restore identity or constrained step; `{stage, csrf_token, recovery_codes: []}`. Missing/expired identity starts anonymous preauth. |
| POST `/login` | `{login_name,password}`; generic 401 for unknown/wrong/revoked/expired credentials; rotate preauth cookie. |
| POST `/password/change` | `{password}`; only forced-change preauth, rotates state. |
| POST `/mfa/enroll` | Preauth only; locally generated `{secret,otpauth_uri,qr_svg}`; no external QR service. |
| POST `/mfa/verify` | `{code}`; enrollment verification, authenticated cookie and recovery_codes shown once. |
| POST `/mfa/challenge` | `{code}`; normal TOTP second factor. |
| POST `/recovery` | `{code}`; requires verified password stage, consumes one recovery code. |
| POST `/logout` | Revoke employee session/preauth and clear cookies; idempotent. |

Stages: `login`, `password_change`, `mfa_enroll`, `mfa_challenge`, `authenticated`.
Responses never expose cookie tokens, authority claims or password hashes. The
enrollment response is sensitive and no-store. Every POST requires matching
Origin and X-CSRF-Token from the current stage (cookie-free repeated logout only
requires matching Origin). Business POSTs authenticated with an employee cookie
have the same CSRF requirement. 429 uses existing Problem Details with
`auth_rate_limited`; other errors retain sanitized common Problem shape.

Login identifiers normalize trim + lowercase ASCII `[a-z0-9][a-z0-9._-]{2,99}`;
unique constraint is in PostgreSQL. `/auth/max`, test-session environment gates,
and A-15 authorization contracts remain unchanged. Forbidden object scope may
return the established concealing 404. No `/register` endpoint exists.

## Статус

B-00 ниже сохраняет TARGET будущих workflows. **A-01 / C0.1 IMPLEMENTED IN
BRANCH `dev/b-experience`, 18.09.2026**: producer, consumer, OpenAPI и TS сведены
одним срезом. B-02 board/detail binding повторно проверен и DONE в ветке.
Baseline до среза: `804f198`; MERGED TO MAIN для A-01 не заявляется.
Live MAX Web/iOS/Android — NOT VERIFIED.

Опубликованы прежние C0 auth/me/capabilities/reports/incident endpoints и
диагностический replay. Analyze, appeals, join, feedback, admin, routes и
filing endpoints остаются TARGET. Перечень ошибок/полей C0.1 ниже отделён от
исторического C0 и полного B-00 target. Новых таблиц/миграций в A-01 нет.

Backend является source of truth для incident status, matching, route,
provenance, capabilities и `allowed_actions`. DEV-B отвечает за public DTO,
OpenAPI, generated TypeScript, их применение в core/services и транзакции.
Frontend не вычисляет права и не hardcode региональные правила. Deep link
передаёт navigation context, но не access grant.

Согласованная foundation boundary сохраняется: Pydantic/FastAPI → OpenAPI →
generated TypeScript types; внешние MAX identifiers на JSON-границе — строки,
время — timezone-aware UTC; API и bot вызывают общие services и не отдают ORM;
контракт меняется совместимо либо одним набором producer + consumer + generated
types + tests. AI-specific внутренний контракт пишет DEV-A, а его совместимую
границу с продуктом DEV-A и DEV-B проверяют вместе.

## Definition of Done продуктовых API

Уточнение [Q&A](decisions.md#qa-alignment-2026-09-18), требование к приёмке
каждого поставляемого среза; не свидетельство, что все проверки уже пройдены.

- Запросы, ответы, статусы, заголовки и обязательные поля соответствуют runtime
  OpenAPI; generated TypeScript воспроизводится из producer без расхождений.
- Проверяются аутентификация, авторизация, tenant/house/object scope и
  `allowed_actions`; сервер повторяет проверку при каждой операции.
- Успех подтверждается отдельным чтением сохранённого результата через API.
  Неоднозначный timeout → повтор с тем же idempotency key без дубля эффекта;
  тот же key с другим содержимым даёт определённый конфликт, не другую операцию.
- Конкурентные команды, устаревшая версия объекта/попытки имеют определённый
  исход без потери истории; конфликт не затирает ввод и предлагает свежий read.
- Ошибки используют **действующий C0.1 Problem Details**, включая A-07 codes:
  `application/problem+json`, type/title/status/code/detail/retryable/trace_id,
  nullable field_errors; без секретов, приватных полей, raw provider payload,
  отражения запроса, SQL/stack. Исторический пример C0 ниже не текущий контракт.

Предсказуемая передача данных для LLM — стабильная типизированная схема,
проверка результата до транзакции, безопасные переходы, clarification/manual
fallback при ошибке или неуверенности. Побайтовое совпадение генераций не требуется.
Для сдачи собственного API применяется A-13 и [release checklist](../README.md#чеклист-технической-сдачи--planned--not-run).

## A-16.1 — согласованный backend-контракт

Реализация согласована владельцем в A16_TICKET_BACKEND_CODEX.md 18.09.2026.
Таблица переходов зафиксирована до реализации. Incident.status не меняется.
Employee = актуальный company_admin либо operator с назначением на management;
manager = company_admin либо responsible. Work owner = текущий assignee,
который лично принял работу; manager может сообщить результат за такого исполнителя.

| From → to | Команда / событие | Кто и предусловия | Причина |
|---|---|---|---|
| отсутствует → new / needs_clarification | intake / created | Разрешённый Report, включённый management; неизвестная категория → уточнение | Серверный routing reason |
| new → accepted; in_progress → in_progress | accept / accepted | Employee, неназначенная или своя; повторное принятие в работе только после утраты/смены принятия | Нет |
| accepted → in_progress | start / started | Work owner | Нет |
| active → new либо прежнее ожидание | assign / assigned | Manager, новый исполнитель имеет актуальный ticket.work; прежнее принятие сбрасывается | Обязательна |
| new/accepted/in_progress → needs_clarification / waiting_external | clarify / wait-external | Work owner либо manager | Обязательна |
| needs_clarification/waiting_external → прежнее рабочее состояние либо new | resume / resumed | Work owner либо manager; чужое принятие не наследуется | Обязательна |
| in_progress → verification_pending | work-attempts / work_reported | Work owner либо manager; действующий лично принявший исполнитель | Явно публичный отчёт |
| verification_pending → closed | observations / result_confirmed | Resident + собственный Report; не исполнитель/автор отчёта; resolved, нет unresolved/rework | Наблюдение |
| verification_pending/closed → in_progress | observations / result_objected | Те же права, unresolved последней попытки | Наблюдение |
| active → cancelled | cancel / cancelled | Manager | Обязательна |
| active → то же | deadlines / deadline_recorded | Manager; internal либо agreed с источником/временем согласования | Обязательна |

Active включает new, accepted, in_progress, verification_pending,
needs_clarification, waiting_external. Reassign из verification_pending сохраняет
попытку/проверку; из accepted/in_progress возвращает new, из ожидания сбрасывает
resume state в new. Новому сотруднику всегда нужно лично принять работу.
Закрытие по таймеру и employee close отсутствуют. После любого unresolved
попытка навсегда требует rework: исправление ответа не закрывает Ticket без новой
WorkAttempt. Старые попытки и cancelled/newer Ticket принимают исторические
наблюдения без изменения текущей работы. Каждый ответ append-only, серверная
ревизия определяет актуальный ответ; поздний ответ не требует Ticket.version.

Ниже сохранены исходные требования проектирования; окончательное правило
закрытия/возобновления для этого среза задано таблицей выше.

### A-16.1 HTTP и handoff B-14

Аддитивное расширение C0.1, `/api/v1`; app/OpenAPI version остаётся `0.1.0`.
Все endpoints требуют существующий Bearer session. POST дополнительно требует
`Idempotency-Key` (8–200 символов); employee body содержит `expected_version >= 1`.
Actor/tenant/role/management в body запрещены. Problem Details: 401 без session,
404 чужой/прошлый management или неизвестный объект, 403 недопустимое действие
в доступном доме, 409 `ticket_conflict` для перехода/версии либо
`idempotency_conflict` для изменённого body, 422 для схемы. `X-Request-ID`
возвращается на успехах и ошибках; OpenAPI описывает фактические headers/errors.

| Endpoint | Runtime DTO / смысл |
|---|---|
| GET `/tickets?house_id=...` | TicketList; house обязателен; status, assignee_id, unassigned; limit 1–100, offset 0–100000; totals после scope/filter |
| GET `/tickets/{id}` | TicketView; внутренний номер, version, assignee/acceptance, source/created_by, latest_attempt, current deadlines, observation_conflict, requires_reassignment, allowed_actions |
| GET `/tickets/{id}/assignees` | Только manager; пагинация актуальных подходящих сотрудников с ID/display_name |
| POST `/tickets/{id}/assign` | AssignCommand: assignee_id (nullable), reason; сбрасывает прежнее принятие |
| POST `/tickets/{id}/accept`, `/start` | TicketCommand; только реализованный переход/полномочие |
| POST `/tickets/{id}/clarify`, `/wait-external`, `/resume`, `/cancel` | ReasonCommand; обязательная непустая reason |
| POST `/tickets/{id}/work-attempts` | WorkAttemptCreate: явно public_description; новая попытка и verification_pending |
| POST `/tickets/{id}/deadlines` | DeadlineCreate; kind, basis internal/agreed, start_event_id, due_at nullable, reason; agreed требует agreement_reference + agreed_at |
| GET `/tickets/{id}/events`, `/work-attempts`, `/deadlines` | Пагинированная внутренняя история; raw reason/employee IDs не resident API |
| GET `/incidents/{id}/work-status` | Отдельная allowlist ResidentWorkStatus; без Ticket → null status/ticket_id, без записи |
| POST `/work-attempts/{id}/observations` | ObservationCreate: outcome resolved/unresolved, optional comment/corrects_id; Ticket.version не требуется |
| GET `/work-attempts/{id}/observations` | Пагинированные внутренние наблюдения; employee scope |
| GET `/work-attempts/{id}/my-observations` | Только собственные ревизии при актуальном resident-доступе; чужих actor/comments нет |

Employee mutation возвращает TicketMutation: текущий TicketView, event_id,
effect_version, attempt_id и replayed. Replay сохраняет исходные effect IDs,
но показывает текущее состояние/версию после повторной проверки прав. Если
владелец/полномочия изменились, replay не выдаёт старый успешный ответ.
ObservationRecorded различает target_attempt_id, observation, applied_to_current,
state_changed, effect_version, replayed и безопасный current. На replay флаги
описывают исходный эффект, current — нынешнюю работу. Ответ по старой попытке
пишет историю, не переносится на новую. При более новом Ticket current указывает
на него, старая closed/cancelled работа не возобновляется.

`allowed_actions` Ticket имеет собственный enum TicketAction (пути команд).
Он вычисляется из текущего transition + AccessPolicy + владельца/принятия,
не меняет значения B-00 ActionDescriptor. Resident action `observe_result`
требует resident basis + свой Report и исключает reported_by/performed_by.
Для cancelled/старой попытки разрешена только историческая запись наблюдения.
User UUID — подтверждённая identity существующего session service; role switch
не меняет её. Join пока отсутствует, членство в чате не означает участие.

Статусы для UI: new — «Новая», accepted — «Принята исполнителем», in_progress —
«В работе», verification_pending — «Ожидает проверки результата»,
needs_clarification — «Нужно уточнение», waiting_external — «Ожидаются сведения
внешней стороны», closed — «Результат подтверждён жителем», cancelled —
«Отменена с причиной». WorkAttempt означает отчёт, не подтверждение устранения.
`responsibility=not_verified` не утверждает юридическую обязанность УК.
B-14 реализует frontend над этими endpoints; автоматического закрытия по времени нет.

### B-14 — аддитивное расширение внутреннего read-model

`TicketView.assignee_name` и `AttemptView.performer_name` — nullable display name
уже связанного исполнителя, без контактов. `AttemptView.resolved_count` и
`unresolved_count` — количество **актуальных** наблюдений попытки, после выбора
последней ревизии каждого автора существующим repository. Они одинаковы в
detail/latest_attempt и paginated work-attempts. Это контекст проверки, не голоса
и не новое правило закрытия. Defaults сохраняют совместимость старых consumers.
Backend lifecycle/access/DB не менялись, новых HTTP adapters/endpoints нет.
OpenAPI и generated TS перегенерированы. `ResidentWorkStatus`/`AttemptPublic`
не расширены этими внутренними полями; negative projection test проверяет их отсутствие.

Queue собирает отдельные разрешённые house pages существующего `/tickets`;
порядок каждой страницы сохраняется. Адрес — из `/me`, incident title/location/
counts — из авторизованного Incident Detail. Scope проверяет каждый endpoint.
`accept` одновременно принимает свободную заявку; отдельного `claim` нет.
Проигравший concurrent accept может получить **403 либо 409**: A-16 проверяет
текущие полномочия до expected_version. UI читает свежий Ticket и при новом
исполнителе показывает сообщение о занятой заявке, не маскируя отказ доступа.

Ответ на старую WorkAttempt по A-16.1 **сохраняется как исторический** с
`applied_to_current=false`, а не обязательно отвергается HTTP 409. B-14 не меняет
этот контракт: показывает обновление работы, делает GET work-status и никогда
не переносит ответ на новую попытку. Даже на replay проверяется target попытки
относительно свежего GET. После каждого POST UI ожидает отдельный read; при
потерянном POST response повторяет исходное body/key, при потерянном GET после
успешного POST повторяет только GET. Actor/tenant никогда не отправляются в команды.

Employee `/admin/` использует существующую Bearer-сессию в памяти. При её
отсутствии production показывает ввод действующего session token; после reload
нужен повторный вход. Новый login provider, MAX OAuth, постоянное хранилище токена
и MFA не добавлены: полноценный web-auth остаётся A-10/B-09. Только при backend
`test_auth=true` и non-production доступен явно обозначенный выбор `a16-*` fixture
через test-session. Query `test_actor` не даёт права в production.

ResidentWorkStatus содержит только номер/ID, состояние/version/times,
AttemptPublic (публичное описание, номер, время, rework), aggregate conflict,
свой последний ответ и DeadlinePublic. В нём нет исполнителей, actor IDs,
служебных причин, чужих комментариев, raw Report или agreement_reference.
Внутренняя история доступна отдельными пагинированными endpoints; общий чат
не получает её через resident DTO. Существенная mutation создаёт один
TicketEvent соответствующего вида и intent; work_reported с to_status
verification_pending одновременно фиксирует результат и ожидание проверки.

### Сроки, intake и outbox A-16.1

HouseManagement.ticket_intake_enabled по умолчанию false; включение — доверенная
серверная настройка/явный `seed_tickets`, без onboarding UI. Принятый Report
создаёт Ticket через общий ReportService.create_in_context, включая A-07 manual
group intake. Diagnostic max_replay не создаёт рабочую задачу. В выключенном
контуре сохраняется прежний manual путь. Один active responsible назначается;
несколько/ни одного → очередь с assignee=null. Категория other →
needs_clarification без автоматического назначения. Категорийных правил
обслуживания пока нет; это fallback по существующим назначениям, не вывод об
ответственности. Семантический matching A-06 не реализован: обычный новый
Report по-прежнему получает новый Incident. Несколько заранее связанных Report
не создают дубли Ticket и не уничтожают оригиналы. После закрытия ensure
возвращает тот же Ticket; следующий самостоятельный эпизод не создаётся.

Номер `T-<number>` уникален глобально в этой БД (PostgreSQL identity), стабилен,
может иметь пропуски, не является юридической нумерацией или номером ГИС ЖКХ.
Latest attempt и исходный incident/house/management защищены composite FK;
tenant не дублируется, берётся через immutable HouseManagement.

Deadline хранит отдельные kind response/completion/next_update и basis
internal/agreed/normative, start_event_id и серверное время исходного события,
due_at либо неизвестно, source/version применимого правила, recorded_by,
agreement reference/time и reason. Изменение append-only, current определяется
по revision отдельно для каждой пары kind/basis. Ручной agreed означает
зафиксированное сотрудником согласование с источником/временем, не независимую
внешнюю верификацию; без этих данных используется internal. Internal/ожидание
внешней стороны не переносят другие часы. Действующий region-pack контракт
имеет только demo правило с due_at=null: нормативная запись через HTTP запрещена,
пока A-02 не даст проверенную применимость. Нет нового калькулятора/общих 10 дней.

Существующий OutboxMessage: kind `ticket.notification_intent.v1`, status pending,
unique dedupe_key `ticket-event:<UUID>`. Typed payload TicketNotificationIntent:
schema_version=1, event/kind, ticket/incident/attempt, house/management/tenant,
ticket_version, audience staff/participants, optional исходные binding ID/version.
Нет текста комментария, причины, auth/initData/token или списка всех чатов.
Это intent, не SENT/READ; consumer A-05/B-03 материализует delivery согласно
контракту personal MAX delivery ниже.

Handoff A-05/B-03/B-06/B-07: перед отправкой заново проверить получателя и его
права, management/tenant, канал и для групп конкретные binding ID/version.
Не рассылать автоматически по всем чатам дома; сопоставить event version с
текущей работой, не отправлять устаревшее «исправлено» после reopening.
Ссылка открывает Incident/WorkAttempt, не выполняет mutation; проверка требует
отдельного авторизованного POST. Внешняя доставка после commit, её ошибка не
откатывает Ticket; API accepted не READ, внешнее exactly-once не обещается.

История защищена от UPDATE/DELETE; WorkAttempt допускает только монотонный
rework_required. Миграция 0004 не создаёт исторические Ticket/intents и запрещает
downgrade при новых данных/включённой настройке (нужен pre-A16 backup).
Рабочая история отделена от технических inbox/jobs; универсальный retention TTL
не введён. Применимость хранения юридически значимых запросов/ответов и №416,
официальный канал/роль партнёра и передача документов при смене УК остаются
отдельной проверкой. A-16 не является АДС или заявлением полного compliance.

Это не опубликованные DTO/endpoints и не разрешение реализации.
Report / Incident / Ticket / ExternalAppeal остаются отдельными объектами.

| Объект / граница | Требование |
|---|---|
| Ticket | Стабильный внутренний номер/ID, created time, источник, исходные management/house, история решений/работ, ответственный либо резервная очередь и следующий шаг. Не номер ГИС ЖКХ; неизвестная ответственность требует проверки диспетчером, а не автоматического обязательства УК. |
| Связывание | Несколько Report одного дефекта могут вести к одной работе без дубля активных Ticket на Incident; исходные сообщения, заявители и индивидуальная история сохраняются. |
| WorkAttempt | Конкретная попытка с конкретным отчётом о выполнении; повтор команды не создаёт новую попытку. Версия защищает конкурентные действия. |
| ResultObservation | Автор, время, результат/возражение и конкретная WorkAttempt. Выполнение, resident verification и закрытие — разные факты. Позднее возражение к последней попытке не теряется после чужого подтверждения; правило закрытия/возобновления ещё согласуется в следующей итерации A-16. Stale callback не применяется к новой попытке. |
| Domain event / notification intent | Типизированные вид/версия события, ID, actor, время, Ticket/attempt, management/house и безопасный payload; точные имена согласуются с producer. Изменение Ticket, история и intent записываются атомарно в существующий transactional outbox. |
| Доставка (A-05/B-03) | Семантические состояния: намерение создано / ожидает / API принял отправку / ошибка или неизвестный результат. Это не Ticket.status и не факт прочтения. MAX failure не откатывает сохранённую работу; сетевой вызов после commit, без нового broker и без обещания exactly-once. |
| Срок (A-02/A-11/Product → A-16) | Различаются срок ответа, согласованный срок работы, срок следующего обновления, нормативный срок при подтверждённой применимости. Каждый несёт тип, основание/источник и редакцию правила, исходное событие и время отсчёта, календарь/timezone и результат applicability. Нет основания/anchor — нет выдуманного срока. Универсальный due_at со смешанной семантикой не вводится; прежний nullable due_at Incident не переопределяется. |
| Resident projection / MAX | Разрешённая история без internal-only комментариев/контактов. Перед отправкой проверяются получатели, актуальные права, management/binding и версия; при открытии Mini App свежий API read. Ссылка не право и не mutation; callback повторно проверяет actor/scope/актуальную попытку. |

Нормы — в правилах/данных, не в Ticket state machine. Подробности применимости
и границы юридических фактов — [PRODUCT_ARCHITECTURE §9](PRODUCT_ARCHITECTURE.md#пп-рф-416--документальная-сверка-18092026).
Новые проверки — [acceptance QA](../scenarios/acceptance.md#qa-alignment--planned--not-run), все PLANNED / NOT RUN.

## A-07 connection contract — IMPLEMENTED IN BRANCH

### Personal MAX delivery contract — IMPLEMENTED IN BRANCH

- Existing A-16 outbox kind and payload are unchanged. Unique logical delivery:
  `(outbox_message_id, recipient_user_id, channel)`, channel=max, purposes
  ticket_accepted/work_verification. Consumer `processed` means durable fan-out
  or classified no-delivery, not provider success. `accepted` requires validated
  provider message ID; it means API acceptance, never read/push/resident approval.
- Policy: accepted is informational; work_reported requests verification of one
  current attempt. started/clarify/wait/cancel do not send private reasons or new
  notifications. Subsequent events reconcile accepted work cards. Unsent stale
  work becomes superseded. Only controlled category and public work result render.
- `GET /api/v1/notification-launch/{ref}` requires existing bearer auth. Ref is
  `w_` plus 32 random URL-safe characters (192 bits), unique, no authority.
  Intended resident, confirmed MAX mapping, participant, current house/management
  and AccessPolicy are rechecked. Missing/foreign/revoked targets share 404 masking.
  Response: incident_id, house_id, latest work_attempt_id|null, stale. Historical
  attempts navigate to the current work; no tenant/permissions/private metadata.
- Inline keyboard: open_app uses documented web_app=bot username and payload=ref;
  equivalent Mini App deep link is `https://max.ru/<bot>?startapp=<ref>`. Callback
  payload is `<ref>:resolved|unresolved`, below the documented 1024-character limit.
  Launch payload is below the 512-character A-Z/a-z/0-9/_/- limit.
- Existing secret-authenticated `/max/webhook` bounds input, maps message_callback
  to TicketCallback, deduplicates by callback ID, commits inbox+job before 200.
  Actor must match intended recipient and saved provider mid; forged/group/deleted
  message callbacks cannot mutate. A-16 observer checks prohibit self-verification.
  A first historical observation follows A-16 applied_to_current=false semantics.
  An existing own response makes quick-button replay inert; corrections/late
  objections remain available through the canonical authorized Mini App path.
- Callback observation and answer-job enqueue commit atomically. POST /answers
  updates the current card through its documented `message` field; no unsupported
  `notification` field is invented. Independent PUT reconciliation covers all
  affected cards, including observations submitted via resident HTTP.
- Retryable 429/connect rejection: exponential 2/4/8/16-second delays, maximum five
  calls; numeric Retry-After, if supplied, can lengthen delay up to one hour.
  401/403/invalid destination are terminal sanitized failures. Send read/write/total
  timeout, malformed success or 5xx is unknown (no documented exactly-once/POST
  idempotency guarantee); there is no automatic resend. Edit/answer boolean false,
  malformed/5xx/timeouts retry boundedly. Job/delivery state survives restart.
- MAX_TRANSPORT=off/recording never sends production notifications. Missing
  MAX_BOT_USERNAME in webhook mode is an explicit MAX_APP_NOT_CONFIGURED failure,
  not a fake success. Identity-less resident is skipped without Ticket failure.

OpenAPI/generated TS carry only the launch addition; A-16 DTO/actions are unchanged.
Provider contract tests are deterministic and are not live MAX evidence.

18.09.2026, on A-15. No main merge or live MAX claim. Public external IDs remain
strings; timestamps are UTC. Pydantic → OpenAPI → generated TS remain canonical.

| Endpoint | Authority / result |
|---|---|
| `POST /api/v1/houses/{house_id}/chat-connections` | Existing session + `chat.connect`; body `scope_type=house`/null or `entrance`/nonempty `scope_value`; derives current management/tenant; 201 ConnectionView |
| `GET /api/v1/chat-connections/{id}` | Current authorized employee of the same management; ConnectionView, no token replay |
| `POST /api/v1/chat-connections/{id}/approve` | Body `confirm: true`; fresh AccessPolicy + MAX verification; 200 BindingView; duplicate returns same active binding |
| `POST /api/v1/chat-connections/{id}/reject` | Authorized employee; terminal rejected ConnectionView |
| `POST /api/v1/chat-connections/{id}/cancel` | Authorized employee; terminal cancelled ConnectionView |
| `POST /max/webhook` | Explicit webhook mode + constant-time `X-Max-Bot-Api-Secret`; committed InboundAccepted, HTTP 200; off gives 503 |

ConnectionView includes id/house/status/expiry/candidate external chat/scope/error,
optional completed binding ID/version. `correlation_token` is present only on first
creation. Repeated initiation of the same open employee+management+scope returns
that request with token null; cancel/recreate if the one-time response was lost.
No public tenant, management, role or client chat override fields are accepted.
A deep link is not synthesized without a known real bot identity; caller receives
the opaque correlation payload. No management addresses/titles of foreign bindings
are returned in conflict errors.

Request states: created → connector_claimed → chat_detected → max_verified →
awaiting_approval → completed. A connector with the same persisted MAX identity
and current company authority may confirm directly from max_verified. External
connector waits for the target company; no mandatory Superadmin step. All paths
still require explicit approval. expired/cancelled/rejected are terminal.
Binding states: pending → active → suspended/revoked, suspended → revoked.
Reactivation always creates a new request/binding and increases chat-wide version.
Revoke is currently an internal authorized service, not a full administration API.

Problem Details uses existing lowercase machine codes: connection_expired,
connection_not_detected, connection_not_verified, connection_invalid_transition,
connection_changed_retry, connector_not_chat_admin, bot_permission_missing,
chat_already_bound, management_not_active, tenant_suspended, binding_not_active,
stale_binding_version; sanitized max_* codes identify provider failures.
Foreign scope is masked 404; visible scope without action is 403; conflict is 409;
provider unavailability during approval is 503/retryable. Verification failures
remain pending/error with no active binding. Failed verification/expiry persists.
No raw upstream responses or secrets appear in errors.

The internal provider returns ChatInfo/ChatMember, never raw MAX JSON to core.
The worker registers max.connection.verify, max.binding.health, max.group.report.
The report job contains chat ID, binding ID/version, user identity, event time and
explicit command text. Resolve/access/version validation precedes product core.
A-07 group command is `/report <elevator|water|lighting|waste|other> <description>`
(5–2000 characters); it reuses manual ReportCreate semantics. Ordinary conversation
is ignored unless passive reading is enabled globally and on the binding (P4, see
«Пассивное чтение подключённого чата» above); even then it never becomes a Report
or Ticket without an operator. `group_mode` capability is not
promoted to a live-ready automatic feature. Personal/manual APIs stay unchanged.

Mini App signed chat/start_param do not grant access or create ResidentMembership;
this version keeps the existing explicit authorized house flow. No participant sync.
More implementation/limits: [architecture](ARCHITECTURE.md) and
[real MAX checklist](MAX_LIVE_SMOKE.md).

## Общие значения

### Capabilities

`UserContext.capabilities` обязательно содержит boolean-поля `group_mode`,
`miniapp`, `photo_analysis`, `voice`, `admin`. Отсутствующая/false capability
скрывает соответствующую функцию; capability не заменяет resource-level
permission.

### Incident status

Допустимы только `detected`, `open`, `reported`, `overdue`, `escalated`,
`resolved`, `dismissed`. `reported` означает: пользователь сообщил ДомСигналу,
что сам отправил обращение. Это не подтверждение регистрации внешней системой.

### ActionDescriptor

```json
{
  "code": "prepare_appeal",
  "enabled": true,
  "reason": null
}
```

Target codes: `prepare_appeal`, `edit_draft`, `join`, `copy_draft`,
`open_official_channel`, `mark_filed`, `mark_resolved`, `mark_unresolved`,
`escalate`, `report_not_problem`, `retry`. `reason` обязателен и может быть
`null`; при `enabled=false` содержит безопасное пользовательское объяснение.

### Provenance

Общий value object: `origin` (nullable, если неизвестно), `source_title?`, `source_url?`, `verified_at?`,
`recorded_at?`, `note?`. Backend соблюдает ограничения и UI-семантику:

| `origin` | Обязательные данные | Смысл |
|---|---|---|
| `official` | `source_title`, `verified_at`; URL при наличии | «Официальный источник · проверено <date>». |
| `product_derived` | `note` и provenance использованных правил | «Рассчитано ДомСигналом на основе указанных правил». |
| `user_reported` | `recorded_at` | «Указано пользователем · внешней системой не подтверждено». |
| `demo` | явный `origin=demo` | «Демонстрационные данные»; не может сериализоваться как official. |

Источник, дата проверки и demo-state передаются вместе с данными, когда влияют
на решение. Неизвестный срок остаётся `null`, а не вычисляется UI.

## Минимальные DTO

Формальная required/nullable-схема должна быть зафиксирована DEV-B в Pydantic →
OpenAPI; ниже — обязательная семантика, а не параллельная JSON Schema.

| DTO | Минимальные поля v0.1 |
|---|---|
| `UserContext` | `id`, `display_name`, `capabilities` с пятью обязательными flags. |
| `HouseSummary` | `id`, `name`, `address`, `region_code`, `timezone`, server-provided `access_role`, `provenance`. |
| `IncidentSummary` | `id`, `house_id`, `title`, `category_code`, `status`, `report_count`, `participant_count`, `updated_at`, nullable `due_at`, `provenance`, `allowed_actions`. |
| `IncidentDetail` | Все поля summary; `problem: ProblemDetails`; backend-resolved `route` (`recipient`, `guidance`, `rationale`, official channel, nullable deadline, provenance); nullable `draft_id`; filing summary с user-reported provenance; `version`; `allowed_actions`. |
| `ProblemAnalysis` | `analysis_id`, normalized `problem: ProblemDetails`, nullable `confidence`, `requires_confirmation`, `analysis_mode` (`rules`, `model` или `manual`), server questions/options, duplicate candidates, nullable emergency instructions/contacts с provenance. |
| `AppealDraft` | `id`, `incident_id`, editable `text`, `version`, `created_at`, `updated_at`, official channel descriptor, `provenance`, `allowed_actions`. |
| `ActivityEvent` | `id`, `incident_id`, `kind`, `title`, `detail`, `occurred_at`, `provenance`, `allowed_actions`. |
| `ActionDescriptor` | `code`, `enabled`, nullable `reason`. |
| `ProblemDetails` | `description`, nullable `category_code`, structured nullable location (`entrance`, `floor`, `label`), nullable `observed_since`, server-defined answers needed for routing. |

`ProblemAnalysis` may degrade from model to rules/manual without changing the
submit contract. Emergency data overrides the ordinary route in presentation.
Matching and create-vs-existing decisions remain server-side. UI показывает
неопределённость по `requires_confirmation`, а не вычисляет свой confidence
threshold.

### AI ↔ product analysis handoff (target)

Это логическая граница внутри текущего backend package, а не требование нового
сервиса и не заявление о существующем endpoint сверх OpenAPI.

1. DEV-B аутентифицирует запрос, проверяет house/resource access и формирует
   допустимый текст и набор кандидатов.
2. DEV-A возвращает типизированный аналитический результат через согласованную
   семантику `ProblemAnalysis`: категория, извлечённые поля, candidates,
   uncertainty/`requires_confirmation`, вопросы и состояние выполнения
   (`rules`, `model`, `manual` или явная ошибка/fallback).
3. DEV-B валидирует результат, применяет safety и остальные бизнес-правила,
   принимает create/join/merge решение, выполняет транзакцию и формирует
   public response.

Semantic score является предложением, а не разрешением merge. Признак риска не
заменяет проверенный безопасный текст и не задерживает deterministic off-ramp.
Предложенная моделью формулировка сохраняется только после продуктовой
валидации, прав доступа и подтверждения пользователя. Модель не задаёт
юридическую ответственность, нормативный срок, факт внешней регистрации или
устранения. При недоступном AI продукт использует честный rules/manual путь, а
не выдуманный production-ответ.

## Target endpoints

Все пути ниже — **не реализованное обещание, а target v0.1**. Protected routes
проверяют authenticated user и resource scope на каждом запросе.

| Method/path | Request → response |
|---|---|
| `GET /api/v1/me` | → `UserContext`. |
| `GET /api/v1/houses` | → `HouseSummary[]` только доступных домов. |
| `GET /api/v1/houses/{house_id}/incidents` | Фильтры/пагинация → `IncidentSummary[]` + page metadata. |
| `POST /api/v1/houses/{house_id}/reports/analyze` | Начальное описание/ответы → `ProblemAnalysis`; не создаёт incident. |
| `POST /api/v1/houses/{house_id}/reports` | Подтверждённые `ProblemDetails` + nullable `analysis_id` → `IncidentDetail` нового или существующего incident. |
| `GET /api/v1/incidents/{incident_id}` | → `IncidentDetail`. |
| `POST /api/v1/incidents/{incident_id}/join` | → актуальный `IncidentDetail`; только при разрешённом `join`. |
| `POST /api/v1/incidents/{incident_id}/appeal-draft` | → новый или существующий `AppealDraft`. |
| `GET /api/v1/appeal-drafts/{draft_id}` | → последняя сохранённая `AppealDraft`. |
| `PATCH /api/v1/appeal-drafts/{draft_id}` | `text`, `version` → сохранённая `AppealDraft`; stale version → `409`. |
| `POST /api/v1/incidents/{incident_id}/appeals/mark-filed` | `draft_id` → актуальный `IncidentDetail`/event; сохраняется только user assertion и server timestamp. |
| `POST /api/v1/incidents/{incident_id}/feedback` | outcome `resolved`, `unresolved` или `not_problem` → актуальный `IncidentDetail`/event. |
| `GET /api/v1/me/activity` | Фильтры/пагинация → `ActivityEvent[]` + page metadata. |
| `GET /api/v1/admin/houses/{house_id}/summary` | Admin-scoped aggregate summary. |
| `GET /api/v1/admin/houses/{house_id}/settings` | Admin-scoped versioned settings. |
| `PATCH /api/v1/admin/houses/{house_id}/settings` | Versioned settings patch → saved settings; stale → `409`. |
| `POST /api/v1/admin/incidents/{incident_id}/dismiss` | Reason → incident `dismissed`; admin scope required. |

State-changing POST requests accept `Idempotency-Key`: same key+payload returns
the original effect, while the same key with another payload returns `409`.
Opening/copying a draft never calls `mark-filed` implicitly.

### `mark_filed`

The endpoint records only the authenticated user's assertion and emits
`user_reported` provenance. It may set incident status to `reported` under
backend transition rules, but must not set external confirmation, invent an
external ID, or claim acceptance by an official system. Retrying with the same
idempotency key has one domain effect.

## Error contract

Errors use `Content-Type: application/problem+json` and contain:

```json
{
  "type": "https://domsignal.example/problems/stale_version",
  "code": "stale_version",
  "title": "Данные изменились",
  "status": 409,
  "detail": "Обновите данные и повторите действие",
  "retryable": true,
  "trace_id": "opaque-id",
  "field_errors": null
}
```

`code`, `title`, `status`, `detail`, `retryable`, `trace_id` обязательны.
Validation errors дополнительно содержат `field_errors` как список
`{field, code, message}`. Минимальная семантика: `401` invalid/expired auth,
`403` authenticated but forbidden, `404` missing resource, `409` stale или
idempotency conflict, `422` validation. Sensitive auth details не попадают в
`detail`, URL или логи.

## A-01 / C0.1 — implemented producer contract

| DTO / field | Реальный результат |
|---|---|
| `ActionDescriptor` | `{code, enabled, reason}`; vocabulary выше, `reason` required nullable. Incident producer всегда возвращает `[]`: domain endpoints ещё нет. Read/navigation не action. Unknown codes consumer игнорирует. |
| `CapabilityFlags` | `group_mode=false`, `miniapp=true`, `photo_analysis=false`, `voice=false`, `admin=false`. C0 flags сохранены: report_create/incident_board/incident_detail true; max_live/routes/appeals/reminders/media false; test_auth только по settings local/test. |
| `MeResponse.capabilities` | Та же модель/значения, что `/capabilities.features`, версия `c0.1`. Role `admin` старого house membership не включает несуществующий admin product. Capabilities не предоставляют resource access. |
| `IncidentSummary` | Сохранены id/house_id/category/title/description/status/created_at; добавлены nullable `updated_at`, `due_at`, structured `location` (entrance/floor/label), `participant_count`, `is_demo`, `provenance`; исправлен фактический report_count. |
| `IncidentDetail` | Summary + реальные reports (id/description/created_at) + существующий DemoRule с отдельным origin/verified_at. Route/responsible/explanation/appeal/history не опубликованы: движок маршрута и lifecycle events отсутствуют. Reports — сообщения, не история смены статусов. |
| Missing data | location/updated_at/due_at = null: нет соответствующего persistence. Не извлекаем место из description и не выдаём created_at за updated_at. |
| Counts | Board: batched `COUNT(*)`, `COUNT(DISTINCT Report.author_id)` по incident; detail: длина reports и множество author_id. Report.author_id — non-null FK. Это уникальные авторы сообщений, не подтверждённые жители; несколько reports одного actor не увеличивают participant_count. Nullable participant_count сохранён для будущего источника без identity. |
| Provenance | `origin` отдельно от `verification_status` и `verified_at`. C0 создаёт incident только по manual report authenticated actor: user_reported; дом is_demo даёт demo. DemoRule всегда origin=demo независимо от verification_status. verified_at=null, проверка не выдумана. Unknown origin допускает null; official не выводится из verified. |
| Status | Только существующие open/resolved/dismissed. Будущий reported остаётся исключительно отметкой пользователя о самостоятельной отправке; filing endpoint не добавлен. |

`POST /api/v1/reports` с body.house_id сохранён; новый house-scoped alias и
analyze не нужны для convergence. Idempotency receipts старого C0 читаются по
сохранённым report/incident IDs, доступ проверяется снова, ответ сериализуется
текущим read model (с актуальными counts). Domain effect/IDs сохраняются;
legacy actions из сохранённого JSON не выходят наружу. Изменённый payload с
прежним ключом по-прежнему даёт 409 без повторного эффекта.

### A-15 — server-resolved OperationContext (IMPLEMENTED IN BRANCH)

18.09.2026, `dev/b-experience`, поверх A-01/C0.1. Не MERGED TO MAIN и не
LIVE VERIFIED. Формы report/incident/board сохранены. `/me.houses[].role`
совместимо расширен `operator`/`responsible`; `admin` остаётся public descriptor
для company_admin, `resident` — для resident access. Полная RBAC модель и
внутренние tenant/management IDs клиенту не требуются. OpenAPI/TS обновлены.

Единственный resolver — `MembershipService.require_house`:
authenticated actor → существующий House → текущая active HouseManagement
(`valid_from <= now < valid_to`, null upper bound) и active ManagementCompany →
active OrganizationMembership + HouseAssignment + неистёкшая active
ResidentMembership → `AccessPolicy` → immutable OperationContext.

- `actor_user_id`, `house_id` известны; `tenant_id` и `management_id` имеют
  `ScopeValue(KNOWN, UUID)`. При недоступном/отсутствующем текущем scope — 404,
  контекст с выдуманным или UNKNOWN tenant не создаётся.
- `organization_role`, `house_assignment_role`, `resident_membership_id` и
  `resident_access` выводятся из БД; `roles`/`permissions` и `source=api|max_replay`
  задаёт сервер. Source resident basis не означает право собственности.
- company_admin видит все текущие management своей УК; operator — только с
  активным assignment operator/responsible на **этот management**. Assignment
  без active organization membership не предоставляет сотруднику доступ.
- Resident basis относится к физическому дому. Active и expires_at проверяются
  на каждом запросе, независимо от login. Истечение и revoke не требуют
  перевыпуска bearer session. Независимое действующее resident basis сохраняет
  доступ при отзыве employee assignment.
- Platform `superadmin` хранится отдельно и не выдаёт read-all/impersonation.
- Текущие permissions: `incident.read`, `report.create`. Возможность действия
  требует и permission, и реализованный endpoint/business capability.
  `allowed_actions=[]`; будущие Ticket/admin/appeal actions не опубликованы.
- chat_binding_id/source_chat_id/binding_version остаются
  `ScopeValue(NOT_APPLICABLE, null)`. MAX ChatBinding — отдельная A-07.

Ни query/header tenant/management/chat/start_param/role/permissions, ни deep link
не authority. Неизвестные query metadata игнорируются, extra body fields
отклоняются (`extra=forbid`, 422). Optional detail.house_id — только selector,
он обязан совпасть с разрешённым объектом; multiple houses требуют явного выбора.

Чужой или отсутствующий house/incident → одинаковые 404 `resource_not_found`,
без раскрытия private content; известный scope без permission конкретного
действия → 403 `house_access_denied`. Отсутствующий обязательный house context
во внутреннем вызове — fail closed. `/max/replay` также проверяет совпадение
external_user_id с bearer actor (подмена actor → 403) и scope до inbox;
worker повторно разрешает scope перед созданием Report.

Incident queries требуют OperationContext и фильтруют **house + management**
до чтения content/построения DTO. При detail без selector допускается сначала
прочитать только incident.house_id как routing metadata, не ORM content.
Counts/reports читаются лишь для уже разрешённых incidents.

При смене УК старые Incident/Assignment сохраняют исходный management; ничего
не копируется. Board/detail этого среза показывают только **текущий management**
(в том числе жителям). Старая история остаётся в БД, отдельный архивный endpoint
и own-history-after-revoke ещё не реализованы. ResidentMembership сохраняется
на House; новые reports получают новый management. Повтор старого idempotency
receipt после switch снова проверяет scope и возвращает 404, не раскрывая старый
ответ и не создавая второй эффект. A-15 не реализует приватные Ticket/internal
employee данные; существующие C0.1 reports остаются частью разрешённой доски.

Migration `20260918_0002`: demo houses → явные demo company/management;
Incident.management_id backfill без смены ID/текстов. Resident basis = demo/manual,
verification_level=unverified, verified_at=null; legacy role/evidence сохранены
для lossless C0 rollback, но не участвуют в policy. Non-demo legacy management
изолирован и suspended/legacy_unverified до проверки; фиктивных активных УК нет.

### Ошибки C0.1 и migration

Единый `application/problem+json`: type/title/status/code/detail/retryable/
trace_id, nullable field_errors; для 422 список `{field, code, message}`.
Сохраняются lower_snake_case codes: authentication_required,
house_access_denied, resource_not_found, idempotency_conflict,
validation_error, feature_unavailable, invalid_init_data, internal_error.
Framework 404/405 нормализуются в http_404/http_405; 500 — безопасный generic.
Все реально выдаваемые error responses описаны problem+json в OpenAPI.

Миграция producer+consumer атомарная: request_id/errors удалены из body;
X-Request-ID header сохранён и равен trace_id, генерируется сервером. Клиентский
X-Request-ID не отражается. Validation не отдаёт input/body/ctx/stack/SQL,
не отражает даже имя неизвестного extra field. C0 service errors retryable=false
(включая не реализованную функцию и конфликт idempotency); internal_error=true.
Consumer читает retryable/trace_id и сохраняет ввод. Только неполный proxy/non-JSON
ответ получает локальный transport fallback; это не business permission.

Producer и miniapp выпускаются вместе; поддержка старого JS bundle не обещается.
Generated source: `docs/openapi.json` и `miniapp/src/shared/api/schema.ts`,
только штатными export/api:generate + `scripts/check.py --scope contracts`.

## ARCH-PLATFORM-v1 — компактный target delta

Основание: [продуктовая архитектура](PRODUCT_ARCHITECTURE.md), §§ 4–12.
Connection/Ticket/onboarding ниже — TARGET. Tenant/access foundation уже
реализован в A-15 выше; остальные возможности не опубликованы.
Существующие C0 и C1/B-00 сохраняются; точная форма, nullable-поля, версии и
совместимость принимаются в A-01, затем соответствующем предметном срезе.

| Область | Требуемая семантика / граница |
|---|---|
| Tenant/house context | Tenant определяется сервером через действующую HouseManagement с периодом; house ID не даёт доступ. Старые объекты сохраняют исходную организацию при смене УК. A-15 реализует этот foundation; lifecycle подключений остаётся TARGET. |
| Assignments / access basis | Несколько назначений пользователя; отдельные organization role, house assignment и resident basis с источником, актуальностью и отзывом. Админ чата не становится админом УК; указанный адрес не открывает чужую доску. |
| Connection lifecycle | Разрешение УК → действие администратора чата → проверка MAX → подтверждение дома → атомарная активация. Состояние, причина, время проверки, лимит/резерв и допустимое следующее действие; сбой проверки оставляет pending. Строковые коды и TTL ещё не приняты. |
| Report / Incident / Ticket / ExternalAppeal | Сообщение, общая проблема, рабочая заявка и внешнее обращение — разные объекты и scope. Ticket несёт очередь/владельца/рабочие переходы; отчёт о выполнении связан с попыткой, наблюдения жителя отдельны. Нельзя заменить Incident.status lifecycle заявки. |
| Provenance | Происхождение отдельно от актуальности/проверки и demo-маркера. Ручной номер/filing не становится external verified registration; WorkReport не становится resident confirmation. |
| allowed_actions / capabilities | Backend вычисляет действия по актуальному scope; endpoint проверяет права повторно. Backend capability означает реализованную функцию, Bridge capability — клиентский метод. Ни одна не заменяет object permission; неподдержанные действия не публикуются активными. |
| Ошибки | Различать отказ доступа, истёкшее/отозванное назначение, конфликт привязки/лимита/версии, истёкший/replayed контекст и временную недоступность проверки MAX. Не раскрывать чужой tenant/объект; коды и HTTP mapping принимаются с negative tests, не объявляются поддержанными здесь. |

A-01 фиксирует минимальный совместимый контекст read-model и стратегию old/new
producer: какие данные уже подтверждены C0, какие отсутствуют и не выдают доступ.
Он не создаёт tenant из query, не заполняет фиктивные tenant ID и не выдаёт
непроверенную роль как действующую. Persistence/authorization двух УК — A-15;
подключения — A-07, кабинет — A-10/B-09, Ticket — A-16/B-14. Новые переходы
публикуются только вместе с реализацией и generated contract tests.

## Foundation C0 — implemented reference, merged to main at 3d4a095

The following section is a HISTORICAL C0 reference at main `3d4a095`, not the current branch contract. A-01/C0.1 above supersedes its actions, counts, capabilities and error format. Other target workflows remain unimplemented; LIVE MAX remains NOT VERIFIED.

# ДомСигнал — контракты C0

## Источник и генерация

Pydantic/FastAPI — источник формата. Зафиксированный OpenAPI 3.1 находится в
`docs/openapi.json`, generated TypeScript — в
`miniapp/src/shared/api/schema.ts`. Проверка воспроизводимости:

```bash
uv run python scripts/check.py --scope contracts
```

Файлы обновляются только вместе: `uv run python scripts/export_openapi.py`,
затем `npm --prefix miniapp run api:generate`.

## Аутентификация и доступ

- `POST /api/v1/auth/test-session` — только local/test и только seeded actor
  `demo` или `outsider`; production configuration не может разрешить endpoint.
- `POST /api/v1/auth/max` — проверяет raw initData один раз и выдаёт короткую
  bearer session. Без bot token возвращает `503`, а не фиктивный успех.
- `GET /api/v1/me` — пользователь и закрытый список memberships.
- Любой house/incident read и report create повторно проверяет membership.
  Deep link, path/query `house_id` и скрытая UI-кнопка права не выдают.

Bearer token хранится mini app только в памяти. Внешние MAX IDs на JSON-границе
считаются строками.

## Реализованные endpoints

| Method/path | Семантика |
|---|---|
| `GET /api/v1/capabilities` | C0 version, environment и только реально доступные flags |
| `POST /api/v1/auth/test-session` | Явная local/test session |
| `POST /api/v1/auth/max` | MAX initData → session после server validation |
| `GET /api/v1/me` | Профиль и доступные дома |
| `POST /api/v1/reports` | Manual category + description → Report и новый Incident |
| `GET /api/v1/houses/{id}/incidents` | House-scoped board, `limit/offset/total` |
| `GET /api/v1/incidents/{id}` | Карточка, reports и demo rule provenance |
| `POST /max/replay` | Local/test normalized diagnostic event → durable inbox/job |
| `POST /max/webhook` | A-07 branch: secret-validated Update → committed receipt/state/job; off = 503; live NOT VERIFIED |

Routes, appeals, participants, feedback, admin, reminders и media отсутствуют в
OpenAPI. Capability flags для них `false`; успешных placeholder responses нет.

## Создание report

`POST /api/v1/reports` требует `Idempotency-Key` длиной 8–200 символов.
Область ключа: authenticated actor + action `report.create`. Одинаковое тело и
ключ возвращают исходный `201`-результат без второго Report; тот же ключ с
другим телом возвращает `409 idempotency_conflict`.

`classification_mode` сейчас принимает только `manual`. Ответ содержит
`report_id` и `IncidentDetail`. Встроенный rule имеет status `demo`,
`due_at=null` и явное примечание, что ответственный/срок не проверены.

## Ошибки

Ошибки API имеют content type `application/problem+json`:

```json
{
  "type": "https://domsignal.local/problems/house_access_denied",
  "title": "Access denied",
  "status": 403,
  "detail": "The authenticated user is not a member of this house",
  "code": "house_access_denied",
  "request_id": "uuid"
}
```

Политика C0: `401` — отсутствующая/истёкшая session, `403` — известный ресурс
чужого дома, `404` — ресурс не существует, `409` — конфликт idempotency key,
`422` — форма запроса не прошла Pydantic validation. `X-Request-ID` возвращается
в response header и body ошибки.

Клиент обязан безопасно показывать неизвестный enum/ошибку как недоступное
состояние; release bundle не включает автоматическую подмену backend.

## MAX и worker boundary

`NormalizedInboundEvent` — наш тестовый контракт, а не утверждение о live MAX
payload: `event_id`, единственный `event_type=diagnostic.report`, string
`external_user_id`, UUID дома, manual category, description, timezone-aware
`occurred_at`. Replay требует bearer session и запрещён в production.

`MaxTransport.send(OutboundNotification)` имеет реализации `off` и
`recording`. `off` не выполняет сеть и не меняет subscriptions; `recording`
разрешён только вне production. Реальный HTTP transport и webhook adapter —
контрактная задача DEV-B после credentials/fixtures.
# A-10/B-09 administration contracts — branch implementation

Public `POST /api/v1/onboarding/company-applications` validates plain bounded fields,
10/12-digit INN syntax and at least one contact. It is rate limited and returns the
same 202 receipt for accepted submissions and existing/open duplicates. It creates
no account, membership, session or house. INN is not externally verified.

`GET /api/v1/admin/bootstrap` supplies active company contexts and each context's
allowed surfaces. A company selector is input to authorization, never a grant.
`/companies/{company_id}` contains staff/invitations/assignments, organization,
overview, houses and management requests; foreign contexts are masked 404 and
operator administrative actions are rejected. MAX operations reuse existing A-07
connection endpoints; operators receive only read summaries.

`/auth/employee/invitations/{preview,register,claim,accept}` shares A-10 preauth,
Origin/CSRF and MFA checks. Replayed, expired, revoked or differently claimed links
fail closed. Company/inviter revocation is rechecked during MFA and acceptance.
Creation uses an Idempotency-Key; retries return metadata with no raw URL.

`/platform` contains bootstrap, company-applications and decisions, companies and
suspend/reactivate, first-admin invitation reissue, house-management-requests and
decisions, houses, binding-disputes, health and audit. Review transitions are
submitted → under_review/needs_info/approved/rejected/cancelled, under_review →
needs_info/approved/rejected/cancelled, needs_info → under_review/approved/rejected/
cancelled. Terminal decisions cannot replay or reopen; reasons and reviewer times
are retained. House approval requires explicit existing/new resolution; overlapping
active management is a 409 from A-15. Platform mutation responses use the same
private-content-free projections as reads. Full source: generated OpenAPI/TS.
