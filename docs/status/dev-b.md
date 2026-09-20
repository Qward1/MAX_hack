# DEV-B — current handoff

## P3c — экран жителя: карточка маршрута, черновик и форма-разговор — 21.09.2026

START: worktree `.worktrees/b-p3c-resident-ux`, ветка `agent/b/p3c-resident-ux`
от `dev/b-experience=3ccaea7` (merge P3b `agent/b/p3b-explicit`). Push, rebase и
merge в другие ветки не выполнялись; `origin/main` не трогался. Это
**IMPLEMENTED IN BRANCH**, не MERGED TO MAIN и не LIVE VERIFIED.

### Результат

Житель, открывший mini app, всегда видит один понятный следующий шаг и
основание, почему шаг именно такой.

- **Форма стала разговором.** `ReportFlow` — три шага: свободный текст →
  «проверьте, что мы поняли» → результат. Категория из списка больше не
  обязательна и живёт в «Уточнить вручную». Предпросмотр показывает только те
  значения, что пришли с backend; `confident=false` виден отдельной строкой.
- **Отправка идёт через ту же цепочку решения.** `POST
  /houses/{id}/reports/submit` и чатовый путь используют один `_apply`,
  принимающий `ReportOrigin` (источник, текст, время, автор, необязательные
  запись приёма и категория). Второй копии правила «какой маршрут → что
  создаём» в репозитории нет.
- **Осознанный `join`.** `ReportPreview` отдаёт до трёх кандидатов по
  детерминированному правилу (тот же дом и период управления, открытый статус,
  та же категория, не старше 14 суток). Житель выбирает сам: «это та же
  проблема» или «нет, это другое». Пока он не выбрал, не отправляется ничего;
  автоматического слияния нет.
- **Экран карточки `?card=<route_outcome_id>`.** Порядок блоков закреплён:
  безопасность первой, затем маршрут, основание с источником и датой, факты
  канала, действия в порядке backend, дисклеймер. Карточка пересобирается по
  текущему справочнику; расхождение типа маршрута даёт `directory_changed` и
  одну честную строку на экране.
- **Черновик `?draft=<draft_id>`.** Три действия в закреплённом порядке,
  `409` не затирает ввод, отказ буфера обмена выделяет текст, после отметки
  редактирование выключено и рядом стоит «ДомСигнал не подтверждает регистрацию
  во внешней системе».
- **Ссылка `r_…` доводит до экрана.** Резолвер принимает оба префикса,
  `NotificationLaunch` вырос аддитивно (`kind`, `route_outcome_id`, nullable
  `incident_id`). Проверки те же; любое несовпадение — одинаковый `404`.
- **Флаги `routes`/`appeals`** вычисляются из `RoutingService.available` и
  скрывают новые экраны, не трогая доску B-02.
- **Честность кнопок.** Непроверенная ссылка — выключенная кнопка с причиной и
  подсказкой входа, без `<a>` в разметке. Имитации перехода нет нигде.

### Миграция

`20260920_0007` аддитивна: `route_outcomes.author_id` (FK `users`, nullable) и
`route_outcomes.submitted_text` (nullable). Существующие исходы не
переписываются. `AppealDraftService._sources` берёт текст из `submitted_text`
только когда нет ни записи приёма, ни заявки — это внешний маршрут из формы.

### Проверки

Отдельная тестовая база `domsignal-p3c-db` (`127.0.0.1:55485` не трогался;
свой контейнер на `55487`), отдельный стенд `domsignal-p3c-stand-db` на `55489`.
Чужие БД фикстурами не очищались.

| Команда | Результат |
|---|---|
| `uv run python scripts/check.py --scope backend` | PASS — ruff, mypy (132 файла), 477 unit/contract/ai тестов |
| `uv run python scripts/check.py --scope contracts` | PASS — OpenAPI и сгенерированный TS без дрейфа, валидация `regions/` |
| `uv run python scripts/check.py --scope frontend` | PASS — typecheck, 120 vitest, build |
| `uv run python scripts/check.py --scope integration` | PASS — миграция до head и 264 PostgreSQL-теста (22 новых), 8 мин 33 с |
| `npm --prefix=miniapp run test:browser` | 31 PASS, 2 skipped, 1 FAIL — `employee-auth.spec.ts`, причина ниже |

Новые тесты: 31 vitest (карточка 7, черновик 8, форма 10, навигация и резолвер
6), 22 PostgreSQL (`tests/integration/test_resident_experience.py`), 9 contract
(запреты формулировок на экранах жителя и форма новых DTO), 4 браузерных
сценария (`miniapp/tests/browser/resident-experience.spec.ts`).

**`employee-auth.spec.ts` не проходит на стенде по HTTP.** Кука
`__Host-domsignal_preauth` ставится с `Secure`, поэтому обратно она не
отправляется без HTTPS, и шаг входа получает «Invalid request origin or CSRF
token». Это воспроизводится голым `curl` без единой строки frontend и не
зависит от этого среза: `employee_auth.py`, `dependencies.py` и `src/admin/**`
не изменялись. Поверхность A-10 требует HTTPS-стенда (Caddy overlay).

### Ручная проверка на локальном стенде

`LLM_PROVIDER=rules`, `MAX_TRANSPORT=off`, API на 18025 → 8025, демо-дом из
`seed_demo`. Проверено по шагам: предпросмотр лифта (`elevator.stopped`,
подъезд «2» из цитаты, `uk_internal`), отправка (заявка + `route_outcome`
`source=form`), кандидат в дубли у соседа и присоединение (участников 2),
третий житель выбирает «нет, это другое» и получает новую проблему, внешний
маршрут (заявки нет, `municipality`, переход `enabled=false` с подсказкой
входа), чтение карточки автором (`200`) и соседом (`404`), черновик со словами
жителя, устаревшая версия (`409 stale_version`), сохранение (`version` 2),
отметка подачи (`provenance.origin=user_reported`, редактирование выключено).

Живой прогон с моделью (`LLM_PROVIDER=openai_compatible`) — **NOT RUN**: ключа
в локальном `.env` нет, из secret stores он не запрашивался и не выдумывался.

### Отклонения и самостоятельные решения

1. **Ручная категория не теряется в неуверенной зоне.** По §2.1 решение
   остаётся `needs_clarification`, но заявка уходит диспетчеру с категорией,
   которую назвал человек, а не как `other`; `classification_mode` = `manual`.
   Иначе «Это не так» с ручным выбором была бы кнопкой в никуда: неуверенный
   разбор обнуляет подтип и территорию, поэтому маршрут туда никогда не станет
   `uk_internal`.
2. **`create_ticket` и `report_to_uk_anyway` появляются только там, где на
   экране есть текст жителя** (шаг результата формы). На `?card=` их обработчик
   не передаётся, и кнопка не рисуется — та же дисциплина, что у `NextAction`:
   известная подпись не равна реализованному шагу. `RouteOutcomeView` текста
   жителя не отдаёт, и добавлять его в контракт ради кнопки не стали.
3. **`danger_kinds` не получили отдельного столбца.** Памятка при чтении
   карточки восстанавливается повторным разбором сохранённого текста теми же
   правилами: результат детерминирован, а новой приватной поверхности в БД не
   появляется.
4. **`--button-primary` переопределён в `.app-shell`.** Основная кнопка MaxUI
   даёт 3,1:1 и валит axe wcag2aa. Взят существующий токен `#235dcc` (6,0:1);
   нового дизайн-языка не появилось. Раньше это не всплывало: в B-02 у блока
   следующего шага не было активных основных кнопок.
5. **`escalated` переименован** из «Передано выше» в «Передано на следующий
   уровень»: подстрока «передано в» попадала под запрет формулировок, когда
   проверка шаблонов распространилась на экраны жителя. Backend такой статус
   сейчас не выдаёт.
6. **`seed_demo` получил двух жителей демо-дома** (`demo-neighbour`,
   `demo-third`) и `TestSessionRequest` — их псевдонимы. Без них честный выбор
   при дубле нельзя ни показать, ни проверить браузером.
7. **`ReportForm.tsx` удалён**, его место занял `ReportFlow.tsx`.
   `POST /api/v1/reports` не менялся и остался живым: его вызывает
   «Всё равно сообщить в УК».
8. **Форма не шлёт личное сообщение**: карточка возвращается в ответе, второго
   транспорта не появляется.

### Вопросы владельцу

1. **Ссылка входа в сценарий ПОС** по-прежнему пуста. Переход и в карточке, и
   в черновике выключен с подсказкой входа; имитации нет. Для показа «до
   официального сервиса» нужен проверенный адрес.
2. **Живой прогон модели** ждёт ключ в локальном `.env`.
3. **Стенд для A-10 по HTTPS**: `employee-auth.spec.ts` требует HTTPS-эджа,
   иначе `__Host-` кука не возвращается. Нужно ли добавить Caddy в браузерный
   прогон или спецификацию помечать skip без HTTPS?

## P3b — явный путь `/report <свободный текст>` и черновик обращения — 20.09.2026

START: worktree `.worktrees/b-p3b-explicit`, ветка `agent/b/p3b-explicit` от
`dev/b-experience=c01b9db` (merge P3a `agent/b/p3a-routing` и P2
`agent/a/a03-ai-core`). Push, rebase и merge в другие ветки не выполнялись;
`origin/main=3d4a095` не трогался. Это **IMPLEMENTED IN BRANCH**, не MERGED TO
MAIN и не LIVE VERIFIED.

### Результат

Сообщение жителя обычными словами доходит до следующего шага, и результат не
зависит от того, жив ли AI-пул.

- **Приём.** `services/group_messages.py`: второе слово — валидный код
  категории → **прежний** путь без изменений; иначе свободный текст создаёт
  запись `explicit_intakes` и две задачи — `ai.report.analyze` (пул `ai`) и
  сторожевую `report.fallback` (пул `operational`, через 30 с). Запись
  захватывается атомарным `UPDATE … WHERE state = pending`, поэтому ровно одна
  задача доводит дело до результата, а вторая тихо завершается.
- **Разбор.** `services/explicit_reports.py` — одна общая функция для обеих
  задач; отличается только наличие провайдера у анализатора. Вызов модели идёт
  **вне транзакции БД**: захват → проверка привязки → чтение контекста →
  разбор → короткая транзакция записи, которая заново подтверждает доступ.
- **Решение.** Зона УК с уверенной зоной → заявка через существующий
  `create_in_context` и `TicketService.ensure`; зона УК без уверенной зоны и
  `unknown`/`requires_operator_choice` → заявка `other` (`needs_clarification`);
  внешний маршрут → заявка **не** создаётся, сохраняется `route_outcomes` и
  жителю уходит личное сообщение с карточкой. При опасности личное сообщение с
  блоком безопасности и телефоном 112 уходит при **любом** маршруте и стоит
  первым в тексте.
- **Доставка.** Новое назначение `purpose = route_action_card` в существующей
  цепочке outbox → `notification_deliveries`; второго транспорта нет,
  `launch_ref` общий (префикс `r_`). `ticket_id` стал nullable, предмет
  доставки — заявка **или** исход маршрутизации. Текст детерминированный и
  снимается в момент разбора; текст модели (`clean_description`) в сообщение не
  попадает.
- **Пулы.** `worker/pools.py` + `WorkerRunner(pool=…)` + `claim_job(pool=…)`;
  `python -m domsignal.worker.main --pool operational|ai`. Пул определяется
  видом задачи по префиксу `ai.`, а не составом обработчиков: задача незнакомого
  вида достаётся ровно одному пулу и честно проваливается. Доставка уведомлений
  живёт только в операционном пуле. В `compose.yaml`/`compose.prod.yaml`
  добавлен сервис `ai-worker` из того же образа.
- **Провайдер и бюджет.** `bootstrap.build_ai` собирает провайдера из настроек
  и профиля модели: таймаут берётся из `models.v1.yaml`, а
  `LLM_TIMEOUT_SECONDS` переопределяет его только если задан явно (то же
  правило для `LLM_SCHEMA_MODE` и `LLM_MAX_TOKENS`). `services/ai_budget.py` —
  `PostgresBudgetGuard` на таблице `ai_call_budget`: атомарный инкремент с
  проверкой дневного лимита и доли чата, отказ доли откатывает и общий счёт.
  По умолчанию 1000 вызовов в сутки, 20 % на чат.
- **API.** `POST /houses/{id}/reports/preview` (синхронно, только правила, без
  побочных эффектов), `POST /incidents/{id}/join`, `POST /appeal-drafts`,
  `GET/PATCH /appeal-drafts/{id}`, `POST /appeal-drafts/{id}/mark-filed`.
  `ReportCreated` += `action_card`; `ClassificationMode` += `rules`, `model`;
  `CapabilityFlags` += `ai_analysis`; `IncidentLocation` += `observed_since` и
  начинает отдавать сохранённые поля.
- **Черновик.** `services/appeal_drafts.py`: каркас из проверенного
  справочника (адресат, канал, факты с источником), абзац описания — слова
  жителя либо переформулировка модели, прошедшая guard `no_new_facts`. Один
  черновик на один исход маршрутизации у автора. `mark-filed` записывает
  только отметку жителя (`user_reported`), повтор не меняет первую отметку.
- **Демо-данные.** `seed_demo` идемпотентно включает `ticket_intake_enabled`
  обоим демо-домам (решение владельца по итогам P3a).

### Синхронный протокол бюджета — почему так

Протокол `BudgetGuard` из `domsignal.ai.resilience` синхронный, а вызывается
изнутри работающего цикла событий: ни `await`, ни блокировка потока там
недопустимы, а синхронного драйвера PostgreSQL в проекте нет. Поэтому решение
принимается **заранее и атомарно** — `reserve()` в отдельной короткой
транзакции до обращения к провайдеру, — а `try_acquire()` только сообщает уже
принятое решение текущей задачи через contextvar. Семантика сохранена: проверка
и списание остаются одной операцией PostgreSQL и происходят до вызова. Вне
`reserve()` ответ «вызова не будет» — отказ в безопасную сторону.

### Проверки

Отдельная тестовая база `domsignal-p3b-db` (контейнер `postgres:16.10-bookworm`,
`127.0.0.1:55485`, БД `domsignal_p3b`); чужие БД фикстурами не очищались.
`ai_call_budget` добавлен в `TRUNCATE` фикстуры явно: у таблицы нет внешних
ключей, поэтому `CASCADE` её не захватывал и счётчик протекал между тестами —
это нашлось при первом прогоне.

| Команда | Результат |
|---|---|
| `uv run python scripts/check.py --scope backend` | PASS — ruff, mypy (132 файла), 465 unit/contract/ai тестов (29 новых) |
| `uv run python scripts/check.py --scope contracts` | PASS — OpenAPI и сгенерированный TS без дрейфа, валидация `regions/` |
| `uv run python scripts/check.py --scope frontend` | PASS — typecheck, 89 тестов, build |
| `uv run python scripts/check.py --scope integration` | PASS — миграция до head и 242 PostgreSQL-теста (65 новых), 10 мин 25 с |
| `docker compose … config` для local и production overlay | PASS, `ai-worker` с `--pool ai` в обоих |

Новые тесты — 94: пулы (7 unit + 6 PostgreSQL), бюджет (10 PostgreSQL), личное
сообщение с карточкой (10 unit), запреты формулировок по шаблонам (12 contract,
включая литералы внутри функций), приём (9 PostgreSQL), явный путь целиком
(14 PostgreSQL), предпросмотр и `join` (12 PostgreSQL), черновик (13 PostgreSQL),
`ticket_intake_enabled` в seed (1 PostgreSQL).

Три существующие проверки миграций сравнивали строки до и после обновления и
поэтому падали на новых столбцах. Добавлен `tests/integration/migration_columns.py`:
новые столбцы перечислены явно, а в проверке onboarding дополнительно
утверждается, что миграция оставила их пустыми.

### Ручная проверка на локальном стенде

Compose project `domsignal-smoke-p3b`, собственный volume, API на 18094,
`LLM_PROVIDER=rules`, оба воркера. Настоящего MAX здесь нет: токен и секрет
заведомо синтетические, поэтому исходящие вызовы MAX невозможны.

| Проверка | Результат |
|---|---|
| Стенд поднялся: migrate → seed → api + worker + ai-worker | PASS, `/ready` = ready |
| `ticket_intake_enabled` у обоих демо-домов после seed | PASS (`t`, 2 строки) |
| `preview` свободного текста про лифт | `elevator.stopped`, `house_common`, подъезд `2` из цитаты, `uk_internal`, `can_create_ticket=true` |
| `preview` про уличное освещение | `street_lighting.failure`, `municipal_territory`, `municipality`, канал `pos_gosuslugi`, `can_prepare_appeal=true`, переход `enabled=false` с причиной |
| `preview` про запах газа | `danger_kinds` = gas, `emergency_service`, памятка с телефоном 112, первое действие — звонок 112 |
| `POST /reports` | 201, в ответе `action_card` с маршрутом `uk_internal`; в БД создан Ticket (`status=new`) |
| `POST /incidents/{id}/join` | 200, `report_count` 1 → 2 |
| AI-пул остановлен: `ai.report.analyze` не тронут | PASS — `pending`, `attempts=0`, операционный пул его не берёт |
| Сторожевая задача через 30 с | PASS — `report.fallback` выполнен операционным пулом, `explicit_intakes.claimed_by = report.fallback`, состояние `done` |
| AI-пул поднят после сторожа | PASS — `ai.report.analyze` завершился тихо, второго эффекта нет (`reports` 2 → 2, `route_outcomes` 0) |

**Граница ручной проверки.** Групповой путь `/report` на локальном стенде не
доходит до заявки: `verify_binding_health` перед каждым групповым эффектом
обращается к MAX, а локально настоящего токена нет и быть не должно
(правило 15). Привязка честно уходит в `suspended`, исход становится `ignored`.
Это поведение A-07 «fail closed», а не дефект среза. Завершённый групповой путь
(заявка, внешняя карточка, `needs_clarification`, опасность) проверен
интеграционными тестами на PostgreSQL с детерминированным адаптером MAX.
Черновик обращения на стенде тоже не проверялся вручную: ему нужен исход
маршрутизации, которого без пройденного группового пути нет.

Живой прогон с моделью (`LLM_PROVIDER=openai_compatible`) — **NOT RUN**: ключа
в локальном `.env` нет, из secret stores он не запрашивался и не выдумывался.

### Отклонения и самостоятельные решения

1. **`miniapp/src/test/fixtures.ts` — одна строка вне разрешённых путей.**
   `CapabilityFlags += ai_analysis` делает поле обязательным в сгенерированном
   TypeScript, и без правки фикстуры `--scope frontend` красный. Правка
   минимальная (`ai_analysis: false`) и относится к согласованному комплекту
   producer + generated types + tests.
2. **Два аддитивных столбца сверх списка §5.**
   `explicit_intakes.clean_description` и `route_outcomes.intake_event_id`.
   Черновик обращения собирается отдельным запросом API уже после разбора,
   поэтому переформулировка модели и исходные слова жителя должны где-то
   дожить до этого момента. `reports.analysis` для этого не годится: он
   обязан оставаться без текста, а у внешнего маршрута заявки нет вовсе.
   Переформулировка лежит рядом с исходной репликой, которую та же таблица уже
   хранит по §5, поэтому новой приватной поверхности не появилось.
3. **Описание длиннее 2000 символов усекается** для `ReportCreate`; полная
   реплика остаётся в `explicit_intakes.text`, а в провенансе разбора стоит
   `text_truncated: true`. Иначе длинное сообщение не дало бы жителю ничего.
4. **Свободный текст короче 5 символов игнорируется** — как раньше
   игнорировался `/report` без описания. Ниже этого предела `ReportCreate` всё
   равно не проходит валидацию.
5. **`action_card` не сохраняется в квитанции идемпотентности:** карточка
   собирается заново при каждом чтении, потому что справочник мог обновиться.
6. **Ручной путь `POST /reports`** получает карточку с территорией
   `house_common` и подтипом `other.unspecified`: житель уже выбрал категорию
   проблемы дома, поэтому маршрут ведёт в УК, а не в честное «не определено».
7. `WorkerRunner.run_once` принимает `now` — только для проверок времени.

### Что нужно для P3c

1. Экран карточки маршрута и черновика в mini app. Ссылка из личного сообщения
   приходит с `launch_ref` вида `r_…`; резолвер `GET /notification-launch/{ref}`
   намеренно **не** расширен и отдаёт 404 для `r_`-ссылок — до появления экрана
   ссылка просто открывает приложение.
2. Форма отправки использует `POST /houses/{id}/reports/preview` для шага
   «проверьте, что мы поняли» и `ReportCreated.action_card` для результата.
3. `ActionCardAction.type` = `prepare_appeal` ведёт на `POST /appeal-drafts`;
   порядок в интерфейсе по §8 целевой архитектуры: «Скопировать текст» →
   «Открыть Госуслуги» → «Я отправил».

### Вопросы владельцу

1. **Ссылка входа в сценарий ПОС** по-прежнему пуста, поэтому в карточке и в
   черновике переход показан с `enabled: false` и подсказкой входа. Это
   единственное, что мешает демонстрации пройти до официального канала.
2. **Живой прогон модели** нужен ключ в локальном `.env`; сейчас NOT RUN.
3. Нужен ли `join` в mini app в P3c или он остаётся backend-возможностью.

## P3a — Responsibility Router, справочник и ActionCard (A-02) — 20.09.2026

START: worktree `.worktrees/b-p3a-routing`, ветка `agent/b/p3a-routing` от
`dev/b-experience=31df491` (merge P1 `agent/a/a03-ai-core`). Push, rebase и
merge в другие ветки не выполнялись; `origin/main=3d4a095` не трогался.
Это **IMPLEMENTED IN BRANCH**, не MERGED TO MAIN и не LIVE VERIFIED.

### Результат

Детерминированный слой «кто отвечает и какой следующий шаг» без модели и без
LLM. Эндпоинтов, UI и изменений OpenAPI/TS в срезе нет — HTTP-граница и явный
путь идут отдельным срезом.

- **Справочник как данные:** `regions/responsibility.schema.json`,
  `regions/safety.schema.json`, `regions/_federal/responsibility.yaml`,
  `regions/_federal/safety.yaml`, `regions/RU-TA/responsibility.yaml`
  (секция муниципалитета `kazan`). `regions/demo/pack.yaml` и его схема не
  изменены. `scripts/validate_region_pack.py` дополнен: схема каждого файла,
  существование `organization_id`/`channel_ids`, коды подтипов из
  `domsignal.ai.taxonomy`, `location_scopes` из контракта AI, обязательные
  `verified_at`/источник для `verified` и источник у каждого шага памятки.
- **Router:** `core/responsibility.py` (слои, объединение, видимость),
  `core/routing.py` (алгоритм), `services/routing.py` (загрузка и проверка
  один раз при старте, контекст дома из БД). Невалидный справочник не роняет
  приложение: все маршруты становятся `unknown`, `/ready` не меняется.
  Сервис маршрута не бросает исключений.
- **Профиль дома:** аддитивная миграция `20260920_0005` над `e107a3cff433`,
  таблица `house_routing_profiles`, репозиторий, CLI
  `python -m domsignal.tools.house_routing_profile` с аудитом `updated_by`.
  `seed_demo` идемпотентно ставит демо-дому на Чистопольской `RU-TA/kazan`
  и `territory_policy: unknown`, второму демо-дому — `uk`.
- **ActionCard:** DTO в `contracts/routing.py`, сборка в
  `services/action_cards.py`, предпросмотр
  `python -m domsignal.tools.route_preview`. `ActionDescriptor` инцидента не
  изменён. Запрещённые формулировки («заявка отправлена», «обращение
  отправлено», «обращение зарегистрировано», «передано в», «срок исполнения»,
  «обязан») покрыты тестом по всем комбинациям маршрут × аудитория × источник.
- **Проводка:** настройка `regions_dir` и `RoutingService`/`ActionCardBuilder`
  в `Container`. Роутеры, worker и bot их пока не вызывают.

### Проверки

Отдельная тестовая база `domsignal-p3a-db` (контейнер `postgres:16.10-bookworm`,
`127.0.0.1:55483`, БД `domsignal_p3a`); чужие БД фикстурами не очищались.

| Команда | Результат |
|---|---|
| `uv run python scripts/check.py --scope backend` | PASS — ruff, mypy (119 файлов), 321 unit/contract/ai тест |
| `uv run python scripts/check.py --scope contracts` | PASS — OpenAPI и сгенерированный TS без дрейфа, расширенная валидация `regions/` |
| `uv run python scripts/check.py --scope integration` | PASS — миграция до head и 177 PostgreSQL-тестов (11 новых) |
| `uv run python -m domsignal.tools.route_preview …` | Пять поведений на демо-доме: `uk_internal`, `municipality` через ПОС, `emergency_service` со 112, выбор диспетчера для двора, `unknown` |

Новые тесты: табличные маршруты (34 случая, включая видимость `verified`/`demo`/
`needs_verification`, исключение канала для `RU-MOW`, `stale` старше 180 дней,
переопределение правила нижним слоем и равноправные правила), ActionCard
(13 тестов, включая запрещённые формулировки по всем комбинациям маршрут ×
аудитория × источник), справочник и деградация (10 тестов), PostgreSQL
(11 тестов: миграция вверх/вниз с отказом при данных, профиль дома,
идемпотентность `seed_demo`, только текущее управление, CLI и `route_preview`).

Во время прогона предпросмотра нашлась и исправлена реальная ошибка CLI:
на однобайтовой консоли Windows печать карточки падала на символе «→»
(`UnicodeEncodeError`). Вывод обоих инструментов идёт через
`domsignal.tools.print_json` с явным UTF-8; есть регрессионный тест.

### Что проверено в справочнике

`verified` — только два канала: «Госуслуги. Решаем вместе» (по скриншотам
владельца с gosuslugi.ru от 20.09.2026, `source_url` пуст) и единый номер 112
(Федеральный закон от 30.12.2020 № 488-ФЗ). Всё остальное —
`needs_verification` и жителю не показывается: аварийная газовая служба 104,
«Госуслуги Дом», чат-бот ГИС ЖКХ, ГИС РТ «Народный контроль», ГЖИ РТ,
ресурсоснабжающие организации и региональный оператор ТКО Казани.
Проверенных муниципальных организаций Казани нет — муниципалитет наследует
федеральный слой. Решение — [ROUTING-DIRECTORY-2026-09-20](../decisions.md#routing-directory-2026-09-20).

### Остаток владельцу

1. **Точная ссылка входа в сценарий ПОС** — одна строка `url` у канала
   `pos_gosuslugi` в `regions/_federal/responsibility.yaml`. Пока `url` пуст,
   действие перехода показывается с `enabled: false` и причиной, в которой
   виден `entry_hint`.
2. По желанию — сверка ГИС РТ «Народный контроль» и «Госуслуги Дом»; после
   сверки достаточно сменить `verification.status` на `verified` с датой и
   источником, код не меняется.
3. Решение о `ticket_intake_enabled` для демо-домов. `has_active_connected_uk`
   в этом срезе означает «у дома есть действующий период управления
   (`HouseManagement`) на текущий момент», и `can_create_ticket` повторяет этот
   признак. `TicketService.ensure` дополнительно требует
   `ticket_intake_enabled`, а `seed_demo` его не включает: на демо-доме
   карточка показывает активное «Сообщить в УК», но фактическое создание
   заявки в следующем срезе вернёт «заявка не создана». Включить флаг в
   `seed_demo` значит изменить поведение всего демо-потока (каждый отчёт
   начнёт создавать Ticket) — это отдельное решение владельца, поэтому срез
   его не трогает. До решения P3b обязан перепроверять `ticket_intake_enabled`
   перед созданием и показывать причину, а не молча ничего не делать.

### Ограничения

Модель, эндпоинты, Signal Inbox, AppealDraft и групповая карточка в чат в срез
не входят. Сроки (`due_at`, вид срока, календарь) A-02 этим срезом не
затронуты. Нормативной проверки состава общего имущества конкретного дома нет:
`uk_default` помечен `needs_verification` и несёт честную формулировку
«типовое распределение».

## A-10/B-09 administrative onboarding — 19.09.2026

START clean `dev/b-experience=02bb61c`; END fetch retains `origin/main=3d4a095`
as an ancestor. No main merge or DEV-A writes. CompanyOnboardingRequest,
EmployeeInvitation and HouseManagementRequest are additive migration
`e107a3cff433` over `1c5baa831ec9`. Company approval creates company and first
hashed invitation atomically; active membership waits for normal A-10 MFA.
Existing employees reuse User, invitation reissue invalidates old first links,
staff assignments and last-admin protection serialize concurrent revocation.
Open tickets lose current assignment/acceptance while work/history remain.
House identity is an explicit platform choice; A-15 overlap/history remain intact.

Public `/company/apply`, Company Admin and Operator `/admin/`, and separate
metadata-only `/platform-admin/` are implemented. Server bootstrap controls
navigation and multiple-company selection. MAX management reuses A-07; operator
sees read-only status. Company suspension removes effective current authority.
Platform cannot read resident content merely through its platform role.

Current deterministic results: ruff, mypy (88 source files), 103 unit/contract,
166 PostgreSQL integration, OpenAPI/TS drift, 89 frontend tests, typecheck/build,
HTTP+PG+worker+restart and Docker persistence smoke PASS. Populated migration
test preserves earlier company/house/binding/credential/report/ticket/work rows
and refuses downgrade after onboarding data. The expanded platform marker test
also checks every platform mutation projection (20 administration tests PASS).
All **30 browser tests PASS** in Chrome in a single consolidated run, including
the administrative lifecycle, operator work and retained history after revoke.
Visual QA corrected the revoke event label (removed performer, not assigned)
and translated platform audit events. After that display-only change, all 89
frontend tests/typecheck/build and the full administrative browser flow PASS again.
Gitleaks staged scan and both diff checks PASS.

Before deployment, VPS backup
`/var/backups/domsignal/domsignal-20260919T205955851493Z.dump` was restored into
`domsignal_b09_restore_20260919`: all 29 public tables match full-row canonical
hashes/counts, including 3 reports/tickets, 1 work attempt, 7 observations and the
existing MAX binding. Previous deployed SHA is
`f861e973f0cb7a2dd4ba5f6ce0f56dee91589600`. The new image first migrated the restored
copy to `e107a3cff433`, passed Alembic drift and matched all 28 earlier data tables
after excluding only new nullable columns. Production then migrated successfully
and matched the same full-row hashes before live smoke. First deployed feature
SHA: `876d3fe1e22183f0c0433df9fce4fcad160e4524`; the display-only follow-up in this
checkpoint is deployed with its own exact SHA recorded by `/version` and
the final handoff, without a documentation hash-update loop.

**LIVE VERIFIED:** real HTTPS Chrome flow used public application → singleton
audited platform CLI identity → normal password change/TOTP → platform approval →
first admin invitation/registration/TOTP → company portal → operator invitation/
registration/TOTP → house request → explicit new-house approval → assignment →
operator view and reload showing exactly one house. No auth/permission fixtures
ran in production. Platform bootstrap denied the company admin with 403.
Three new dedicated identities have MFA; the existing human-owned employee and
MAX resident were not changed. Credentials/recovery codes are in a local ACL-protected
directory outside the repository; consumed invitation links and bootstrap password
exports were removed. No secrets are written in this document.

Isolated `LIVE ADMIN TEST 2026-09-19` company:
`6d0996eb-02d6-44b4-8975-3c1e47b1316e`; house
`cafb33aa-d182-426f-89d3-2da6c68b00cd`; management
`35a1411c-0162-4a86-9aa7-d788d1d58318`. One application, two accepted invitations,
one approved house request and one assignment; **zero real MAX groups added**.
The test scope remains available for review. Audited cleanup: platform Organizations
→ this exact LIVE ADMIN TEST company → enter cleanup reason → Suspend. This removes
effective employee/house authority and preserves approval/history; do not delete
the tenant/house or revoke the last administrator to simulate archiving.

Post-deploy `/ready`, all four entry points and public HTTPS return 200; API healthy,
worker running, test auth/seed false, failed jobs 0. Webhook without secret=401 and
authenticated empty body=422. Existing bot identity/subscription URL and all six
event types unchanged; one prior MAX binding remains active. Original 3 Reports,
3 Tickets, 1 WorkAttempt and 7 observations remain; no new resident content was
created by this live admin smoke. Source-file and API/worker log scan against five
actual configured production secrets found zero matches; env mode is 600.
VPS public self-connection stalled; external HTTPS and local Caddy TLS with the
unchanged hostname verified readiness instead. No DNS/TLS/MAX configuration changed.

**NOT LIVE VERIFIED:** invite expiry/replay/revoke races, multi-company switching,
last-admin denial, historical management switches, company suspension and actual
staff revoke were tested deterministically, not against retained live identities.
New MAX connection UI was fully verified with the deterministic A-07 provider;
no second live group was connected. Native mobile MAX and a new human resident
delivery/observation loop were not repeated. Parent roadmap tasks remain PARTIAL.

Roadmap mapping: A-10 onboarding/access slice implemented, parent PARTIAL for
limits/reservations/settings/second-region scope; B-09 administrative UI slice
implemented, parent PARTIAL for limits/quiet hours/auto-react/moderation;
A-07 existing connection API exposed in company UI; B-14 queue reused.
Exactly one recommended next DEV-B task: A-10/B-09 company house limits and
reservation accounting. It is not started by this slice.

## A-10 employee web-auth checkpoint — 19.09.2026

Owner DEV-B, branch `dev/b-experience`; START `f61b32a`, production before this
slice `6ac08e09d22a11836fc18a45cb65b594f67bbad4`. `origin/main=3d4a095` is an
ancestor; no main merge or DEV-A write. Historical MAX evidence below is retained.

**IMPLEMENTED IN BRANCH:** employee password/TOTP/recovery authentication,
operator create/reset-password/reset-mfa/revoke/status, constrained preauth,
server-side cookie AppSession with idle/absolute expiry/revocation, CSRF+Origin,
PostgreSQL bounded rate limit and security audit. Existing A-15 authority and
MAX resident authentication remain separate. Web Admin has restore/login/change/
enrollment/challenge/recovery/logout; manual Bearer entry removed. No public
registration, staff management or organization onboarding was added.

**Roadmap mapping:** A-10 employee identity/MFA/session-revoke slice only;
B-14 temporary entry/reload gap replaced; B-09 ordinary web entry prerequisite
only, not onboarding/settings. A-12 deployment/config/headers verification for
this release, not full task closure. A-10 and B-09 remain PARTIAL/open.

**Verification executed:** ruff, mypy (84 source files); 102 unit/contract;
89 frontend tests; typecheck/build; OpenAPI and generated TS drift; 29 browser
checks via `scripts/notification_smoke.py --browser` (employee + B-14 + resident
House Board + notification); real HTTP/PG/separate-worker/restart delivery smoke.
Employee PostgreSQL suite: 22 passed. Full PostgreSQL/migration suite: 145 passed
(including additive migration and credential-history downgrade guard). Final
Docker build/migration/restart smoke passed. DETERMINISTIC VERIFIED. AUTH-01…40 evidence mapping is in acceptance.md; these
are deterministic checks, not live MFA ownership. Browser regression exposed and
fixed recovery-mode state leakage across account switches; axe now loads a
same-origin test asset while production CSP remains enabled.

Secret scan: detect-secrets --no-verify over changed/new files; 21 candidates
reviewed as synthetic fixtures, existing local DB defaults, revision IDs and event
names; no production secret included. `git diff --check` passed. Crypto libraries:
argon2-cffi 25.1.0, PyOTP 2.10.0, cryptography 48.0.1, qrcode 8.2 (locked).

**DEPLOYED / infrastructure verified:** code and pushed release
`f861e973f0cb7a2dd4ba5f6ce0f56dee91589600` deployed via verified Git bundle/SSH.
Production-shaped restored DB upgraded first; Alembic check reports no drift.
Live DB then upgraded to `1c5baa831ec9`; all 20 domain/audit/delivery table full-row
contents still match the restored backup, with zero default credentials at migration.
Public `/ready`, `/admin/`, `/admin/login`, root and capabilities return 200.
Employee bootstrap returns login with Secure/HttpOnly/Lax cookie; missing CSRF
is 403; production test-session is 503. Admin-only CSP is present; resident root
has no frame restriction. API/DB healthy; worker running.

Existing notification provider GET is 200, accepted delivery desired/applied v12,
zero retries; failed worker jobs=0. Webhook missing secret is 401, valid secret
with invalid empty payload is 422. Subscription URL and six event types unchanged.
This is post-deploy health evidence, not a fresh human MAX product loop.

**Isolated employee / human gate completed:** existing scoped employee UUID
`763c4458-e474-4398-9bc8-16ef79077463` has one active LIVE TEST company_admin
membership, no Superadmin/MAX identity/resident grant; no authority expansion.
Backup `/var/backups/domsignal/domsignal-20260919T190532283380Z.dump` restored to
separate `domsignal_a10_restore_20260919`; exact full-row SHA-256 and counts match
across 20 domain/audit/delivery tables. Includes 2 Users, 1 resident membership,
3 Reports/Incidents/Tickets, 1 ChatBinding, 2 notifications, 7 observations.
Dedicated MFA key generated once on VPS into mode-600 env without printing;
protected env backup is present. MAX subscription read-only baseline retains
same URL and six update types. Exactly one credential was provisioned through the production CLI for this existing
User; login `live-test.operator`. Temporary password was returned only in the
operator output and is not stored in docs/git. The user completed password change
at 19:32:12 UTC and personally enrolled/verified TOTP at 19:32:44 UTC; no real MFA
enrollment was automated. Credential is active, `mfa_enabled=true`,
`password_change_required=false`.

**LIVE VERIFIED, 19.09.2026 19:38 UTC:** actual password/change/enroll/verify
requests returned 200. Exactly one server session has source
`employee_password_mfa`, created 19:32:44 UTC; after the user's page refresh its
`last_seen_at` advanced to 19:37:30 UTC with the same session ID and exactly one
`employee_auth.login_success` audit event. The user explicitly confirmed that
login persisted and the queue opened. Actual `/api/v1/auth/employee/session`,
`/api/v1/me` and scoped `/api/v1/tickets` requests returned 200 at 19:37:29 UTC.
Read-only MembershipService/TicketService checks resolve the same single
LIVE TEST company_admin grant, tenant `9f0306fa-9660-40ab-8527-f1e361d48d61`,
one house `6edbf50b-4bb4-4a74-a6fd-40351010802e`, three tickets. No authority was
added by authentication. All six employee security audit payloads contain only
`user_id`; configured-secret comparison against API/worker logs found zero
matches. Raw user passwords/TOTP/recovery codes were not retrieved for inspection.

Post-human-gate health: `/ready` and capabilities 200, test auth false;
webhook without secret 401, authenticated empty payload 422; existing MAX
subscription URL/six event types unchanged, existing provider message GET 200.
Notification remains accepted at desired/applied v12 with zero retries;
failed jobs=0. API healthy, runtime build remains `f861e97`.

**NOT LIVE VERIFIED:** recovery-code login, logout/relogin, credential reset,
MFA reset, credential/membership revoke, concurrent MFA and restart survival
were verified deterministically, not repeated against the human-owned production
account. No new full human MAX product loop was requested after this auth deploy;
existing live evidence and post-deploy provider/webhook health are distinguished.

Configured-secret scan on VPS compared all tracked files against five actual
production secret values: zero matches; env mode 600 confirmed. Local scan findings
were synthetic/default constants, not production credentials.

**Next:** human MFA ownership, scoped queue and reload gate is complete. Live
revoke remains deterministic-only to preserve the user's newly enrolled account;
resident MAX identity was not revoked. Do not start onboarding UI. Recommended later
DEV-B task: A-10/B-09 approved company application/invitation onboarding slice,
only under a separate explicit task.

## Latest product checkpoint — 18:16 UTC

The full group command created exactly one Report/Incident/Ticket at 18:05 UTC,
with the real resident as author and the approved test-house binding. Scoped CLI
TicketService commands resumed the category-other clarification, accepted and
started T-1, then created attempt 1 at 18:06:53 UTC; verification_pending v5.
The work description explicitly says this is a test, not an actual repair.

Production worker delivery accepted at 18:06:54 UTC, one send, no retries/errors:
`mid.00000000066d71cf01a0bad98cf55266`. Provider GET confirms the real bot, correct
personal recipient and open_app/resolved/unresolved keyboard. Earlier accepted
intent was superseded before sending. User screenshots plus real API reads verify
the board, T-1 and attempt 1 UI. Exact IDs/evidence are in MAX_LIVE_SMOKE.md.

LIVE launch at 18:11:43 UTC: actual notification click → validated auth/max →
notification-launch 200 → exact Incident/attempt card, confirmed by the user.
LIVE callback at 18:13:13 UTC: resolved observation revision 1 by the real resident
closed the same T-1 (v6). Callback and answer jobs succeeded once. Reconciliation
preserved the provider message ID; provider GET confirms closed text and removed
callback buttons, desired/applied v6, zero retries.

LIVE Mini App correction at 18:15:25 UTC: observations POST 200 saved unresolved
revision 2 correcting revision 1, reopened the same T-1 to in_progress v7 and marked
attempt 1 for rework. Same provider message updated to «Проблема возвращена в работу»,
confirmed by real GET, desired/applied v7, one send plus two edits, zero retries.
Real resident retains only one house membership and no staff/platform role; distinct
existing CLI identity cannot resolve the resident launch ref. No new domain objects.

User also confirmed reading «Ваш ответ учтён. Проблема возвращена в работу.» in
the personal MAX notification. Final reconciled text is now confirmed in the real
client as well as by provider GET; no API read-receipt/push claim is inferred.

No required client/organizer action remains for this Web smoke. Native mobile and
additional replay/stale/retry/restart/multi-resident scenarios remain unverified live.
The editable original is the bot's personal notification, not the human group post.
Code remains tested/deployed 6ac08e0; latest changes are evidence docs only. Fixture
stays active for review; revoke is available, delete-empty refuses retained history.
Historical pending notes below are superseded.

## Current Mini App checkpoint

START/own origin `53ee8b5`; fetched main is already an ancestor. DEV-A remote
handoff read without writes. MAX Web operator launch produced auth/max 200 and
me 200 at 17:28:29 UTC, with canonical user and verified timestamp committed.
The real MAX identity matches the previously accepted bot_started destination.
Production contained zero houses/memberships: empty board was correct access.
Full sanitized evidence and exact IDs: [MAX live smoke](../MAX_LIVE_SMOKE.md).

Existing HMAC/age validation matches current official MAX documentation and needs
no bypass. Added `tools.live_fixture` singleton CLI with validated identity
precondition, ManagementService, explicit ResidentMembership, no employee/platform
role, operator audit and safe revoke/delete-empty. Deterministic PG tests exercise
scope isolation, idempotency, invalid identity/other owner rejection, revocation
and refusal to delete dependent rows. Added wrong-token/future-date/signed selector
auth tests. OpenAPI/TS unchanged. This is not a main merge.

Deployed code `d4b6776` via verified Git bundle (VPS has no GitHub credential),
production Docker rebuild and healthy API/DB. The CLI created exactly one test
scope at 17:43:43 UTC; operator audit retains IDs/reason. Production service reads
return only that house with resident permissions, empty board succeeds, unknown
house is masked 404. No organization membership, Report, Ticket or ChatBinding.
Public ready 200, anonymous me 401 and disabled test-session 503; no new session
issued by operator checks. Original real MAX session expired before provisioning.

Checks PASS: 68 targeted PG/auth/production tests; backend 100 unit/contract,
ruff/mypy 78 files, OpenAPI/TS drift, region validation, frontend production build,
local + production Docker builds, Gitleaks staged scan and diff check. Existing
Starlette/httpx/anyio deprecation notices only; no checks suppressed.

Operator completed reopening at 17:44:49 UTC and separate MAX-menu reload at
17:47:34 UTC. Each produced real auth/max, me and exact test-house board GET 200;
same canonical User and resident scope. Operator confirmed the board remained
visible. Mini App authentication/context is now LIVE VERIFIED for MAX Web.
Tool browser inventory did not expose the user's MAX tab; visual confirmation
is human evidence, not an automated browser fixture. Native mobile is untested.

Provider me exposes no group-add switch. Current official docs deprecate GET/chats
since June 2026, so its empty response proves neither absence of groups nor group
disablement. Setting is organizer-owned and currently UNKNOWN. Requested actual
addition/admin assignment in an existing test group. All later group/product loop
steps remain pending; no synthetic production webhook/identity or binding used.

## Current production checkpoint

### Live group continuation

Real bot_added accepted at 17:51:14 UTC; MAXChat `-79142681723640` (`TEST_MAX`)
persisted. Provider verifies bot admin + read_all_messages, connector is current
admin/owner. Group capability LIVE VERIFIED, organizer gate resolved.
Requests/bindings remain zero because installation preceded A-07 correlation.
Added live_connection prepare/approve CLI, confined to audited singleton scope,
using existing initiate/approve with a separate scoped CLI service principal (no
MAX identity/session/platform role). Real user's resident permissions unchanged.
Revoke also disables the operator grant. Correlated bot_started/re-add remains a
MAX-client step; no synthetic event, backdate, or direct binding state mutation.
Deterministic coverage tests missing event/correlation, no client/staff escalation,
fresh-rights rejection, correct activation and scope revocation. Deployment and
subsequent live evidence will be recorded after execution. Checks PASS: 41 targeted
PG tests (38 A-07, 2 fixture, 1 operator flow), 100 unit/contract, ruff/mypy 79
source files, OpenAPI/TS drift, full Docker production build, Gitleaks and diff check.

Code `6ac08e0` pushed/deployed, API/DB healthy; 17:59 UTC CLI prepare created
request `f650a92a-daf8-4a0e-a83a-dc1c64d25d83` for the test management, pinned to
TEST_MAX. Separate CLI User has only test-company admin membership and no MAX
identity/platform role/session; real resident me unchanged. Request is `created`
until genuine token-bearing bot_started; expires at 18:14 UTC. Requested opening
the one-time link in MAX. Link is not persisted in docs/audit; next step is genuine
correlated re-add, fresh rights verification and service approval, then /report.

Real bot_started at 17:59:48 UTC claimed this request to MAX user 294889720.
Guarded self-leave API for the pinned, unbound test chat returned 200/success=true;
operator receipt saved. No immediate bot_removed webhook observed. User was asked
to re-add the bot/admin in TEST_MAX, so A-07 can observe addition after claim.
No direct candidate assignment, fake event or binding bypass used.

Re-add arrived at 18:01:49 UTC and matched the claimed request. Worker first saw
missing admin rights (user was still assigning them); explicit approval rechecked
fresh provider rights and company authority successfully. Binding
`7786a1b3-b224-48ff-8938-800d79566f6b` ACTIVE v1 at 18:02:51 UTC; request completed.
Real chat/management/house/tenant mapping and resident OperationContext verified.
Requested one genuine /report in TEST_MAX; Report/Ticket/product notification
remain pending until that actual event. Details in MAX_LIVE_SMOKE.

Resumed START ref and own origin ref:
`b986aeda249316d75ad2a2c9620a803033e96a69`; origin/main already an ancestor.
No main merge and no writes to DEV-A. Existing project SSH key passes BatchMode
and strict host verification; the previous SSH access blocker is resolved.

VPS `domsignal-prod`, Ubuntu 24.04.4, 4 vCPU/7.8 GiB RAM/55 GiB disk, now runs
Docker 29.8.1 + Compose 5.5.1 at `/opt/domsignal`. Missing host DNS resolvers and
broken Ubuntu mirror fixed; NTP synchronized. UFW allows TCP 22/80/443;
PostgreSQL has no published port and API is loopback-only. Fresh secrets stay in
mode-600 `deploy/.env.production`; `.dockerignore` now excludes nested env files.

**DEPLOYED:** Caddy/API/worker/PostgreSQL; migrations completed, demo seed disabled,
API and DB healthy; worker process and DB reachable, no restart loops.
Application source remains the previously deployed code; this checkpoint adds a
Caddy Docker network alias and docs. Exact deployed checkpoint SHA is stored as
BUILD_COMMIT in the VPS environment file. No test data copied or generated.

**DETERMINISTIC VERIFIED:** Compose quiet validation/fail-closed assertions;
17 targeted production/subscription/MAX provider tests pass. Public `/ready` and
resident `/` return 200; external webhook without secret 401 and with production
secret plus `{}` 422. Test auth and demo seed remain disabled.
Controlled replay of the exact real event identity returns duplicate=true,
job_id=null; inbox count stays one and no jobs are added. This is operator replay,
not a second MAX-originated delivery.

**LIVE VERIFIED:** trusted public TLS (Let's Encrypt YE1, matching SAN and verified
chain); real production MAX GET `/me` identity
402577719 / t480_hakaton_max_bot / is_bot=true. Safe utility inspected empty
subscriptions, registered the expected `/max/webhook` URL, and confirmed exactly
one subscription with all six documented event types.

The operator's real Start produced authenticated, typed, persisted bot_started at
2026-09-18 21:39:42.616290 UTC. MAX's active dialog data identified the actual
recipient and reconstructed the exact event hash for duplicate verification.
Production HttpMaxMessagingProvider sent the requested plain-text confirmation;
MAX accepted `mid.00000000066d71cf01a0b678f3ea6fad`, and GET read-back verified
ID/text/recipient. No reading/push-display claim.

Acceptance is persisted in the real inbox receipt's `payload.bootstrap_smoke`;
a pre-send claim prevents accidental resend. This operational record does not
create or verify a Ticket NotificationDelivery or app User. Users, tickets, work
attempts, deliveries and jobs remain empty. API/worker restart retained event,
accepted message ID and subscription; readiness, TLS preflight and worker process/DB pass.

**FIXES:** cloud ingress was opened by the operator. VPS public-IP loopback remains
unavailable, so Caddy gets PUBLIC_DOMAIN as a Docker network alias. Container
HTTPS preflight uses the real Caddy certificate; separate external probes confirm
actual public reachability. No TLS bypass, token rotation or unrelated services.

**PENDING ORGANIZER ACTION:** Mini App binding; group permission if disabled
(capability currently unverified; GET chats empty, not presumed disabled/enabled).
Resident entry for organizers is `https://domsignal.176-108-244-168.sslip.io/`;
HTTPS/HTML are verified. Mini App binding/initData/client behavior are not.
Callbacks require a genuine product Ticket/WorkAttempt; no artificial smoke Ticket.
No further action is requested from the operator now. Product scenarios remain pending.

Full evidence and continuation boundary: [MAX live smoke](../MAX_LIVE_SMOKE.md).

## Delivery result and roadmap mapping

START HEAD/origin/dev/b-experience `95a6c24`, origin/main `3d4a095`; clean tree.
START fetch, own fast-forward and main sync completed, already up to date. DEV-A
status read from origin/dev/a-core; no writes/push there. Final commit/push evidence
belongs in the session report, without a follow-up hash-only commit. Main requires
the existing second-developer review and current CI; this task does not merge it.
END fetch confirms unchanged main and own remote refs. Required documentation,
local links, conflict markers and final diff whitespace checks pass.

| Existing task | Implemented part; remaining boundary |
|---|---|
| A-05 | A-16 intent consumer, durable per-recipient delivery, leases/recovery/retry/unknown and dialog throttling |
| B-03 | Production send/edit/answer provider and authenticated callback ingress; live acceptance pending |
| B-06 | Personal work-card reconciliation and safe callbacks; group cards/quiet hours remain outside slice |
| B-07 | Opaque personal open_app/start_param and existing Mini App routing; QR/sharing/group transition remain outside slice |
| B-08 | Existing work result/observation connected to personal messages; remaining history/reminder/escalation scope unchanged |
| A-09 | Reused delivery access/staleness safeguards only; reminder scheduler and escalation remain PLANNED |

No new epic, broker, business outbox, lifecycle, admin screen, A-10 or AI work.

## Durable delivery and authorization

WorkerRunner consumes existing `ticket.notification_intent.v1`: SKIP LOCKED claim,
typed payload + stored TicketEvent validation, unique fan-out, reconcile marks and
outbox processed commit together. Candidates are distinct authors of own Reports
for the Incident, then MembershipService/AccessPolicy resident access, current
management, same Ticket and confirmed numeric MAX identity are checked. No house
broadcast/subscriber model is invented. Legacy max_user_id alone does not qualify:
additive max_identity_verified_at is set only by existing validated initData auth.

NotificationDelivery uniquely identifies (outbox, recipient, channel); it stores
Ticket/attempt, random ref, destination, provider mid, desired/applied version,
attempt/retry counters, timestamps, sanitized error and fenced lease. States:
pending, processing, accepted, retry_wait, unknown, failed, superseded, skipped.
`accepted` means validated MAX API response with a persisted mid, never read/push.

Fresh authorization/render runs again after the durable claim immediately before
send/edit/answer, with no domain lock or DB transaction held during HTTP. Changed
management/identity or revoked access suppresses delivery. An old unsent work
attempt becomes superseded. No global User revocation field exists in A-15;
resident access/current management are the available revocation boundary. A change
after the final check cannot atomically retract an in-flight external request.

Only accepted and work_reported produce new personal messages. Other A-16 intents
reconcile already accepted work cards against current ResidentWorkStatus. Renderer
uses controlled category, explicitly public work description and own observation;
never private Report/location, internal cancellation reason or other users' data.
Work verification includes «Открыть и проверить», «Исправлено», «Проблема осталась».
After observation/rework/new attempt, callbacks disappear from rendered cards.

Opaque random `w_…` ref has no embedded IDs or authority. GET
`/api/v1/notification-launch/{ref}` requires an authenticated intended recipient,
current access/management/identity and own Report. Other actors receive masked 404.
Bridge reads start_param, resolver selects the existing Incident Detail/current
WorkAttempt, stale launch shows current work with a notice and focus. Test URL
override requires non-production + server test_auth. No new UI lifecycle.

Webhook secret verification and bounded parser precede durable callback inbox/job.
Callback actor, original provider mid and accepted delivery must match; then the
same A-16 observe service and lock order create ResultObservation. Same event is
deduplicated; another callback ID after one's answer cannot overwrite it. First
historical answer may be recorded with applied_to_current=false, preserving A-16;
it cannot change the newer attempt. Unresolved reopens the same Ticket. Corrections
remain possible through existing Mini App actions. Observation + durable answer
job commit together; provider edit/answer failure cannot roll back business state.
Existing A-16 intents reconcile messages after callback AND Mini App observations.

Production HttpMaxMessagingProvider reuses A-07 MaxHttpClient and existing
base URL/token/timeout/TLS boundary. MAX_BOT_USERNAME is additive configuration,
passed through production Compose; missing value is a terminal configuration
failure, not a fake successful send. POST /messages validates recipient and mid;
PUT /messages and POST /answers require strict boolean success=true. Recording
providers live in tests and require explicit injection; no production fake mode.

Transient rejected sends (429/connect failure) and edit/answer errors use durable
backoff 2/4/8/16 seconds, max five calls per operation/version; Retry-After is
respected up to one hour. Permanent errors stop. Ambiguous POST timeout/5xx/invalid
response or expired send lease becomes unknown and is never blindly resent.
Known mids are retained on edit failure. PostgreSQL destination gate covers all
three operations, with 500ms minimum gap and 90s leases; dialogs are independent.
No exactly-once external send guarantee is asserted.

## Delivery verification actually executed

Dedicated own PostgreSQL 16 container `domsignal-nd-db`, loopback 55478, databases
`domsignal` (integration) and `nd_smoke` (HTTP/browser); existing test containers and
production data untouched. Test-only HTTP provider uses a loopback port and a
synthetic credential; no real MAX token/webhook was used. No dependency changes.

| Command actually executed | Result |
|---|---|
| `uv run ruff format` on explicit changed files; `uv run ruff check src tests scripts migrations`; `uv run mypy src/domsignal` | PASS, 76 source files; final targeted rerun after defensive renderer/ref checks |
| `uv run python scripts/export_openapi.py`; `npm --prefix miniapp run api:generate` | PASS, additive resolver producer/OpenAPI/TS synchronized |
| `uv run python scripts/check.py --scope all` with isolated DATABASE_URL | PASS: 75 unit/contract, 89 frontend unit/component, 119 real PG integration (228.62s), ruff/mypy, TS/typecheck/build and generated drift checks, migration upgrade |
| `uv run pytest tests/contract/test_max_messaging.py -q` | PASS, 22 provider tests: exact wire, strict success, errors/unknown, real composition |
| `uv run pytest tests/integration/test_notifications.py -q` | PASS, 20 integration tests, also included in full gate; rerun after final defensive backend changes |
| `uv run python scripts/notification_smoke.py --browser` with APP_ENV=test, ND_FIXTURES=1, separate migrated nd_smoke DB | PASS HTTP + PG + separate worker/provider processes + actual restart; all 28 browser tests (8 B-02, 19 B-14, 1 ND), 1.2m |
| `uv run python scripts/notification_smoke.py` after readiness/answer assertions | PASS, callback answer observed; same Ticket, two attempts, two observations, two unique mids persist after API/worker restart |
| `uv run python scripts/docker_smoke.py --project domsignal-smoke-nd --api-port 18090` | PASS, clean build/migration/API+worker, Incident persisted after API restart; own smoke project and volume removed |
| `git diff --check` | PASS, no whitespace errors |

ND-01…ND-30 are PASS assertions, not thirty separate test functions: full mapping
is in [acceptance](../../scenarios/acceptance.md#nd--personal-max-delivery).
Kill-test proves unsent #1 superseded, #2 actionable and fabricated old callback
inert; an accepted historical callback is separately checked against newer work.
Two concurrent consumers/delivery workers preserve unique logical fan-out. Access
revocation is also injected between claim and final preflight; no send follows.
Provider failure tests acquire Incident NOWAIT from another connection during HTTP
to verify no domain lock is retained, and exercise the five-call retry bound.

Migration `2aea407269aa` upgrades populated A-16 `20260918_0004` and preserves
Incident/Ticket/attempt/observation/event/outbox history; legacy identity stays
unconfirmed and no fake delivery is backfilled. Empty-slice downgrade/upgrade
passes; populated delivery/verified identity downgrade is explicitly guarded:
restore a pre-delivery backup rather than discard durable external state.

Latest HTTP restart evidence: Ticket `00eefcd0-90be-40f1-a7ba-d64d849e1c34`,
Incident `3e3f438f-8b5f-42f2-8bad-4dd2a4c8879b`, two attempts/two observations,
two mids prefixed `mid.fixture-c7b861625bd447c29a1c0ec91f3232ef-`, with accepted
intent superseded before send. Browser screenshot reviewed at
`miniapp/test-results/nd-resident.png` (ignored local artifact): existing detail,
public work result, own unresolved feedback and current state; no overflow.

Early test runs exposed fixture settings shared across tests and an older migration
snapshot treating the new null identity field as old data; isolated settings and
explicit additive-column exclusion corrected those issues. Smoke retries exposed
reused fake mids and Windows subprocess redirection; per-run mids and direct base
interpreter handles made restart deterministic. Final runs above pass; no tests
disabled to obtain a green result. Existing dependency warnings remain unchanged.

## Official MAX boundary and handoff

Official API checked on 18.09.2026: [send](https://dev.max.ru/docs-api/methods/POST/messages),
[edit](https://dev.max.ru/docs-api/methods/PUT/messages),
[answer](https://dev.max.ru/docs-api/methods/POST/answers),
[Mini Apps](https://dev.max.ru/docs/webapps/introduction),
[Bridge](https://dev.max.ru/docs/webapps/bridge). Current open_app uses web_app +
payload; attached app/client behavior still needs live validation. Current answers
schema exposes message, not a notification field. success=false at HTTP 200 is
failure. Personal dialog guidance is at most two operations/second. Keyboard DM
edits have no documented age limit; other messages have seven days. No documented
POST idempotency guarantee, so uncertain send is unknown. Actual push/read and
mobile/web behavior cannot be inferred from provider acceptance.

Production code is IMPLEMENTED, deterministic integration VERIFIED; real MAX is
NOT LIVE VERIFIED / PENDING TOKEN. Updated unchecked live list is
[MAX_LIVE_SMOKE](../MAX_LIVE_SMOKE.md).
Main/review/CI policy unchanged; no A-10 or next-task work started.

Exactly one recommended next DEV-B task: **B-01 — execute the updated live MAX
delivery checklist with an explicitly allowed token and attached Mini App.**

## Historical B-14 handoff

Updated: 2026-09-18 (B-14)
Branch: dev/b-experience
Current task: B-14 — employee Ticket UI + resident verification
State: PASS / IMPLEMENTED IN BRANCH; NOT MERGED TO MAIN; NOT LIVE VERIFIED

## B-14 result

Explicit owner request supersedes the earlier “B-14 not started” handoffs.
START HEAD/origin/dev/b-experience: `194d91a`; origin/main: `3d4a095`.
Tree was clean. START/END fetch succeeded, refs unchanged; START own ff/main
sync already up to date. DEV-A status read from origin/dev/a-core, no writes there.
Final SHA/push result is in the session report, not a follow-up hash-only commit.
No automatic main merge: second-developer review/current remote CI remain required.

One existing Vite/npm project, two HTML entries: resident `/` and employee
`/admin/`. Employee entry loads no MAX UI/Bridge/CDN; one sidebar item “Заявки”.
Queue uses backend-scoped house pages (20 each), server order/status/assignee
filters, real totals and pagination; detail/URL/back/reload use authoritative reads.
Address comes from /me, title/category/location/counts from authorized Incident API.
No fabricated SLA or priority. All permitted houses appear without loading foreign
scope and filtering it away in React. No Superadmin/onboarding/settings/chat UI.

Detail renders number, state, action panel, assignee, incident, separate attempts,
current-observation summary, paginated history and published typed deadlines.
Only allowed_actions expose implemented commands; unknown values fail safely,
disabled descriptors remain disabled and show reason. Canonical accept performs
claim; no invented claim endpoint. assign gets only scoped paginated candidates,
requires a reason and cannot submit an arbitrary employee. Operator has no assign.
Report form explicitly publishes its text and waits for resident verification.
Existing clarify/wait-external/resume/cancel adapters use required reasons; deadline
editing/calculation is outside this slice. Native dialog adds explicit focus trap,
Escape/return focus, labels and safe field errors.

Existing Incident Detail adds public work-status/latest attempt and attempt-scoped
observations. Confirmation is a resident observation, not an official acceptance.
Late objection reopens the same Ticket; employee “В работе” includes it. Conflicting
observations require another check, not majority voting. A-16 actually records stale
attempt responses as historical with applied_to_current=false; UI honors that source
of truth and refreshes the current attempt. It does not claim a backend HTTP reject.

No new workflow, migrations or HTTP endpoints. Minimal additive internal read DTO:
assignee_name; AttemptView.performer_name/resolved_count/unresolved_count. Counts
use existing backend current-observation revisions, not a frontend decision rule.
Separate ResidentWorkStatus/AttemptPublic remain unchanged, internal fields are
physically absent. Producer/OpenAPI/TS regenerated together; privacy assertions
cover the additions. Published summaries agree in detail and attempt history.

Mutations retain the original body/key for an uncertain retry, prevent double
submit, then await GET. Failed GET after acknowledged POST retries only GET.
No optimistic lifecycle. 403/409 losing claim refetches the winner; 401/403/404
remove cached private content. 422 attaches safe validation to fields; 429/5xx/
network use retryable. History refreshes on version change. No raw error/stack/IDs.
Shared useResource preserves cancellation/out-of-order guards and exposes awaited
read-after-write. No tokens or private responses persist in browser storage.

## B-14 actual commands and evidence

Dedicated PostgreSQL 16.10 container `domsignal-b14-db`, loopback 55477;
`b14_tests` for pytest, `b14_browser` for browser (never concurrently shared).
API 8030 in APP_ENV=test/MAX_TRANSPORT=off. Python 3.12.14, Node 24.19.0,
existing ignored npm launcher; no dependency/lock updates. Browser fixtures require
APP_ENV=test + B14_BROWSER_FIXTURES=1, are CLI-only, and never truncate shared data.
Instructions: [miniapp README](../../miniapp/README.md#b-14--employee-entry-и-browser-fixtures).

| Command actually executed | Final result |
|---|---|
| `uv run ruff format` on explicit changed Python files; `uv run ruff check src tests scripts migrations` | PASS; fixture unused import/formatting corrected |
| `uv run mypy src/domsignal` | PASS, 69 source files |
| `uv run python scripts/export_openapi.py`; `npm --prefix miniapp run api:generate` | PASS, generated OpenAPI/TS |
| `uv run python scripts/check.py --scope frontend`; final targeted typecheck, 15 B-14 component tests and build after dialog feedback cleanup | PASS, 88 frontend tests (73 existing + 15 B-14), final targeted 15/15, production build for both entries |
| `uv run python scripts/check.py --scope all` | PASS: ruff/mypy, 53 unit/contract, 88 frontend, build, OpenAPI/region/TS drift, alembic upgrade, 98 real PG integration (230.95s); A-01/A-15/A-07/A-16 regressions included |
| `uv run alembic upgrade head`; `uv run python -m domsignal.tools.seed_demo`; `uv run python -m domsignal.tools.seed_tickets` | PASS in separate browser DB; no migration added |
| `npm --prefix miniapp run test:browser` with base URL 8030, Chrome and fixture gates | Final PASS 27 (19 B-14 + all 8 B-02), 1.8m; real HTTP/PG vertical path, access/revoke/switch, concurrent claim, late/stale/conflict, idempotent retry, reload, field 422, axe and responsive/themes |
| `uv run python scripts/docker_smoke.py --project domsignal-smoke-b14 --api-port 18089` | PASS clean image/build/PG/migrations/API+worker, persisted Incident after API restart; own smoke project/volume cleaned by script |
| `git diff --check`; repository required files/conflict markers/local documentation links | PASS before commit |

The full backend/PG gate and Docker smoke preceded the final dialog feedback
polish. The final frontend build, targeted component checks and all 27 browser
tests ran after that polish; backend and packaging files were unchanged.

Full vertical scenario: actual Report creates Incident+one Ticket → employee
queue/detail accepts/starts/reports attempt 1 → resident unresolved → same Ticket
returns to work → new attempt 2 → resident resolved → closed → both UI reload.
Direct PostgreSQL snapshot matches HTTP ID/version/status, exactly 2 attempts and
2 observations. Commit-with-lost-response test returns one WorkAttempt after retry.
New backend regression verifies current revision counts, names and history/detail
agreement. Full [UI-TK-01…28 matrix](../../scenarios/acceptance.md#b-14--ui-tk-evidence).

An additional browser regression verifies an in-dialog 409 notice, retained text,
disabled outdated submit and no duplicate WorkAttempt. Final visual review also
waits for loaded queue rows before checking responsive overflow.

First browser run exposed Tab escaping the dialog to browser chrome; explicit
focus trap fixed it. Repeated full run exposed duplicate synthetic address in the
switch fixture; unique isolated fixture addresses fixed repeatability. Final full
27/27 rerun passed, no skipped/disabled checks. Screenshots of employee/resident,
390/768/1024/1366 admin and 320 light/dark resident generated; visual QA performed.
Existing Starlette/httpx deprecation and browser color environment notices remain.

## B-14 limitations and next step

PASS applies to the authorized UI/workflow slice, not production identity or live MAX.
Production admin accepts an existing bearer session in memory and requires sign-in
again after reload; only explicitly enabled non-production test auth offers named
fixtures. A complete employee login provider/MFA is still A-10/B-09, not invented MAX
OAuth. Browser reload lifecycle evidence uses real gated test-session identities.
No live MAX token/chat/callback/notification, real mobile MAX client, public TLS or
external official acceptance was verified. Outbox delivery unchanged. Existing
manual report/group-off/B-02 regressions pass; semantic matching remains outside scope.
Queue composes per-house pages because no cross-house queue endpoint exists; no
claim of large-tenant performance or server-side global sorting. Deadline editor,
photos, employee/resident messaging, Superadmin and onboarding are excluded.

One recommended next DEV-B task after review/merge: A-10 employee web authentication
for this cabinet. Do not start it in this session. Current integration step is DEV-A
review and green merge-result CI; main stays unchanged.

## Previous A-16 handoff — historical evidence

Updated: 2026-09-18 (A-16 backend)
Branch: dev/b-experience
Current task: A-16 — Ticket backend
State: PASS / IMPLEMENTED IN BRANCH; NOT MERGED; NOT LIVE VERIFIED

## A-16 result and boundaries

Owner authorization: A16_TICKET_BACKEND_CODEX.md, iterations 1–2 agreed;
the earlier docs-only prohibition below is historical and superseded for A-16.
Start HEAD/origin/dev/b-experience `0bbe6a4`; origin/main `3d4a095`.
Fresh refs fetched at START and END; own ff/main sync at START already up to date;
END refs unchanged. DEV-A handoff read from origin/dev/a-core; no AI/DEV-A writes.
Initial working tree clean; no unrelated WIP to move/stash. IMPLEMENTATION_CONTEXT
is intentionally unchanged: its verified-main table must not describe branch-only work.
Final commit/push SHA is reported in the final response, without a hash-only follow-up commit.

Implemented models: Ticket, WorkAttempt, ResultObservation, TicketEvent,
TicketDeadline; additive migration `20260918_0004`. No duplicated tenant source:
Ticket → original Incident house/management via composite FK → HouseManagement.
Partial unique active Ticket per Incident includes all six nonterminal statuses.
Composite FK checks latest attempt belongs to Ticket; attempt numbers unique per
Ticket; global DB identity number rendered `T-N`, stable with permitted gaps.
Scope, creation authorship and number immutable; attempt identity/report immutable,
rework only false→true; observations/events/deadlines append-only. Downgrade fails
with new history/config instead of deleting it. No historical backfill/intents.

Common ReportService.create_in_context calls ensure inside its transaction after
authorized Report persistence, including A-07 manual group intake. Flag
HouseManagement.ticket_intake_enabled defaults false; explicit test/demo enabling
does not verify a real organization. Existing/manual disabled path unchanged.
One active responsible → assignee while new; several/none → house queue, null
assignee; unknown category other → needs_clarification. Company admin sees reserve
and revoked-assignee tasks. Reassignment clears acceptance; work must be accepted
personally, preserving attempt snapshots of the previous employee.

Central core transitions and service authorization implement new→accepted→
in_progress→verification_pending→closed, clarification/external waiting/resume,
reasoned cancellation. Work report is an event and new attempt. No employee close,
silent/timeout close or external registration. Resident needs current basis and own
Report; canonical User identity cannot verify its own performed/reported attempt.
Resolved closes only without current objections and without rework. Late unresolved
reopens the same latest Ticket; rework is permanent on that attempt. Correction
appends a server revision; old positive answers cannot close without a new attempt.
Old/cancelled/superseded attempts remain historical, and response flags say whether
the observation affected current work. Conflicting opinions remain visible.

House SHARE → Incident FOR UPDATE is the common write lock order, including
absence/ensure/reopen. Expected version guards staff commands; resident observations
are serialized without rejecting a valid late answer for a changed Ticket.version.
Existing idempotency_records and ReliabilityRepository are reused; report intake
adds an advisory transaction lock for same-key concurrency. Ticket receipts contain
effect IDs/version, not private snapshots. Replay rechecks access/ownership and
returns current state plus original effect_version/replayed. Same key/different body
is a defined 409; revoke cannot replay old success. Internal DB uniqueness supplements
the serialized decisions rather than serving as the normal conflict handler.

HTTP/DTO handoff: [A-16.1 contract](../CONTRACTS.md#a-161-http-и-handoff-b-14).
Staff list/detail/assignee lookup, assign/accept/start/clarify/wait-external/resume/
cancel/work-attempts/deadlines, paginated events/attempts/observations/deadlines;
resident work-status, authorized observation POST and own observation history.
Existing Bearer/AccessPolicy/OperationContext; 404 foreign scope, 403 action,
409 transition/version/key, mandatory Idempotency-Key; bounded pagination/totals.
Separate ResidentWorkStatus allowlist excludes employees, service notes, other
comments/reports and agreement references. TicketAction does not change B-00 actions.
C0.1 plus additive A-16.1; app/OpenAPI version remains 0.1.0; generated TS updated
only by npm run api:generate. Test-session enum adds only named a16-* demo aliases;
the existing production prohibition remains enforced.

Deadline facts separate response/completion/next_update and internal/agreed/normative;
anchor references a same-Ticket event/time, due may be null; changes preserve revision,
author and reason. Agreement requires recorded source/time (staff attestation, not
independent external verification). Existing region rule is demo with due_at=null:
normative HTTP creation is unavailable until verified A-02 applicability exists.
No clock pause for waiting_external, universal repair deadline or SLA calculator.

Each accepted change persists state + event + existing OutboxMessage in one
transaction; unique dedupe_key ties intent to event. Typed safe references, context,
version and audience only; no comment/auth/token copies. Kind
ticket.notification_intent.v1 stays pending, with no registered delivery handler.
Work_reported/to_status records both report and pending verification. Future sender
must recheck recipient/scope/management/binding and latest state, never broadcast to
all house chats or send a stale fixed result after reopen. No SENT/READ/exactly-once claim.

## A-16 actual verification evidence

Dedicated PostgreSQL 16.10 container `domsignal-a16-db`, host port 55476; final suite
DB `a16_final`, separate network/browser DB `a16_smoke`. Existing databases untouched.
Local Python 3.12.14, Node 24.19.0 (within declared 24.x range); ignored local npm
launcher selects bundled Node, dependency/lock changes not required. Docker uses
the existing pinned Node 24.21.0/Python 3.12.11 images. MAX off outside explicit
A-07 fake-provider tests; no live token/webhook/provider or AI calls.

| Actual command / check | Result |
|---|---|
| `git fetch origin`; `git merge --ff-only origin/dev/b-experience`; `git merge --no-edit origin/main` | PASS; START sync already up to date; END fetch same refs |
| `uv run alembic revision --autogenerate -m 'A16 ticket work and resident verification' --rev-id 20260918_0004` | Draft generated, reviewed; dependency order/FK cycle/downgrade guard/history triggers hardened |
| `uv run alembic upgrade head`; `uv run alembic check` | PASS clean PostgreSQL; no model drift; also exercised in migration tests |
| `uv run pytest tests/integration/test_tickets.py -x -q` and subsequent targeted added scenarios | Initial 23 PASS; final expanded file 31 PASS in full suite. A new test initially missed an import; fixed before final run |
| `uv run pytest tests/integration/test_ticket_migration.py -x -q` | PASS populated A-07 preservation, repeated upgrade, drift, guarded downgrade |
| `uv run python scripts/export_openapi.py`; `npm --prefix miniapp run api:generate` | PASS; generated files not manually edited |
| `uv run python scripts/check.py --scope all` | Final PASS: ruff, mypy (69 files), 53 unit/contract, 73 frontend, frontend typecheck/build, OpenAPI/region/TS drift, clean migration and 97 PG integration; integration 190.27s |
| `npm --prefix miniapp run test:browser` with PLAYWRIGHT_BASE_URL=http://127.0.0.1:8026, PLAYWRIGHT_CHANNEL=chrome | PASS 8 / 18.8s, including actual API→PG→board/detail/reload; 320/430/1280 light/dark, keyboard/accessibility/unknown values |
| `uv run python scripts/docker_smoke.py --project domsignal-smoke-a16 --api-port 18087` | PASS clean build/PG/migrations/seed/API+worker and persisted Incident after API restart; own project cleaned by existing script |
| `uv run python -m domsignal.tools.seed_tickets`; `uv run python scripts/ticket_smoke.py --base-url http://127.0.0.1:8026` | PASS actual network HTTP Report→Ticket→accept→start→attempt→resolved→late unresolved→read, version 6 |
| Separate Compose `domsignal-smoke-a16-ticket`, port 18088: seed_tickets; ticket_smoke; `docker compose ... restart api worker`; ticket_smoke `--read-incident d9544cd6-c107-43fd-b5d0-a45dd610f69f` | PASS after actual API AND worker process restart: same Ticket c816f50a-ee3a-45e5-b65b-3dc882352a7c, version 6, in_progress/rework; SQL confirmed all 6 intents pending |
| `git diff --check`; repository-sanity + relevant local Markdown links | PASS (final pre-commit check) |

Full final suite includes all previous 65 PG integration cases plus 32 A-16 cases
(31 HTTP/PG + populated migration), with no regression suppression. Two existing
AccessPolicy permission assertions were extended to the implemented Ticket/resident
permissions; old scope assertions remain. [TK-01…26 mapping](../../scenarios/acceptance.md#a-16--backend-evidence-18092026)
preserves C/MT/CB/QA IDs and separates future UI/delivery/live evidence.
Concurrency uses independent DB sessions, simultaneous HTTP requests, and an
explicit held PG aggregate lock; it is not sequential simulation. SQL rollback
fault injection checks no partial Report/Incident/Ticket/Event/Intent. Existing
Starlette/anyio deprecation warnings and browser color notice remain non-failing.

The host-process restart command was rejected by automatic execution policy;
the restart requirement was instead completed through the scoped Compose project.
The loopback browser-test API at 8026 and dedicated PG container at 55476 remain
available locally; no new scheduled/background automation was created. The separate
Compose Ticket smoke was stopped with down; its test volume is retained.

## Reproduce A-16 network smoke

Use a fresh isolated Compose project and an unused loopback port, not a shared DB.
PowerShell example (MAX_TRANSPORT remains off in the checked-in Compose):

```powershell
$env:API_PORT='18088'
docker compose -p domsignal-smoke-a16-ticket up --build -d
docker compose -p domsignal-smoke-a16-ticket exec -T api python -m domsignal.tools.seed_tickets
uv run python scripts/ticket_smoke.py --base-url http://127.0.0.1:18088
docker compose -p domsignal-smoke-a16-ticket restart api worker
# Wait for /ready, then substitute the incident_id printed by the previous command:
uv run python scripts/ticket_smoke.py --base-url http://127.0.0.1:18088 --read-incident <incident_id>
docker compose -p domsignal-smoke-a16-ticket down
```

The idempotent seed adds synthetic roles/two organizations/three houses, without
resetting data or granting real access. Repeated smoke creates an explicit new
test report; no generic Ticket create, public seed/reset, or automatic old-data work.

## A-16 status, limitations and next step

- A-16 backend: PASS / IMPLEMENTED IN BRANCH. A-01/A-15/A-07/B-02 regression PASS.
- MERGED: no; origin/main remains 3d4a095. Remote CI/review are separate from local PASS.
- LIVE VERIFIED: no. MAX delivery/UI/callbacks/live clients, real organization
  connection and normative applicability NOT RUN. B-14 and other roadmap work not started.
- Existing core still creates a new Incident per ordinary Report; linked-report
  fixtures do not claim semantic matching. Existing assignment roles cover routing;
  no category rules or responsibility verification were invented.
- No normative calculator/verified deadline source, join flow, photo/voice,
  full admin/web-auth/MFA, official registration, archival tenant transfer or retention
  platform. Current safety UI/path unchanged; no AI/emergency classification added.
- Next single step: DEV-A review of the A-16 branch and current remote CI before a
  normal PR merge. Do not automatically start B-14, MAX delivery or the next roadmap task.

## Previous Q&A documentation handoff — historical evidence

Updated: 2026-09-18 (Q&A documentation alignment)
Branch: dev/b-experience
Current task: QA-ALIGNMENT-2026-09-18 — документы и план
State: DOCS UPDATED; runtime readiness unchanged; A-16 TARGET / TODO / NOT STARTED

## Результат документационной правки

[Источник](../decisions.md#qa-alignment-2026-09-18) — заметки владельца после
Q&A организаторов, не самостоятельно просмотренная запись. Снят только блокер
общей допустимости LLM; provider/data/license gate сохранён. Собственный API
готовим для проверок в A-13: HTTPS, OpenAPI, роли/данные, обязательные проверки,
DATA-API по ещё не полученному официальному шаблону. Веса ТЗ не менялись.

A-16 уточнена: стабильный внутренний номер, исходные Report/заявители/история,
ответственный/резерв и следующий шаг, WorkAttempt/ResultObservation, позднее
возражение, четыре смысла срока и атомарные typed events/outbox intents.
Правило закрытия/reopening ждёт следующего согласования. Delivery остаётся
A-05/B-03/B-06/B-07/A-09/B-08, UI — B-14, live — B-01/B-11. Все эти Owners —
DEV-B; AI остаётся DEV-A. QA-01…QA-13 добавлены как PLANNED / NOT RUN.

№416: [таблица пунктов/применимости](../PRODUCT_ARCHITECTURE.md#пп-рф-416--документальная-сверка-18092026)
по тексту редакции 20.06.2026 из LegalActs/СудАкт; официальная публикация найдена,
но текст первоисточника получить не удалось. Ограниченная документальная сверка,
не полный compliance. Нужны официальная повторная сверка/порядок Минстроя,
роль продукта у партнёра, основания/anchors и раздельная retention policy.
Контроль жителем не акт приёмки; фото остаётся A-14/Product/B-13.

## Проверки и refs этой правки

- Стартовый HEAD и origin/dev/b-experience: `4628d11` (A-07);
  origin/main: `3d4a095`; origin/dev/a-core: `a70df01`, handoff прочитан из ref.
  Fetch успешен; синхронизация собственной ветки/main — already up to date.
- Repository-sanity по действующему CI: обязательные файлы, agent discovery,
  отсутствие conflict markers — PASS. Локальные Markdown пути/anchors — PASS.
  Прежние 100 строк C/MT/CB/A-15 acceptance и веса критериев сохранены.
- `git diff --check` — PASS; docs-only scope проверен. Архив плана, DEV-A status,
  runtime OpenAPI/generated TS, код/миграции/dependencies не изменены.
- Официальные страницы MAX send/edit/subscriptions/Mini App/Bridge и callback
  прочитаны, это DOC CHECK. Heavy product tests/Docker/live не запускались.

A-07 остаётся IMPLEMENTED IN BRANCH, не MERGED; текущий групповой путь только
явная `/report`. Live MAX **NOT VERIFIED / PENDING TOKEN**. Нужны разрешённый
токен, изолированные чаты, HTTPS-стенд и реальные клиенты. Новые evidence A/B
не подменяют C. Webhook/данные/боевой MAX не тронуты; Git cleanup не выполнялся.
Финальный SHA и результат push собственной ветки — в итоговом сообщении;
review/актуальный CI до main остаются обязательными. Остановиться после этой
правки: реализацию Ticket/UI/уведомлений/LLM и A-16 не начинать.

## Предыдущий handoff A-07 — сохранённое evidence

Updated: 2026-09-18 (A-07)
Branch: dev/b-experience
Current task: A-07 — existing MAX chat connection and safe ChatBinding
State: PASS / IMPLEMENTED IN BRANCH; MAX NOT LIVE VERIFIED / PENDING TOKEN

## Delivery boundary

| Slice | State | Evidence |
|---|---|---|
| A-01 / C0.1 | PASS / IMPLEMENTED IN BRANCH | Parent e66c351; producer/consumer regressions and OpenAPI/TS drift rerun |
| A-15 | PASS / IMPLEMENTED IN BRANCH | Parent ffd9b84; all 16 existing isolation/access tests rerun |
| A-07 | PASS / IMPLEMENTED IN BRANCH | Migration 0003, provider/state/approval/context/worker; CB-01…CB-22 PASS, 38 PG cases |
| B-02 | PASS / IMPLEMENTED IN BRANCH | 8 browser tests, real API/PG create/board/detail/reload plus existing 73 frontend tests |
| Real MAX | IMPLEMENTED / NOT LIVE VERIFIED | Read-only production provider + webhook; no real token/chat calls; PENDING TOKEN |
| Ticket / full admin UI / AI | NOT STARTED | Explicitly excluded from this task |

Start and END refs after fetch: own branch/remote ffd9b84, origin/main 3d4a095.
Own fast-forward/main synchronization was already up to date. Colleague handoff
read from origin/dev/a-core; no writes/push to that branch. Main is unchanged:
second-developer review/current CI/merge remain pending. IMPLEMENTATION_CONTEXT
retains the verified main table and a separate branch pointer. Final commit SHA
is provided in the final response, not a follow-up hash-only commit.

## Implemented flow and invariants

MAXChat is a technical snapshot of an already existing chat: UUID, unique string
max_chat_id, type/title/channel/owner, bot_present, last_seen/lifecycle timestamps
and a monotonic binding counter. Title/text/LLM/client parameters never select a
house or tenant. No API creates groups or imports participant lists.

ConnectionRequest stores management+house, initiator, connector MAX identity,
SHA-256 digest of a random 256-bit opaque token, expiry, scope, candidate chat,
verification/completion/cancellation/rejection times and sanitized error code.
TTL defaults to 900 seconds. The raw token is returned once; it is absent from
DB receipts/jobs/outbox. Repeated open initiation returns the same request with
null token; cancel/recreate recovers a lost first response.

State transitions are centralized in core/chat_connections.py and applied by the
application service: created → connector_claimed → chat_detected → max_verified
→ awaiting_approval → completed; expired/cancelled/rejected terminal. Same-company
connector with the same persisted MAX identity and current chat.connect permission
can confirm from max_verified. External connector waits for target-company approval.
Neither path needs mandatory Superadmin approval, and both require explicit confirm.

ChatBinding pins management+house and house/entrance scope; states pending → active
→ suspended/revoked, suspended → revoked. Reactivation/reassignment always uses a
new request/binding. The chat counter increments across bindings (1 → 2), old
binding scope/version is immutable, and histories are retained. Revoke is an
internal authorized service; no full administration endpoints/UI were introduced.

DB constraints: unique MAXChat external ID/token digest/request binding; composite
FK (management_id,house_id) for request and binding using the A-15 pattern; typed
scope/status/version CHECKs; unique (chat,version) and partial unique active chat;
immutable binding scope/version trigger. No house uniqueness prevents multiple
chats per house. An A-15 management status/end trigger suspends old active bindings
with MANAGEMENT_ENDED; natural period expiry is checked by health/access resolution.
No binding or old Incident history transfers automatically to a successor company.

`chat.connect` extends existing AccessPolicy: active company_admin, or active
organization operator with responsible assignment. Resident/operator alone cannot
connect. Backend derives current management/tenant. Existing OperationContext and
MembershipService remain the only access/context mechanism.

bot_started claims a valid unexpired token to the webhook's sender MAX identity;
same actor replay is idempotent, another actor cannot steal the request. A connector
may have only one open request; ambiguous bot_added is not guessed. bot_added
matches that connector's prior claim and records candidate chat, then enqueues
verification. Unrelated/duplicate add never activates a binding. Lifecycle event
timestamps stop an older add/remove from reversing newer installation state.

Verification reads current ChatInfo, bot membership/admin+mandatory permissions
(default read_all_messages), and current connector admin/owner from the provider.
No bot_added.user or token is permanent authority. Timeout/429/5xx keeps a new
connection chat_detected with verified_at null and uses durable job retry. Approval
rechecks MAX even after earlier success. Invalid/missing/unsupported responses fail
closed. Approval confirms current employee/management/company again after network
calls, rejects foreign active-chat conflict generically, creates binding/outbox and
completes request atomically. Lock order: house shared → chat advisory → request row;
DB uniqueness independently rejects concurrent activation. Request detection racing
its routing read fails closed for retry instead of reversing lock order.

Webhook authenticates configured secret before payload parsing (bounded 64 KiB).
Only explicit webhook mode accepts live payloads. Mapping lives in bot/max_updates;
application receives typed events. Concurrent duplicate delivery serializes on a
stable inbox identity. Receipt/state/jobs commit before HTTP 200. Inbox holds no
raw token or ordinary/unbound message text. Unknown events are acknowledged without
product effects; malformed identity gets sanitized Problem Details.

Group product intake is deliberately explicit `/report <category> <description>`
through existing manual ReportService core; no AI/NLP or B-06 auto-group introduced.
The author must already have authorized resident/employee access. Unbound chats,
ordinary conversation, channels and unauthorized actors create no Report/Incident
and invoke no NLP. There is no fallback demo/first house or membership grant.

For eligible messages, receipt captures chat_binding_id, binding_version and event
time. Worker checks binding health, then resolves chat → ACTIVE binding → pinned
current management → tenant/house → existing AccessPolicy → OperationContext in the
write transaction. Wrong/old ID/version, pre-activation events, management changes
and revoked access are ignored as terminal stale context. Outbox carries binding
ID/version and verified entrance hint; text cannot reassign it. No outbound group
sender/broadcast is added. Future senders must use the same guard before effects.

bot_removed sets bot_present false and suspends once with BOT_REMOVED. Health service
is worker-callable as max.binding.health and runs before each group report; missing
admin/permissions, inaccessible chat or unknown MAX state suspend. No periodic cron
was added. Recovery requires new confirmation/version, not automatic resumption.
Signed Mini App chat/start_param remain selectors only in the target architecture;
this version ignores them as access authority and keeps the existing explicit
house flow. No automatic ResidentMembership or live Mini App claim.

## API, provider and migration

Added API (existing session/Problem Details style):
- POST /api/v1/houses/{house_id}/chat-connections
- GET /api/v1/chat-connections/{request_id}
- POST /api/v1/chat-connections/{request_id}/approve with confirm:true
- POST /api/v1/chat-connections/{request_id}/reject
- POST /api/v1/chat-connections/{request_id}/cancel
- POST /max/webhook now implements authenticated mapping when explicitly enabled;
  off still gives 503. Existing test replay/manual endpoints remain independent.

OpenAPI and generated TS updated together. Foreign scopes are masked 404; visible
scope without permission 403; conflicts 409; provider failure 503/retryable.
Error codes include connection_expired, connector_not_chat_admin,
bot_permission_missing, chat_already_bound, management_not_active, tenant_suspended,
binding_not_active, stale_binding_version and sanitized max_* errors. No foreign
owner/title, raw upstream JSON or secrets appear in responses.

Production HttpMaxChatProvider is the sole read HTTP boundary, using configured
HTTPS origin (current official default platform-api2.max.ru), token from Settings
in Authorization, timeout, no redirects and strict response mapping. 401/403/404/
429/5xx/network/malformed responses have safe typed errors. It uses only documented
GET chat, members/me and members/admins. Unexpected admin pagination is explicitly
unsupported, not guessed. TLS is not disabled. HTTPX moved from dev to runtime.
Off/recording composition withholds token from the provider, preventing live calls.
The deterministic adapter exists only in tests/fakes and must be explicitly injected.
It covers metadata/admin/non-admin/permissions/timeout/429/5xx/missing chat.
Production selection and response mapping are independently tested.

Migration 20260918_0003 is additive, produces no active/demo bindings and preserves
existing A-15 grants/history. Clean upgrade and upgrade from populated C0.1/A-15
are tested. Empty A-07 downgrade works through base and back to head. Nonempty
chat/request/job history blocks destructive downgrade and requires a pre-A07 backup.
Alembic check reports no drift. Existing private PostgreSQL + worker/outbox are reused.

## Actual commands and evidence

Dedicated local PostgreSQL container domsignal-a07-db, loopback 55475; existing
shared DBs untouched. Python 3.12.14; Node 24.21.0 in child process PATH, existing
npm launcher; browser Chrome against own API 8020 with MAX_TRANSPORT=off. Docker
smoke uses its own project/volume/API 18086 and removes that smoke volume afterward.
No real MAX token, shared webhook mutation, polling or VPS deployment was performed.

| Command actually executed | Result |
|---|---|
| uv run ruff check src tests scripts migrations --fix; final without --fix | PASS; initial import/line-length issues fixed |
| uv run ruff format <explicit changed Python paths> | Formatting confined to this task |
| uv run mypy src/domsignal | PASS, 62 files; initial redundant cast corrected |
| uv run pytest tests/unit tests/contract -q / same via check.py backend | Final PASS, 51; initial tests package import collection issue fixed |
| uv run alembic upgrade head | PASS, clean 0001 → 0002 → 0003; initial multi-statement asyncpg DDL corrected before success |
| uv run alembic revision --autogenerate -m 'verified MAX chat connections' --rev-id 20260918_0003 | Generated additive draft, then reviewed and hardened |
| uv run pytest tests/integration/test_chat_bindings.py -x -q | PASS first 28 cases; final expanded suite 38 |
| uv run python scripts/check.py --scope backend | Final PASS: ruff, mypy, 51 unit/contract |
| uv run python scripts/check.py --scope integration | PASS: upgrade head + 65 integration tests (A-07 38, A-15 16, other regressions/migrations 11) |
| Migration harness subprocesses: python -m alembic upgrade 20260917_0001 / 20260918_0002; upgrade head; check; downgrade 20260917_0001/base; upgrade head | PASS in two uniquely named temporary PostgreSQL DBs; grants/data preserved; history-bearing A-07 downgrade correctly refused |
| uv run pytest tests/integration/test_chat_bindings.py::test_cb18_max_temporary_failure_is_pending_with_durable_retry tests/integration/test_jobs.py -q | PASS, 6 after final provider/terminal-job hardening |
| uv run python scripts/export_openapi.py | PASS, regenerated |
| npm --prefix miniapp run api:generate | PASS, regenerated |
| uv run python scripts/check.py --scope frontend | PASS: npm run typecheck; npm run test -- --run (73); npm run build |
| uv run python scripts/check.py --scope contracts | PASS: export_openapi --check; validate_region_pack.py; npm exec openapi-typescript to temporary file; TS comparison |
| uv run uvicorn domsignal.main:create_app --factory --host 127.0.0.1 --port 8020 | Own API for B-02 browser checks, test/off mode |
| npm --prefix miniapp run test:browser (explicit Node 24 npm CLI, PLAYWRIGHT_BASE_URL=8020, PLAYWRIGHT_CHANNEL=chrome) | PASS, 8; real-detail screenshot inspected |
| uv run python scripts/docker_smoke.py --project domsignal-smoke-a07 --api-port 18086 | PASS, clean image/PG/migration/seed/API+worker/restart persistence |
| docker compose -f compose.yaml -f compose.prod.yaml config --format json (synthetic config-only env) | PASS; PostgreSQL no published ports; required services share network |
| git diff --check | PASS |

Existing Starlette/httpx/anyio deprecation and browser color notices remain; no
checks were suppressed. B-02 board/detail/manual/reload and /me/houses/capabilities
regressions pass with group transport off. CB-01…CB-22 outcomes and test names:
[acceptance matrix](../../scenarios/acceptance.md). Source/doc mapping and 18 pending
live smoke steps: [MAX_LIVE_SMOKE](../MAX_LIVE_SMOKE.md).

## Remaining boundary / next

A-07 PASS refers to this authorized backend/connection slice and deterministic
regressions. IMPLEMENTED IN BRANCH is not MERGED TO MAIN. MAX integration code is
IMPLEMENTED / NOT LIVE VERIFIED; live verification is PENDING TOKEN and two real
existing test chats, HTTPS webhook, genuine permissions/identities and clients.
No real token was requested from secret stores or invented as production credentials.
Test adapters/synthetic events are explicitly not live integration evidence.

The next DEV-B step is to finish B-01 live feasibility after a public HTTPS VPS/DNS
endpoint is available, using the issued token and isolated bot/chats. Do not start
A-10/Mini App binding or unrelated product work from this handoff. Review/CI of
this branch precedes main merge.

## A-12/B-01 production webhook bootstrap — 18.09.2026

Production Compose is now a fail-closed live overlay: `APP_ENV=production`, test
session and demo seed disabled, fixed webhook transport/bot username/API origin,
required token/webhook/session/DB secrets, HTTPS public origin/CORS, DB-backed API
readiness, restart policies and private PostgreSQL. Caddy remains the single HTTPS
edge and keeps persistent certificate state. The runtime trust store includes the
Russian Trusted Root CA used by the current `platform-api2.max.ru` chain; TLS
verification is not disabled.

Settings reject short/template session and DB secrets, missing/template MAX
credentials, non-webhook production transport, another bot username/API origin,
HTTP/path/non-default-port public URLs and invalid CORS. Production composition
still selects only `HttpMaxChatProvider`/`HttpMaxMessagingProvider`; deterministic
fakes remain tests-only. Contract coverage proves production test auth is disabled,
and webhook authentication returns 401 before parsing while valid secret + `{}`
reaches the expected 422 payload rejection.

Added `deploy/.env.example`, a copy-paste VPS/Caddy/Compose runbook and guarded
`python -m domsignal.tools.max_subscription`. The operator tool verifies `GET /me`,
lists subscriptions, refuses every foreign/multiple-URL conflict, checks public
`/ready` and webhook 401/422, then registers the exact official six update types.
Update/secret rotation uses documented POST for the same URL; DELETE targets only
that exact URL and verifies removal. HTTP 200 with `success=false` always fails.
Application startup never creates, replaces or deletes a subscription.

Read-only live evidence from the built runtime image: TLS validation succeeded;
`GET /me` matched `t480_hakaton_max_bot`; `GET /subscriptions` returned `[]`.
No POST/DELETE, polling, public deployment or synthetic live event was performed.
There is no public HTTPS hostname/VPS in this environment, so external `/ready`,
subscription registration and real `bot_started`/message/callback delivery remain
PENDING PUBLIC HTTPS / NOT LIVE VERIFIED. Mini App binding and A-10 were untouched.

Relevant evidence:

| Command/check | Result |
|---|---|
| `uv run ruff check ...`; `uv run mypy src/domsignal` | PASS; mypy 77 source files |
| `uv run python scripts/check.py --scope backend` | PASS: ruff, mypy 77 source files, 96 unit/contract tests |
| isolated PostgreSQL: Alembic head + `test_chat_bindings.py test_notifications.py` | PASS, 58 tests |
| `uv run python scripts/docker_smoke.py --project domsignal-smoke-max-live-final --api-port 18092` | PASS; final image migration/seed/API/worker/restart persistence, isolated volume removed |
| production Compose config with safe synthetic env | PASS; DB has no published ports, API is loopback-only, Caddy 80/443 |
| production Compose with missing env; runtime with template values | FAIL CLOSED as expected |
| `caddy validate`; root certificate subject/validity/SHA-256 | PASS |
| built-container guarded `list` with issued token | PASS; correct bot and zero subscriptions, no mutation |

Canonical commands and manual VPS/DNS/secrets boundary are in
[`deploy/README.md`](../../deploy/README.md); the live evidence boundary remains in
[`MAX_LIVE_SMOKE.md`](../MAX_LIVE_SMOKE.md). Final exact test counts, diff check and
commit SHA belong to the session report after the final checkpoint.
