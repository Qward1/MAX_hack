# ДомСигнал — ROADMAP для двух разработчиков и кодовых агентов

> План реализации, **не отчёт о выполнении**. Фактический статус и evidence — в handoff владельца, проверенном implementation context и PR; завершённые foundation/B-00 не возвращаются в TODO.
> Согласованная цель: [ARCH-PLATFORM-v1](docs/PRODUCT_ARCHITECTURE.md), TARGET от 17.09.2026. Этот roadmap остаётся единственным действующим планом.
> Основа: `domsignal_plan.md`, §§ 5–8, 15–16. Адаптация от 17.09.2026: два разработчика, ранняя mini app, активное использование агентов, больше законченных сценариев на одном ядре.
> Даты онлайн-этапа и контрольных точек ниже взяты из исходного плана команды; точное время сдачи и условия проверки требуется подтвердить у организаторов.
> Уточнения по заметкам владельца после Q&A: [QA-ALIGNMENT-2026-09-18](docs/decisions.md#qa-alignment-2026-09-18). Требования, не новый runtime/live evidence; веса ТЗ прежние, направления организаторов — примеры.

## 1. Что выпускаем

**ДомСигнал: из сообщения о проблеме — к понятному маршруту и подготовленному обращению, с общей историей для соседей.**

Продуктовый цикл: личное сообщение или реплика в разрешённом домовом чате → уточнение и проверка срочности → создание/присоединение к инциденту → адресат с источником → редактируемый текст → переход в официальный канал → отметка жителя о подаче → напоминание → наблюдение о результате/следующий шаг.

Вводим три уровня объёма:

| Уровень | Смысл | Что относится |
|---|---|---|
| **P0 — обязательный законченный продукт** | Без этого релиз не принимается | Личный путь + реальная MAX-интеграция + mini app с доской/карточкой/редактором + проверяемые маршруты + источник статуса + сохранение/ошибки/права + воспроизводимая поставка |
| **P1 — целевой сильный релиз** | Берём ограниченными срезами с проверкой; ARCH-PLATFORM-v1 расширяет цель, но не гарантирует весь объём к прежним датам | Групповые инциденты, контекст между тремя пространствами, соседи, история/напоминания/эскалация, QR/sharing, проверяемые подключения, веб-кабинет УК, назначения/очередь Ticket, второй регион, больше проверенных категорий, полезная NLP-подсказка |
| **P2 — усиление после готовности P0/P1** | Берём только при наличии ресурса проверки | Вложения, голос → редактируемая расшифровка, ограниченная подсказка по фото, дополнительные представления/язык |

**Увеличиваем количество законченных путей, а не количество экранов-заглушек.** P1 включается в релиз только с backend, UX, тестами и честной маркировкой ограничений. Из P0 нельзя удалить ошибку/права ради ещё одной «kill-фичи».

Не обещаем официальную регистрацию: без внешнего подтверждения написано **«Житель отметил подачу»**. Добавляем согласованный ограниченный рабочий контур УК: tenant, назначения, подключения, отдельный веб-кабинет и Ticket; полноценная CRM ремонтных бригад и биллинг остаются вне scope. Сохранение исходного обоснования не означает, что его статистика, правовые примеры и ограничения конкурентов повторно проверены: это отдельная исследовательская работа.

## 2. Владельцы и параллельность

Префиксы `A-`/`B-` и имена постоянных веток исторические. Owner определяется
только явным полем карточки. DEV-A направляет около 90% усилий на AI/NLP/ML;
это ориентир специализации, а не основание добавлять ненужную модель, RAG,
vector DB или мультимодальность.

| Кто | Ветка | Ответственность |
|---|---|---|
| **DEV-A — AI / NLP / ML** | `dev/a-core` | Нормализация и данные для моделей; category/field extraction; classifiers; LLM providers/prompts/structured output; semantic ranking; AI-specific timeout/fallback/circuit breaker; datasets/evaluation/regression; качество, задержки и стоимость AI; backend-код выделенных AI modules. ASR/vision/RAG — только по принятому roadmap. |
| **DEV-B — Product / Fullstack / MAX** | `dev/b-experience` | UI/UX, mini app/MAX Bridge, bot/transport; public API/contracts; core/services; incidents/messages/membership/appeals; rules/regions; DB/migrations; auth/security; общие jobs/outbox/delivery; admin/analytics; Docker/CI/deploy/observability/release; E2E и демонстрация. Интегратор по умолчанию. |

Оба тестируют свой код и проверяют PR коллеги. DEV-A обязательно review PR
DEV-B; интегратор не обходит review или protection `main`.

### Каноническая матрица ownership

| Область | Writer | Реальные пути / точная граница | Карточки и handoff |
|---|---|---|---|
| AI/NLP/ML modules | DEV-A | Целевые выделенные `src/domsignal/ai/`, `src/domsignal/nlp/`, `datasets/`, `evaluation/`, `model_artifacts/` и точные `tests/ai/`, `tests/nlp/`. В проверенных refs этих каталогов ещё нет; они создаются только нужной задачей. | A-03/AI, A-06/AI, A-08, A-11/AI, A-14/AI. A отдаёт типизированный анализ, uncertainty/fallback и evidence качества. |
| Product backend | DEV-B | Существующие `src/domsignal/core/`, `services/`, `api/`, `contracts/`, `db/`, `tools/`, `main.py`; `/tests/` по умолчанию. Точный AI test path ниже/уже широкого правила принадлежит A. | A-01, A-02, A-03/Product, A-04, A-05, A-06/Product, A-07, A-09, A-10, A-11/Product, A-12, A-13, A-14/Product, A-15, A-16 и backend-срезы B-задач. B применяет AI-результат и делает транзакцию. |
| MAX, bot и frontend | DEV-B | `src/domsignal/bot/`, `miniapp/`, browser tests и MAX fixtures/scenarios. | B-01…B-14; business rules вызываются через services/core, а не копируются в React/handlers. |
| Public contract | DEV-B | `src/domsignal/contracts/`, API routes/errors, `docs/openapi.json`, `miniapp/src/shared/api/schema.ts`, `docs/CONTRACTS.md`. | Один producer+consumer+generated types+tests diff. AI-specific внутренний contract пишет A; совместимую границу review оба. |
| Persistence | DEV-B | `src/domsignal/db/`, `migrations/`, persistence/integration tests. | Один writer models/migrations; A не пишет model schema ради AI feature. |
| Jobs и delivery | DEV-B по умолчанию; DEV-A только выделенный AI handler | `src/domsignal/worker/`, общая queue/leases/retries/outbox/delivery и wiring — B. AI handler живёт в точном AI-модуле A и возвращает typed result. | A-05 — B; AI-specific execution в A-03/A-08. Регистрацию handler/settings согласует B коротким diff. |
| Rules, regions и product data | DEV-B | `regions/`, нормативные справочники, route/deadline logic и tests. | A-02/A-10/A-11/Product. Model datasets принадлежат A и не заменяют проверенные нормы. |
| Wiring, dependencies и delivery platform | DEV-B | `bootstrap.py`, `settings.py`, `pyproject.toml`, `uv.lock`, `miniapp/package*.json`, `Dockerfile`, `compose*.yaml`, `deploy/`, `.github/workflows/`, общие scripts. | Один writer каждого общего файла; dependency/lock/deploy меняются целым проверяемым срезом. |
| Общий context и status | DEV-B — `IMPLEMENTATION_CONTEXT.md`; каждый — только свой status | `IMPLEMENTATION_CONTEXT.md`, `docs/status/dev-a.md`, `docs/status/dev-b.md`. | Context обновляется после значимого принятого merge; branch progress остаётся в status. Историческое разовое разрешение правки обоих status относилось только к решению о ролях; этот архитектурный patch меняет только status DEV-B. |

Широкое владение DEV-B каталогами `src/domsignal/` и `tests/` не перекрывает
точные AI/NLP paths DEV-A. Для общих файлов нужен короткий согласованный diff,
а не разрешение на каждый шаг внутри своей зоны.

### Текущий следующий срез

| Developer | Сейчас / следующий шаг | Настоящая зависимость и снимающий контракт |
|---|---|---|
| DEV-A | Сохранить review/handoff FND-01; затем A-03/AI: baseline extraction/risk detector + evaluation, без обязательного provider. | DEV-B задаёт разрешённый input scope и public application boundary; A возвращает typed analysis fixture и не ждёт реализации всего product backend. |
| DEV-B | **A-07 IMPLEMENTED IN BRANCH**, `4628d11`, поверх A-01/A-15; B-02 evidence сохранён. Сейчас — Q&A docs alignment; далее B-01 при доступах и отдельное согласование A-16, без начала реализации. | Evidence: [dev-b](docs/status/dev-b.md), [MAX smoke](docs/MAX_LIVE_SMOKE.md). Live MAX NOT VERIFIED / PENDING TOKEN; не MERGED TO MAIN. Групповой путь — явная `/report`, не анализ переписки. |

### Встраивание ARCH-PLATFORM-v1 в существующий план

| Раздел 14 архитектуры | Действующая карточка / изменение |
|---|---|
| C0/B-00/C1 | A-01: ограниченная convergence и минимальный контекст; B-02: сохранить C0 UI/evidence, затем повторный binding |
| Tenant/access | **Новая A-15**: отсутствующая основа двух УК, HouseManagement и назначения; не повтор FND-01 |
| Проверенная установка | A-07 + B-03/B-07, feasibility B-01; установка больше не зависит от matching A-06 |
| Кабинет/заявки УК/лимиты | A-10 + B-09: обычный web вместо Admin Mode, общая backend-логика |
| Инциденты/рабочая очередь | A-02/A-04/A-06 сохраняют границы; **новые A-16 + B-14** только для отсутствующих Ticket core и рабочего UI |
| Jobs/эксплуатация | A-05/A-09/A-12: актуальный tenant/access scope перед выполнением и доставкой |
| AI | A-03/AI, A-06/AI, A-08, A-11/AI: разрешённый typed input, независимый manual путь; без зависимости всей платформы от DEV-A |

Порядок новых срезов: документационная фиксация → **A-01** (отдельное следующее
обсуждение) → A-15 → повторная проверка/binding B-02 → A-07 и A-10/B-09 →
A-16/B-14 → MT-проверки B-11/A-12. Содержательные зависимости личного пути
A-02…A-06 сохранены. B-01 допускается параллельно; live-блокеры не мешают
документам, но запрещают LIVE VERIFIED. A-03/AI не ждёт всю платформу.
FND-01 и B-00 не выполняются заново, B-02 не закрыта этим patch.

A-15 — PASS / IMPLEMENTED IN BRANCH, evidence в DEV-B handoff; A-16/B-14 остаются TARGET / TODO. Старый календарь
ниже остаётся ориентиром: расширенный scope требует переоценки перед взятием
каждого среза, а не обещания выполнить всю платформу к прежнему freeze.

### Как использовать агентов с выигрышем

Один пишущий агент — один изолированный worktree/checkout. DEV-A может
параллельно вести независимые provider/evaluation/NLP-срезы; DEV-B — UI, bot и
backend только при непересекающихся write-paths. Contracts, migrations, locks и
wiring имеют одного writer. Результаты владелец направления объединяет
последовательно; read-only review можно вести отдельно.

Обычно активен один интегрируемый срез на ветку. Измеряем скорость по принятым
acceptance criteria и merged PR, а не по числу агентов или строк.

## 3. Первые контракты: чем разблокируем друг друга

Pydantic/OpenAPI — источник формата; `docs/CONTRACTS.md` — смысл. TS types генерируются, а не переписываются вручную.

| Пакет | Когда / writer | Минимум данных | Что разблокируется |
|---|---|---|---|
| **C0 — skeleton** | FND-01; реализовал DEV-A, дальнейший public writer DEV-B | Me, House, Incident summary/detail, Report input, Error, capabilities | Board/detail/form, состояния ошибок и доступа |
| **C1 — основной путь** | A-01 convergence, A-04 предметное развитие; writer DEV-B | IntakeResult с уточнениями, RouteResult, source/deadline, AppealDraft, structured `allowed_actions` | Личный диалог, карточка маршрута, редактор обращения; A-01 convergence завершает блок B-02 |
| **AI analysis boundary** | A-03/A-08; internal writer DEV-A, product boundary review DEV-B | Категория/поля/candidates, uncertainty, questions, execution/fallback state | Product orchestration может использовать model/rules одинаково и сохраняет manual путь |
| **C2 — совместная проблема** | A-06/A-07; public writer DEV-B | Participant count, message count, ChatBinding, IncidentEvent, Feedback, conflict state; semantic scores A — только input решения | Групповые карточки, история, подтверждения/возражения |
| **C3 — сопровождение/admin** | A-09/A-10; writer DEV-B | Reminders, escalation preview, настройки/агрегаты; A-10 добавляет onboarding УК, лимиты и назначения для web-кабинета | Мои обращения, администрирование, фильтры/сводки |

Контрактный PR может определять ещё не подключённый DTO и валидируемые fixtures, но **не публикует несуществующий endpoint с фиктивным успешным ответом**. На UI допустим MSW для разработки; в сборке релиза он выключен и не подменяет сбой настоящего API.

Все передачи содержат task ID, Owner, готовый PR, семантику изменений и пример
ответа/ошибки. «Я закончил бэк» или «модель вернула результат» без пути проверки
и fallback — не handoff.

## 4. Контрольные точки и календарь

Это рабочая целевая сетка, а не гарантия скорости агента. При позднем старте сдвигаем промежуточные даты и уменьшаем P2, но сохраняем время на release-проверку. Не проставлять прошедшим датам DONE задним числом.

| Этап | Цель / дата из плана | DEV-A | DEV-B | Gate |
|---|---|---|---|---|
| **S0 — definition + repository** | Первый день, целевой 17.09 | Исторический исполнитель S0-01/BOOT-01 | Исторический исполнитель B-00; B-01 — доступы и MAX feasibility | Продукт/ветки/правила понятны; блокеры внешних доступов записаны |
| **S1 — foundation** | 17–18.09 | Исторический исполнитель FND-01; review product changes | B-00/B-01, review FND; B-02/B-03 | Локальный UI → API → PostgreSQL → reload; обе ветки стартуют от принятого main |
| **S2 — personal golden path** | 19–21.09 | A-03/AI baseline и evaluation; A-08 только по gate; review C1 | A-01, A-02, A-03/Product, A-04, A-05, A-12 ранний стенд; B-02…B-05 | Golden path работает без LLM; optional AI улучшает, но не блокирует. Настоящий MAX остаётся отдельным gate |
| **S3 — совместный инцидент** | 21–23.09 | A-06/AI semantic ranking | A-06/Product, A-07, A-09; B-06/B-07/B-08 | Группа → личный диалог → доска либо полноценный fallback через ссылки; merge решает core, не model |
| **S4 — сильный релиз** | 23–25.09 | A-08 и A-11/AI по gates | A-10/A-11 Product; B-09/B-10; законченные P1 | Напоминания, history, admin, второй регион; model coverage имеет отдельное evidence |
| **S5 — reliability** | 26–27.09 | AI regression, provider failure/latency/cost checks своей зоны | A-12, B-11 и исправления product зон | Риски доступа, повторов, конфликтов, restart, AI fallback и UI закрыты проверками |
| **S6 — packaging + rehearsal** | 28.09 | Review и evidence AI-компонентов, если они вошли в release | A-13/B-12; проверка README с чистого клона | Совпадают исходники, образ, API schema, данные, PDF и путь проверки |
| **S7 — release** | Цель 29.09; дедлайн из источника 30.09 требует уточнения времени | Обязательный peer review; проверенные AI limitations | A-13 release/deploy и B-12 demo/evidence | Зафиксирован commit, доступен MAX, материалы переданы, нет незаметных изменений |
| **S8 — проверка / подготовка финала** | По подтверждённому регламенту | Сбор фактических AI limitations/quality evidence | Дежурство продукта/инфраструктуры, интервью/пилотный контакт и UX feedback | Не менять сданный код без разрешённого окна; будущая работа не попадает на стенд проверки |

**Группа — ранний gate.** B-01 проверяет права и реальное получение событий в первые часы после доступа к токену. При отсутствии разрешения к контрольной точке 18.09 (или в первые сутки фактического старта) активируем личный путь + sharing/QR. Неподтверждённые групповые функции остаются выключены и не заявляются работающими.

**Freeze — 25.09 по исходному плану.** После него новые P2 не берём. Исправляем дефекты, доводим уже начатые критичные сценарии, документируем. Добавление поздней функции — явный обмен на другую задачу и повторный regression, не «агент за час успеет».

### Вместимость, а не иллюзия неограниченных агентов

Для ориентира: два человека × 6–8 активных часов × 11–12 рабочих дней дают **132–192 человеко-часа**. Это модель при таких допущениях, не сведения о доступности команды. Резервировать порядка четверти времени на review, интеграцию, реальные устройства, доступы и выпуск; оценивать заново после FND-01.

Оценки карточек ниже — относительная сложность: S — локальный срез, M — несколько связанных частей, L — рискованная/интеграционная работа. L делится на PR по acceptance criteria; это не команда ждать единого большого merge. В конце S1 и S2 сравниваем реальную скорость с остатком работ. DEV-B теперь является вероятным bottleneck: сначала C1/golden path, затем group/history/admin, P2 — последним. Дополнительные агенты не устраняют review, contract, migration, live MAX и release gates; при перегрузе режем срезы по этому порядку, а не возвращаем общий backend DEV-A скрытым соавторством.

## 5. Стартовые задачи

### S0-01 — решения и зависимости
- **Owner / authorship:** DEV-A; DEV-B проверяет пользовательские пути. **Priority:** P0. **Size:** S. **Depends:** нет. Последующая смена ролей не меняет автора выполненного решения.
- **Результат:** принято новое разделение на двух разработчиков; выбран набор P0; записаны вопросы про group rights, внешние LLM, API/схему DATA-API, тестовые токены, дедлайн, режим стенда. Не придумывать ответы организаторов.
- **Пути:** `docs/decisions.md`, `ROADMAP.md`, после bootstrap — общий контекст.
- **Acceptance:** для каждого блокера есть владелец, следующая проверка и fallback; scope не зависит от неполученного ответа. Факты из исходного исследования не помечены повторно проверенными.
- **Q&A delta:** LLM разрешено в принципе; provider/data/license gate остаётся. Решение о собственном API принято: готовим к проверкам в A-13; неизвестен шаблон DATA-API, а не необходимость API-проверок.

### BOOT-01 — репозиторий и совместная работа
- **Owner / authorship:** DEV-A; DEV-B — reviewer и проверка clone. **Priority:** P0. **Size:** S. **Depends:** S0-01 в объёме названий/ролей. Сопровождение workflow и интеграция новых правил теперь у DEV-B.
- **Результат:** выполнен промпт №1; `main`/`dev/a-core`/`dev/b-experience`, инструкции, handoff, repository-sanity CI, подтверждённые права GitHub.
- **Acceptance:** оба имеют рабочие клоны и свои ветки; `AGENTS.md` ведёт к `AGENT_INSTRUCTIOM.md`; отсутствие серверной защиты честно указано, если тариф её не даёт. Продукт ещё не объявлен готовым.

### FND-01 — архитектурный walking skeleton
- **Owner / authorship:** DEV-A, единственный writer реализованного каркаса; DEV-B — review и UX acceptance. **Maintenance owner после принятого merge:** DEV-B. **Priority:** P0. **Size:** L. **Depends:** BOOT-01.
- **Результат:** выполнен промпт №2: минимальный сквозной slice, PostgreSQL, auth boundary, jobs basis, DTO/types, UI shell, Compose, реальные тесты.
- **Пути:** только необходимый skeleton согласно архитектуре; не реализация всех последующих задач.
- **Acceptance:** local test user создаёт инцидент, видит его после reload/restart; чужой дом недоступен; main после PR воспроизводим. Внешний MAX остаётся NOT VERIFIED до реального B-01/B-03.
- **Handoff:** C0, настоящие команды запуска/checks, `MaxTransport` port и normalized event. FND-01 не реализуется повторно: DEV-B принимает product backend и делает A-01 convergence; DEV-A использует выделенную AI-границу A-03/A-08.

## 6. Исторические A-ID — явные текущие Owners

### A-01 — минимальная C0/B-00 convergence и контекст C1
- **State / evidence (18.09.2026): PASS · IMPLEMENTED IN BRANCH.** C0.1 + B-02 rebind, context/isolation, error/legacy-receipt regression; [команды и результаты](docs/status/dev-b.md). Не MERGED TO MAIN и не LIVE VERIFIED.
- **Owner:** DEV-B. **P0 · M · Depends:** FND-01; B-00. **Allowed paths:** `src/domsignal/contracts/`, `src/domsignal/api/`, затронутые product read-model services/repositories, `docs/CONTRACTS.md`, `docs/openapi.json`, `miniapp/src/shared/api/` (включая generated schema), затронутые C0 consumers и связанные producer/consumer tests. Без tenant migration или новых бизнес-действий.
- **Сделать сейчас:** минимальный C0/B-00 convergence для B-02: structured `allowed_actions`; provenance отдельно от verification freshness; согласованные capabilities; `message_count`/`report_count` отдельно от unique `participant_count`; нужные read-model поля; единый error contract; generated types и producer/consumer checks. Неподдержанные действия не публикуются. Зафиксировать минимальный tenant/house/access read-model context и совместимость old/new producer без фиктивных tenant/roles. Дальнейшие safety/route/draft/filing C1 реализуются предметными A-03/Product и A-04, не этой convergence.
- **Acceptance:** B-02 читает один generated contract без adapter-догадок; enum/nullable/401/403/404/409/422 задокументированы; опасные поля нельзя принять как verified от клиента; OpenAPI/TS воспроизводимы. Не требуется реализовать все будущие business actions или mock endpoints.
- **Handoff:** маленький contract+producer+consumer+tests PR; DEV-A review границы AI и общих invariants, но не является ожидаемым writer product backend.
- **Граница / проверка:** tenant persistence, назначения и проверка двух УК — A-15; onboarding/кабинет/Ticket исключены. Проверить текущий C0, negative contract cases и генерацию OpenAPI/TS; отсутствующие поля явно unknown/unsupported, не access grant. Реальное B-02 binding перепроверяется отдельно, без автоматического DONE.

### A-02 — движок маршрута, пакеты и сроки
- **Owner:** DEV-B. **P0 · L · Depends:** A-01. **Allowed paths:** product `core/services`, `regions/`, API/contracts при необходимости, rule tests.
- **Сделать:** федеральный/региональный/домовой слои; валидация и provenance; первые четыре категории; applicability и clarification вместо выдуманной ответственности; deadline kind/anchor/calendar. Начать со схемы и одного полного маршрута, затем расширять.
- **Acceptance:** для каждого принятого правила есть источник и фактический статус проверки; неизвестный исполнитель или срок возвращает безопасную неопределённость. На тестовом календаре проверены выходные, переход месяца/года и timezone. Пример из источника не превращён автоматически в норму.
- **Handoff внутри DEV-B:** RouteResult и fixtures нормального/неполного/неприменимого маршрута для bot/UI; дата источника и причина отсутствия due_at. DEV-A использует только стабильные category codes как вход AI evaluation.
- **ARCH target / зависит для tenant-среза от A-15:** правила внешнего адресата и сроки не равны routing рабочей очереди (A-16). Resolver ограничен tenant/домом/периодом управления; неизвестный маршрут остаётся неопределённым. Проверка: одинаковая категория в двух УК не заимствует чужую конфигурацию/источник.
- **Q&A / №416:** вместе с A-11/Product ведёт применимость, источник/редакцию, вид срока, исходное событие и календарь по [матрице №416](docs/PRODUCT_ARCHITECTURE.md#пп-рф-416--документальная-сверка-18092026). Отдельно ответ, согласованная работа, следующее обновление и подтверждённый нормативный срок; A-16 потребляет контракт правил, без универсального смешанного due_at.

### A-03 — intake, NLP baseline и safety-off-ramp
- **Parent ID сохранён; P0 · M · Depends:** A-03/Product зависит от A-01 public boundary; A-03/AI может начать параллельно по короткому согласованному internal fixture/category codes. Реализация делится на два независимых среза с одним Owner каждый.
- **A-03/AI — Owner DEV-A. Allowed paths:** выделенные AI/NLP modules, model fixtures/datasets/evaluation и их точные tests. **Сделать:** нормализация текста для анализа, извлечение категории/места/полей, предварительный detector признаков риска, uncertainty/candidates и regression evaluation. Облачная LLM не обязательна.
- **A-03/Product — Owner DEV-B. Allowed paths:** intake application service, core safety policy, public contracts/API, scenario tests. **Сделать:** access/scope, orchestration, deterministic/manual выбор и уточнение, немедленный safe off-ramp с проверенным текстом, валидация AI-result и только затем запись.
- **Acceptance:** шум не превращается в инцидент; отрицания/исторические упоминания и «отключили газ» не равны автоматически «пахнет газом». Возможная опасность не ждёт LLM или обычную очередь. Пользователь видит проверенную безопасную инструкцию, а не диагноз модели. Synthetic и real quality разделены; AI failure сохраняет manual/rules path.
- **Handoff A → B:** typed category/fields/candidates/uncertainty/questions/execution state fixture. DEV-B решает product action; model confidence не выдаётся за откалиброванную вероятность без evidence.

### A-04 — обращение от черновика до отметки пользователя
- **Owner:** DEV-B. **P0 · L · Depends:** A-01/A-02; FND-01. **Allowed paths:** `src/domsignal/services/`, product core/API/contracts/DB, `migrations/`, tests.
- **Сделать:** create/edit draft, минимальная полнота, сохранение версии, safe official handoff, self_reported filing с необязательным номером, history event. Один и тот же service вызывается bot и REST.
- **Acceptance:** исправления сохраняются; двойное нажатие не создаёт дубликат; конфликт версии не теряет текст; другой житель не редактирует чужой draft. Открытая ссылка не считается подачей; ручной номер не считается проверенной регистрацией. Собственное обращение доступно, даже когда сосед уже отметил подачу.
- **Handoff:** рабочие C1 endpoints, generated client, contract/integration tests и примеры conflict/retry для bot/miniapp в том же направлении DEV-B.
- **ARCH target / зависит для tenant-среза от A-15:** AppealDraft/ExternalAppeal отделены от Report, Incident и Ticket. Проверка: чужой tenant не читает draft/ручной номер; смена УК не переписывает владельца старого обращения; ручной filing не повышается до verified (MT-14/16).

### A-05 — durable execution и доставка без ложного успеха
- **Owner:** DEV-B. **P0 · M · Depends:** FND-01 и transport port из C0. B-03 — интеграция того же направления, не условие начала. **Allowed paths:** `src/domsignal/worker/`, services/scheduling, DB/outbox, tests.
- **Сделать:** довести skeleton jobs до real operations: commit-before-ack, event dedup, приоритеты, backoff, recovery leases, последний актуальный render карточки, взаимодействие с MaxTransport B. DB транзакция не держится во время сети.
- **Acceptance:** crash в ключевых точках воспроизводим в тесте; stale lease не завершает чужое задание; повтор не дублирует доменное действие; один отправитель регулирует запросы. Отдельно документирована неопределённость внешнего send при потере ответа — без обещания exactly-once.
- **Handoff:** sender interface, delivery states, retry policy и тестовый RecordingTransport для B-03. AI-specific handler DEV-A подключается к этой инфраструктуре через отдельный typed boundary и не владеет leases/retries/delivery.
- **Q&A target:** A-16 передаёт типизированные события/outbox intents; A-05 отвечает за delivery states, повторы и согласование последнего render. Сбой MAX не откатывает Ticket; потеря ответа остаётся неизвестным результатом, не exactly-once. Получатель, management/binding и права перепроверяются перед отправкой.
- **ARCH target / tenant-этап после A-15, connection-этап после A-07:** scope в job/outbox и повторная проверка текущих прав/привязки/версии перед побочным действием; отзыв/приостановка не обходятся старым payload. Проверка: restart, повтор и устаревший job двух УК (MT-10/12/17). Базовый sender не ждёт эти расширения; Redis/новый брокер не добавлять.

### A-06 — общий инцидент, соседи и наблюдения
- **Parent ID сохранён; P1 · L · Depends:** A-06/Product — A-03/Product, A-04, A-05; A-06/AI — A-03/AI и согласованный candidate fixture от DEV-B. Реализация делится по ответственности.
- **A-06/AI — Owner DEV-A. Allowed paths:** AI semantic matching/ranking module, evaluation fixtures/tests. **Сделать:** оценить только переданный DEV-B допустимый набор кандидатов и вернуть ranking/scores, uncertainty и признаки для уточнения.
- **A-06/Product — Owner DEV-B. Allowed paths:** core/matching/incidents, services, public API/contracts, DB/migrations, scenario/integration tests. **Сделать:** отбор кандидатов по дому/месту/правам, окончательное create/join/merge решение, участники, отдельные message/report/participant counts, feedback, persistence и concurrency.
- **Acceptance:** semantic score не даёт право merge; разные дома/подъезды/объекты не склеиваются; неизвестное место при двух кандидатах уточняется; гонка двух сигналов не создаёт две активные карточки. Счётчик сообщений ≠ уникальные участники. Противоречащие наблюдения видны; посторонний не удаляет инцидент.
- **Handoff:** A возвращает typed ranked candidates; B публикует C2, позитивные/conflict fixtures и явный источник каждого статуса.
- **ARCH target для A-06/Product / Depends дополнительно A-15:** кандидаты ограничены tenant/домом/объектом до AI; приватные Report не копируются между чатами дома. Incident и его статусы не заменяются Ticket. Проверка: два tenant/два чата, race, чужие ID и сохранение исходных сообщений (MT-09/12/16).

### A-07 — подключение дома и разрешения группового режима
- **Evidence 18.09.2026:** A-07 existing-chat/ChatBinding backend IMPLEMENTED IN BRANCH `dev/b-experience`; [DEV-B](docs/status/dev-b.md), [CB-01…CB-22](scenarios/acceptance.md), [live checklist](docs/MAX_LIVE_SMOKE.md). NOT MERGED / NOT LIVE VERIFIED. Current accepted slice excludes quota, auto-group NLP and full admin UI; the broader target below does not assert those implemented.
- **Owner:** DEV-B. **P1 · M · Depends:** FND-01, A-01, A-15; B-01 и B-03 для реального MAX. Matching A-06 не prerequisite; полный web UI A-10/B-09 не нужен для проверки service boundary. **Allowed paths:** membership/chat binding services, API/admin, settings, DB, tests.
- **Сделать:** ConnectionRequest на tenant/дом с TTL/одноразовостью; разрешение УК → действие администратора чата → проверка текущих MAX-прав человека и бота → подтверждение дома УК → атомарная активация/лимит. Реестр установок и аудит; режимы explicit/group-auto/off, отзыв/смена чата. Дом допускает несколько чатов, активный групповой чат MVP — один дом. `bot_added` только начинает ожидание, не выдаёт роль.
- **Acceptance:** чужая ссылка не выдаёт доступ; админ одного дома не админ всех домов; удаление/отключение бота прекращает обработку группы. Для public synthetic demo доступ задан отдельной явной политикой. При отсутствии group entitlement доступны DM/QR/sharing.
- **Handoff:** C2 binding/settings, разрешённые действия и capability/error codes для bot/miniapp; все части остаются в product направлении DEV-B.
- **Граница / проверка:** три независимых основания — управление домом, назначение УК, MAX-права. Неуспешная проверка оставляет pending; название/URL/start_param не доказательства. Лимит активных домов/резерв защищён от race, повторное добавление требует проверки; каналы не принимаются как группы. MT-02…MT-10/17: API/PG negative+concurrency, transport fixtures и отдельно live MAX; fixtures не LIVE VERIFIED.

### A-08 — полезная LLM и evaluation, без зависимости основного пути
- **Owner:** DEV-A. **P1 conditional · M · Depends:** A-03/AI; разрешённый выбранный provider/ключ либо законный локальный доступ, допустимые данные и лицензии. LLM в принципе разрешено по Q&A, этот вопрос больше не блокер. **Allowed paths:** выделенные AI/NLP providers/prompts/validation, evaluation, dataset cards, AI regression tests.
- **Сделать:** structured slot extraction, ограниченное семантическое ранжирование кандидатов, один controlled repair, timeout/circuit breaker. Модель не определяет законный срок/адресата и не вызывает инструменты.
- **Acceptance:** invalid JSON, prompt injection, недоступный provider и расхождение методов дают clarification/rules fallback. Ни одна неподтверждённая деталь не попадает в готовый текст без пользователя. Evaluation фиксирует размер/происхождение набора и ошибки; при отсутствии real holdout так и написано.
- **Ограничение:** сначала один полезный AI-шаг. Training сложной модели, vector DB и универсальный RAG не часть этой задачи.

### A-09 — сопровождение: reminders, escalation, мои действия
- **Owner:** DEV-B. **P1 · M · Depends:** A-04/A-05/A-06/Product. **Allowed paths:** services/scheduling/appeals, API/contracts, общие jobs/outbox, DB, tests.
- **Сделать:** персональные/обоснованные нормативные напоминания, отмена/перенос, мои обращения, «нет ответа» → следующий допустимый маршрут/черновик с источником, история. Уведомлять только пользователя, которому разрешено отправлять DM.
- **Acceptance:** overdue не считается от произвольной даты чата; при неизвестном anchor нет ложного срока. После закрытия/смены версии лишнее напоминание не отправляется. Deadline тестируется fake clock, не ожиданием суток в CI. Эскалация — подготовка, а не автоматическая внешняя жалоба.
- **Handoff:** C3, reminder reason/time/source и states канала доставки для bot/miniapp того же product направления.
- **Ticket extension / PLANNED:** после A-16 использовать его события/попытку и контракт сроков A-02 для reminders; B-08 открывает актуальную карточку, A-05/B-03 доставляют. Это зависимость расширения, не перенос всех reminders в A-16.
- **ARCH target / Depends дополнительно A-15:** адресаты и записи tenant-scoped; актуальные полномочия/доступ/канал проверяются перед отправкой, не только при создании reminder. Проверка fake clock + отозванный сотрудник/приостановленная УК: доставки чужих данных нет, история/собственные обращения не удалены (MT-10/16).

### A-10 — backend веб-кабинета, заявки УК, лимиты и назначения
- **Owner:** DEV-B. **P1 · M · Depends:** A-15, A-02; A-07 для live состояния подключений, A-06/Product только для расширенных incident aggregates. Onboarding/settings не ждут matching. **Allowed paths:** admin API/services, summary queries, DB, `regions/`, tests.
- **Сделать:** два последовательных ограниченных этапа: (1) приглашения/web-auth, отзыв сессий и MFA привилегированных ролей, заявка УК → ручное решение Superadmin с основанием; (2) лимиты активных домов/резервы, назначения сотрудников на несколько домов, готовность дома, anti-spam/тихие часы, категории/режим, ограниченная модерация, сводка разрешённых домов и второй пакет региона. В исходном source есть RU-TA/RU-BA — сохраняем эти контексты с честным происхождением.
- **Acceptance:** агрегаты вычисляются из событий/БД, не чисел модели; у второго дома иной config без fork кода; ограничения адаптации показаны. Неудачный новый pack не ломает уже загруженную проверенную конфигурацию. Полная переписка не появляется в admin summary.
- **Handoff:** C3 settings+aggregates и два воспроизводимых demo fixtures для admin UI.
- **Граница / проверка:** отдельный web entry point использует существующие services/API; auth-механизм согласовать в этом срезе, не выдумывать MAX OAuth. Ticket mutations — A-16. API/PG tests: неутверждённая УК не получает дом, chat admin без org assignment не админ УК, лимит/смена назначения идемпотентны, агрегаты не раскрывают чужой tenant (MT-02/03/10/12/16). Каждый этап сдаётся отдельным проверяемым diff; не единый срез всей платформы.

### A-11 — расширение полезных маршрутов
- **Parent ID сохранён; P1 · M · Depends:** A-11/Product — A-02, A-03/Product и проверка данных; A-11/AI — A-03/AI и стабильные category codes от Product-среза. Реализация разделена.
- **A-11/Product — Owner DEV-B. Allowed paths:** `regions/`, product taxonomy/routing/contracts, fixtures/tests. **Сделать:** расширить четыре начальных проверенных маршрута до восьми, вести slots, applicability, source/provenance, safe unknown path, drafts и generated enums/labels.
- **A-11/AI — Owner DEV-A. Allowed paths:** category model support, datasets/evaluation/regression tests. **Сделать:** поддержать согласованные category codes и вопросы в extraction/classification; измерить ошибки отдельно от полноты нормативного маршрута.
- **Acceptance:** у каждой активной категории есть input slots, normal path, риск/неизвестность, основание, draft и тест. Нет проверенного источника → needs_verification и safe fallback. Model coverage или enum count не называется числом работающих сценариев.
- **Handoff:** B публикует стабильные codes/schema/source cards; A возвращает per-category evaluation и uncertainty. Маршрут и норматив остаются решением product backend.

### A-12 — production readiness и восстановление
- **Owner:** DEV-B. **P0 · L · Depends:** FND-01; B-03 для LIVE части; принятые P0 product-срезы. AI observability включается только для реально shipped AI. **Allowed paths:** `deploy/`, Compose, CI, settings/bootstrap, auth/security tests, runbook.
- **Сделать:** ранний HTTPS-стенд; отдельные local/test/prod credentials; logging sans secrets; health/readiness/version; backup/restore; миграции и безопасное повторное развёртывание; isolation/load sanity, защита демо-сброса. Не ждать 26.09 для первого deploy.
- **Acceptance:** свой image hash; нет автоизменения общего webhook при локальном старте; production не принимает test-login; restart сохраняет данные/jobs; restore проверен на отдельной БД. Порты API/DB не открыты в обход принятой политики. Нет обещания полного compliance одним расположением сервера.
- **Handoff:** стабильный URL, проверочные роли/дома безопасным каналом и список реально включённых функций для B-11/B-12; DEV-A получает только необходимые provider config/observability hooks без секретов.
- **Q&A target:** чистое воспроизведение без внешних секретов отделено от проверочного MAX-стенда. Reset только явно выбранной тестовой БД/Compose scope. С владельцем/партнёром согласовать раздельную retention policy для переписки, рабочей истории и юридически значимых запросов/ответов; общий короткий TTL не применять ко всем объектам (№416 п.38 при применимости).
- **ARCH target / MT-этап после A-15/A-07, очередь после A-16:** tenant scope в файлах, jobs, кешах, аналитике/экспорте; restore сохраняет историю и реестр установок. Проверка двух УК, отзыва, смены управления и restart (MT-10/12/16/17); ранний HTTPS/P0 не блокируется будущим Ticket. Без измерений нет обещания ёмкости или нового брокера.

### A-13 — воспроизводимая техническая сдача
- **Owner:** DEV-B. **P0 · M · Depends:** P0 и принятые P1; B-11. **Allowed paths:** README technical sections, OpenAPI/DATA-API, CI/release, deploy/runbook.
- **Сделать:** lockfiles/licenses/secret scan, frozen release и **проверяемый собственный API**: HTTPS base URL на период проверки, runtime OpenAPI 3.0/3.1 согласно ТЗ, безопасные проверочные учётные записи/доступы нужных ролей без админского bypass, изолированные тестовые данные, обязательные API-проверки и DATA-API.yaml по схеме организаторов. Шаблон отсутствует — недостающий вход, не самодельный official schema_version. Зафиксировать SHA/образ/стенд и измерение Docker build.
- **Acceptance:** [release checklist](README.md#чеклист-технической-сдачи--planned--not-run): чистый клон → документированная конфигурация → Docker → миграции → изолированные тестовые данные → проверки → restart без потери состояния. Один head миграций или объяснённое слияние; применённые миграции не переписаны. Сборка **не более 5 минут без первоначальной загрузки базовых образов**; shipped metadata совпадает. Локальное воспроизведение без секретов и рабочий MAX-стенд имеют отдельное evidence; transport=off не интеграция. Неизвестный DATA-API формат остаётся блокером сдачи этого файла.
- **Handoff:** единый release evidence для demo/слайдов, включая отдельные AI quality/latency/cost limitations от DEV-A, если AI вошёл в release. Не публиковать PDF с рабочими секретами в Git.

### A-14 — медиа как реальное расширение
- **Parent ID сохранён; P2 · M/L · Depends:** A-12 и готовность основных P1. B-13 — consumer/парный UX-срез, не prerequisite. Мультимодальность не обязательна ради загрузки DEV-A.
- **A-14/Product — Owner DEV-B. Allowed paths:** attachment service, private storage, public API/contracts, DB/access/retention, tests. **Сделать:** upload/read/delete, limits MIME/size, access, metadata policy и текстовый fallback.
- **A-14/AI — Owner DEV-A; Depends:** A-14/Product attachment boundary и реальный provider, только при согласованном roadmap. **Allowed paths:** ASR/vision provider adapters, prompts/structured validation, evaluation/tests. **Сделать:** вернуть редактируемую расшифровку/описание как предложение; timeout/failure не блокирует текст.
- **Acceptance:** bytes/storage/access реальны и изолированы; фото не считается диагнозом. Расшифровка редактируется до сохранения. Нет автопубликации личных фото или внешней отправки без основания. Недоступный provider даёт честный fallback, не synthetic production success.

### A-15 — минимальная tenant/access-основа
- **Owner:** DEV-B. **P0 foundation нового scope · M · State:** PASS / IMPLEMENTED IN BRANCH (18.09.2026), не MERGED TO MAIN. **Depends:** FND-01, A-01. **Allowed paths:** product core/services/contracts/API/DB, migrations, access tests; generated types одним согласованным diff.
- **Результат:** Tenant, HouseManagement с основанием/периодом, минимальные OrganizationMembership/HouseAssignment и resident basis; один сотрудник имеет несколько назначений. Объектная изоляция двух УК и отзыв прав, без повторного каркаса FND-01.
- **Границы:** минимальные подтверждаемые административные service-команды/seed fixtures для проверок; полноценный onboarding/web-auth/UI — A-10/B-09, MAX binding — A-07, Ticket — A-16. Нет IAM-конструктора и автоматического права из указанного адреса. Миграция сохраняет текущие C0 данные/личный путь, старый tenant истории не переписывает.
- **Acceptance / проверка:** API+PostgreSQL migration/restart и negative tests с двумя УК/домами, несколькими назначениями, чужими ID, отзывом и новым периодом управления; MT-01 (изоляция в локальном API, без claim LIVE MAX), MT-10/11/12/16/18. Read-model и allowed_actions отражают серверное основание доступа; old/new contract совместимы, OpenAPI/TS воспроизводимы.
- **Handoff:** проверенный access boundary и ограничения для B-02/A-07/A-10; будущие MT ещё не PASS, B-02 не закрывается автоматически.
- **A-15 evidence:** [DEV-B](docs/status/dev-b.md), `tests/integration/test_tenant_access.py` (MT-01…MT-10 текущего среза, отдельный namespace от полного ARCH MT), `test_migrations.py`; 27 unit/contract, 26 PostgreSQL integration, 73 frontend, 8 browser; Docker restart и local backup/restore PASS. B-02 binding подтверждён повторным прогоном. Полные target MT/Live MAX остаются NOT RUN/NOT VERIFIED.

### A-16 — Ticket: ограниченная очередь УК и проверка результата
- **Owner:** DEV-B. **P1 · M · State:** PASS / IMPLEMENTED IN BRANCH (18.09.2026), не MERGED TO MAIN. **Depends:** A-15, A-06/Product, A-10 (назначения/настройки), A-05, A-02 (контракт применимости/сроков). **Allowed paths:** product core/services/contracts/API/DB, migrations, worker wiring, contract/integration tests.
- **Результат:** Ticket поверх Incident с сохранением исходных Report, связей с заявителями и их индивидуальной истории; ExternalAppeal отделён. Стабильный внутренний номер/ID (не номер ГИС ЖКХ), создание/источник/management/house, история решений и работ. Для поддерживаемого процесса — ответственный либо резервная очередь и следующий шаг; неизвестная ответственность требует диспетчерской проверки, категория сама по себе не обязательство УК.
- **Попытки / проектирование:** WorkAttempt хранит конкретный отчёт о выполнении, ResultObservation привязан к конкретной попытке. Выполнение, проверка жителем и закрытие — разные факты. Позднее возражение к последней попытке сохраняется и после подтверждения другим жителем; согласованное правило: допустимый resolved без unresolved/rework закрывает; поздний unresolved последней попытки возобновляет тот же Ticket; после возражения нужна новая WorkAttempt.
- **События:** типизированные доменные события и notification intents; изменение Ticket + история + намерение уведомить атомарны через существующий transactional outbox. Сетевой send вне транзакции; MAX failure не откатывает работу. Новый broker не нужен; внешнее exactly-once не обещается. Delivery — A-05/B-03, карточки/callbacks/links — B-06/B-07, reminders — A-09/B-08; UI — B-14.
- **Границы:** lifecycle/DTO не заменяют Incident.status; overdue только по применимому сроку. A-02/A-11/Product дают контракт правил/данных: ответ / согласованная работа / следующее обновление / нормативный срок с основанием, типом и событием отсчёта. A-16 хранит факты; нормы не hardcode в state machine, универсальный due_at и новый SLA-engine не вводятся. Нет биллинга, полной CRM, автоматической внешней подачи/подтверждения по молчанию или голосованию. Фото — A-14/Product/B-13, отметка жителя не акт приёмки.
- **Acceptance / проверка backend — PASS:** MT-13/14/15 + MT-10/12/16/17 и [QA-проверки](scenarios/acceptance.md#qa-alignment--planned--not-run): один Incident без дубля активных Ticket; repeat без новой WorkAttempt; чужой scope закрыт; race/stale безопасны; rollback без ложного intent; intents остаются pending без нового sender; reload/restart сохраняют историю; resident projection без internal-only; текст/срок/номер не внешнее подтверждение. Реализация разрешена владельцем по A16_TICKET_BACKEND_CODEX.md. B-14/delivery/live не входят в выполненный срез.
- **Handoff:** реальные Ticket DTO/actions, generated schema, позитивные/negative fixtures и evidence для B-14; не placeholder success.

- **A-16 evidence:** [DEV-B handoff](docs/status/dev-b.md), TK-01…TK-26 в [acceptance](scenarios/acceptance.md#a-16--backend-evidence-18092026): migration 0004; 53 unit/contract, 97 PostgreSQL integration (32 новых A-16), 73 frontend, 8 B-02 browser; OpenAPI/TS drift и Docker smoke PASS. Семантический matching отсутствует; normative deadline недоступен без проверенного A-02; outbox pending без MAX delivery. Предыдущие A-01/A-15/A-07/B-02 regression PASS; main/live статусы не повышены.

## 7. Исторические B-ID — Owner DEV-B

### B-00 — UX-контракт и acceptance-сценарии до каркаса
- **Owner / authorship:** DEV-B. **P0 · S · Depends:** S0-01; начать параллельно BOOT-01/FND-01. **Allowed paths:** `docs/UX.md`, `scenarios/acceptance.md`. Завершённое evidence сохраняется в status DEV-B.
- **Сделать:** 5 основных экранов, пути и тексты source/status/ошибок; согласовать потребности C1; матрица сценариев раздела 9. До merge FND-01 не создавать конкурирующий scaffold miniapp.
- **Acceptance:** личный сценарий понятен без группового доступа; черновик редактируется; кнопка «подал» не выдаёт внешнюю регистрацию; определены mobile/web/loading/empty/error/unauthorized. Зависимые страницы не обещают несуществующий endpoint.
- **Handoff:** краткие требования DTO/allowed_actions в A-01 product contract; DEV-B теперь writer producer и consumer, DEV-A review AI boundary/invariants.

### B-01 — MAX feasibility и реальное окружение
- **Owner:** DEV-B. **P0 · S/M · Depends:** доступ к разрешённому боту/организаторам; часть можно до FND-01. **Allowed paths:** `docs/decisions.md` согласованным diff, короткие integration evidence.
- **Сделать:** сверить официальные docs; права добавления/чтения группы; DM events, deep link, mini app on mobile/web; получить реальный пример initData для локального безопасного теста; проверить sharing capability. Не хранить raw initData/token в Git.
- **Acceptance:** таблица LIVE VERIFIED / NOT VERIFIED / BLOCKED; разрешение group доказано фактическим событием, не предположением из SDK. При отсутствии доступа выбран fallback. Подписка общего токена не перенастроена чужим окружением.
- **Handoff:** нормализованные обезличенные forms/events и утверждённые configuration requirements для product backend; AI receives only explicitly allowed content if a later feature needs it.
- **ARCH target / проверка:** текущие методы admins/member/me, реальные sender/chat context, bot_added/removal и права; документальные источники M1–M12 отдельно от токена/live evidence. Условия linking/сервисных уведомлений и пределы подтверждаются до использования; неполученные доступы не блокируют docs/A-01 и не дают LIVE VERIFIED.
- **Q&A target:** реальные Web/iOS/Android проверки цепочки Ticket→MAX→Mini App→ResultObservation по [live smoke](docs/MAX_LIVE_SMOKE.md) после готовности A-16/B-14 и delivery; сейчас NOT RUN / PENDING TOKEN.

### B-02 — визуальная система и рабочая mini app
- **Owner:** DEV-B. **P0 · M · Depends:** FND-01/C0; B-00; A-01 convergence для обновлённого binding; A-15 для нового tenant/access context. Полная платформа/кабинет/Ticket не входят в B-02. **Allowed paths:** `miniapp/src/app/`, `shared/`, `features/incidents/`, frontend/browser tests.
- **Сделать:** consistent tokens/типографика/отступы; House board, Incident detail, ясные badges, source chip, responsive lists, loading/empty/error/access states; MAX Bridge wrapper с capability detection.
- **Acceptance:** реальные API данные и reload; действия доступны по allowed_actions; тема/контраст/фокус/клавиатура; на web нет обязательного mobile-only Bridge метода. Длинный адрес/текст/неизвестный enum не ломают layout.
- **State / evidence (18.09.2026): DONE · IMPLEMENTED IN BRANCH** для текущего board/detail/manual C0.1 binding после A-01 и повторных frontend/PostgreSQL/browser checks ([dev-b](docs/status/dev-b.md)). Producer blocker снят. Будущий tenant binding после A-15 остаётся отдельной проверкой; live MAX NOT VERIFIED, merge A-01 в main не выполнен.
- **Не нужно:** Storybook/platform для компонентов, если достаточно лёгкой dev-страницы и component tests.
- **ARCH target / сохранение evidence:** одна Mini App всех домов; пять экранов B-00 и реальный C0 manual report не заменяются новым scaffold. После A-15 проверить явный выбор разрешённого дома/утрату scope (MT-11/18), generated fields/actions и прежние C-сценарии; live MAX web/mobile фиксируется отдельно от браузерной эмуляции. `c4492dd` и существующие результаты сохраняются.

### B-03 — MAX transport, ingress и отправка
- **Owner:** DEV-B. **P0 · L · Depends:** FND-01 и transport port из C0; B-01 для LIVE проверки. A-05 — интеграция общей delivery-инфраструктуры, не условие начала. **Allowed paths:** `src/domsignal/bot/`, MAX API/ingress adapters, bot tests, MAX scenario fixtures.
- **Сделать:** HTTPX client ограниченных проверенных методов; send/edit/callback answer; webhook normalization и типы событий; корректные ID/время; links; 429/5xx/network errors; recording adapter используется только тестово/off.
- **Acceptance:** настоящее сообщение и изменение карточки в MAX; bot-loop отбрасывается; подпись/secret ошибки rejected; повтор/редактирование не смешиваются; разрешённая библиотека/корни сертификатов, TLS verification не отключён. Невыясненная доставка не называется подтверждённой.
- **Handoff:** конкретный transport/handler и product-level wiring выполняет DEV-B одним срезом; DEV-A не ожидается для общего composition root.
- **Q&A target:** send/edit и callback response сверять по [MAX methods](docs/MAX_LIVE_SMOKE.md#методы-max--документальная-сверка-18092026): лимиты, тело ответа (включая success=false при HTTP 200), неизвестный результат. Принятие API не прочтение человеком; реализацию доставки A-07 не доказывает.
- **ARCH target:** normalized события установки/отзыва и реальные sender/chat IDs передаются в A-07 без выдачи роли от bot_added; transport сам не активирует дом. Проверка recording/contract и отдельно live события с выданным токеном; повтор/сбой MAX не становятся успешным подключением (MT-04/08/17).

### B-04 — личный бот как законченный продукт
- **Owner:** DEV-B. **P0 · L · Depends:** A-01, A-02, A-03/Product, A-04, B-03. A-03/AI подключается как optional enhancement, не блокирует manual path.
- **Allowed paths:** `src/domsignal/bot/`, product services/API clients, bot scenario tests.
- **Сделать:** /start, выбор дома/контекста, свободный текст или категория, safety-off-ramp, максимум полезных уточнений, маршрут+источник, draft preview, clipboard/link, «житель отметил подачу», возврат к текущему шагу, /help и версия для проверки.
- **Acceptance:** путь заканчивается сохранённым состоянием и понятным следующим действием; restart/timeout не заставляет повторять всё; deep link сохраняет контекст, но не даёт права. Работает без LLM и группы. Нажатие «открыть официальный сервис» не отправляет автоматически текст третьей стороне.
- **Проверка:** real MAX web+mobile, synthetic fixture data явны; без реального внешнего обращения пользователя тестируется только handoff и self-report, не выдуманная регистрация.

### B-05 — редактор обращения и мои действия
- **Owner:** DEV-B. **P0 · M · Depends:** A-01/A-04; B-02.
- **Allowed paths:** `miniapp/src/features/appeals/`, onboarding/shared API client, UI/e2e tests.
- **Сделать:** route panel, объяснение источника/ограничения, draft edit с autosave/debounce, preview, copy/open external, возвращение из MAX, self-reported number/date, мои черновики/действия. Autosave и submit не создают гонку потери текста.
- **Acceptance:** изменения переживают reload; 409 предлагает восстановить/сопоставить, не стирает текст; отсутствие due_at понятно; пользователь редактирует только своё. Внешний переход виден и инициируется человеком; test markers читаемы, но не загромождают каждый экран.

### B-06 — «одна карточка вместо шума»
- **Owner:** DEV-B. **P1 · M · Depends:** B-03, A-06/Product, A-07; реальный group gate B-01. A-06/AI ranking optional и не принимает merge decision.
- **Allowed paths:** `src/domsignal/bot/`, product services/cards/group handlers, scenario tests.
- **Сделать:** карточка общего инцидента; edit вместо повторного постинга; меня касается/не проблема; допустимое уточнение; anti-spam/quiet-hours и права; реакция на removal/edit.
- **Acceptance:** два пользователя видят одну историю; counts правильные; устаревшая кнопка не портит состояние; отключение auto-mode работает. После ручного удаления карточки не начинать бесконечный repost против намерения администратора. При снятии прав нет бесконечных retry.
- **Fallback:** если group blocked, усиливать B-07/B-08 вместо ложного «работает за флагом».
- **Ticket extension / PLANNED:** после A-16 — актуальная общая карточка и callbacks с повторной проверкой actor/scope/попытки. Приватные комментарии/контакты в группу не попадают. Текущий A-07 принимает только явную `/report`; auto-анализ переписки этим планом не разрешается.

### B-07 — контекст между MAX-пространствами, sharing и QR
- **Owner:** DEV-B. **P1 · M · Depends:** B-02/B-04; A-07; B-01 capabilities.
- **Allowed paths:** bot links, `miniapp/src/shared/max/`, onboarding/share, product access services/tests.
- **Сделать:** group→DM→mini app на том же инциденте; нативный sharing проверенным методом MAX; короткий opaque deep link; QR дома/подъезда и текстовая ссылка как web fallback.
- **Acceptance:** второй пользователь проходит доступ и присоединяется; ссылка не раскрывает private данные/не выдаёт membership сама. На web fallback реально работает; QR даёт контекст, а не auth. Payload соблюдает проверенные ограничения платформы.
- **Бонус:** это кандидат на +0,15, а не гарантированное начисление; показывается путь от действия до результата двух людей.
- **Ticket extension / PLANNED:** после A-16/B-14 — ссылка на соответствующую карточку, свежий API read при открытии; ссылка не grant и не mutation. Sharing cancel не отправка, mobile-only методы имеют рабочую ссылку/копирование как fallback.
- **ARCH target:** мастер подтверждения ConnectionRequest по A-07, подписанная идентичность подключающего и явный дом; приглашённый admin чата не получает кабинет/роль УК. Проверка MT-05/06/07/11/19: чужой/replayed/expired контекст отклонён, Mini App вне чата и web fallback не угадывают дом. Нет копирования приватного текста между чатами.

### B-08 — история, результаты и следующий шаг
- **Owner:** DEV-B. **P1 · M · Depends:** A-06/Product, A-09; B-02/B-04.
- **Allowed paths:** miniapp incident/appeal features, bot reminder/feedback cards, product API integration.
- **Сделать:** timeline, «решено/осталось», расхождение наблюдений, новый связанный случай, reminder settings, «нет ответа» → проверяемый следующий маршрут/preview.
- **Acceptance:** статус не скрывает источник; старое «решено» не переносится на новый случай; ручная отметка filing не выглядит ответом УК; пустой/неприменимый нормативный срок не заменяется случайным отсчётом. Напоминание открывает актуальный экран и правильный incident.

### B-09 — отдельный веб-кабинет: подключение и готовность дома
- **Owner:** DEV-B. **P1 · M · Depends:** A-07/A-10; B-02.
- **Allowed paths:** отдельный web entry point в текущем frontend toolchain (точный путь выбрать по foundation), shared product API client, component/e2e tests; docs/UX. Не создавать вторую backend-платформу или конкурирующий scaffold.
- **Сделать:** обычный браузерный кабинет без Bridge: Superadmin рассматривает заявки УК/лимиты/споры; администратор УК ведёт дома/сотрудников/назначения; ответственный видит свои дома. Готовность дома, состояние проверенного чата, режим/quiet hours, реальные aggregates и допустимая модерация. Очередь и карточка Ticket — отдельная B-14.
- **Acceptance:** одной настройкой отключается auto-react; последствия понятны; ошибка сохранения не показывается как успех. Нет чужих домов/личных текстов/общей выгрузки чата. Role-switcher не подменяет серверную авторизацию.
- **Не нужно:** большая CRM с персоналом/нарядами, универсальный конструктор дашбордов.
- **Проверка:** browser E2E с реальным A-10/A-07 API и двумя tenant, без window.WebApp; loading/empty/error/401/403/409, клавиатура, отзыв назначения и отсутствие чужих домов. C39–C41, MT-02/03/10/12/19; UI не имитирует неподключённый backend. Авторизованный админ чата видит только мастер подключения, если нет org role.

### B-10 — UX/UI polish без новых бизнес-зависимостей
- **Owner:** DEV-B. **P1 · M · Depends:** основные экраны B-02/B-05; выполняется частями до freeze.
- **Allowed paths:** `miniapp/src/shared/styles/`, shared UI, affected features, UX tests.
- **Сделать:** читаемая мобильная композиция, visual hierarchy, skeletons, сохранение фильтра/позиции, feedback кнопки, return/back, длинные тексты, empty states с действием. Убрать лишние запросы и мигание, измерив поведение.
- **Acceptance:** основной путь проходит без объяснений; focus/контраст/клавиатура проверены; layout не зависит от одного размера телефона; нет обязательных анимаций/blur, мешающих доступности. Фотографии/скриншоты теста отделены от реальных исследовательских данных.

### B-11 — сквозной bug bash и проверки клиентов
- **Owner:** DEV-B. **P0 · L · Depends:** первые end-to-end части S2; продолжать до S6.
- **Allowed paths:** `miniapp/tests/`, product scenarios, короткий release evidence. Bug fix делает владелец соответствующей зоны; AI defect возвращается DEV-A.
- **Сделать:** автоматизировать продуктовые сценарии раздела 9; negative cases раздела 10; запуск на реальном API/PG; реальные MAX mobile/web smoke с двумя ролями. Независимый участник проходит README без подсказок.
- **Acceptance:** проверены не только happy screenshots; flaky тесты разобраны, не отключены. Синтетический replay не маркируется LIVE MAX. Сеть/provider и неизвестный адрес дают понятный следующий шаг. Итоги записаны с датой, commit и ограничениями, без выдуманного количества тестировщиков.
- **ARCH target:** MT-01…MT-20 в существующей acceptance matrix; предусловия, роли, ошибки и evidence фиксируются по мере готовности соответствующих A-15/A-07/A-10/A-16/B-09/B-14. Непрогнанные проверки остаются NOT RUN, локальный API/browser прогон не выдаётся за LIVE MAX.

### B-12 — демонстрация и продуктовый комплект сдачи
- **Owner:** DEV-B. **P0 · M · Depends:** B-11; A-13 того же направления.
- **Allowed paths:** README user sections, demo/runbook, материалы презентации согласно правилам доступа.
- **Сделать:** сценарий 2–3 минуты, два пользователя, резервное видео того же release, инструкция reset только своего demo scope, evidence matrix real/test/planned. Слайды продукта и польза MAX; согласовать факты с источниками/исследователем.
- **Acceptance:** видео показывает существующие функции; на слайде не говорится «официально подано», если был только self-report. Technical slide с рабочими доступами не публикуется в Git. Все URL/hash/ограничения согласованы с A-13.

### B-13 — UX для фото и голоса
- **Owner:** DEV-B. **P2 · M · Depends:** A-14/Product; B-10; основные P1 проходят. A-14/AI нужен только для реально принятого ASR/vision enhancement.
- **Allowed paths:** miniapp media UI, bot attachment normalization, product API integration, tests.
- **Сделать:** прикрепление/превью/удаление изображения; при реальном ASR — запись или разрешённое вложение → редактируемый текст. Progress/cancel/retry, лимиты и доступность.
- **Acceptance:** photo upload и transcript provider не имитируются. При сбое пользователь вводит текст, черновик сохраняется. Распознавание не публикует вывод без подтверждения; недоступный микрофон не ломает страницу.

### B-14 — рабочая очередь и карточка Ticket в веб-кабинете
- **Owner:** DEV-B. **P1 · M · State:** TARGET / TODO. **Depends:** A-16, B-09; B-02 для resident projection. **Allowed paths:** web queue/ticket features в выбранном B-09 entry point, resident Incident Detail, shared API client, UX и browser/component tests.
- **Результат:** разрешённая очередь, фильтры/владелец следующего шага, принятие заявки, комментарий и отчёт исполнителя; отдельное наблюдение/возражение жителя в существующем Incident Detail. Все mutations идут через реальные actions A-16.
- **Границы:** не дублировать B-02 board/detail, B-08 историю/напоминания и B-09 onboarding/settings. Не выводить рабочие права из Incident.status; не показывать Ticket как внешнюю регистрацию. Нет фальшивого приёма при неактивной УК/очереди.
- **Acceptance / проверка:** browser → реальный API/PG, MT-13/14/15/19/20 плюс чужой scope MT-12; работник видит только назначения, конфликт принятия обновляет владельца, неподдержанное действие отсутствует, отчёт и возражение раздельны. Кабинет работает без Bridge; resident result проверяется отдельно в MAX web/mobile, отсутствие live записывается NOT VERIFIED.
- **Handoff:** evidence queue→work report→resident response с ref/ролями и ограничениями, без автоматического закрытия прежних B-задач.
- **Q&A target:** рабочий и пользовательский UI различают WorkAttempt, ResultObservation, закрытие и delivery state, показывают виды/основания сроков. Позднее возражение не теряется из-за чужого подтверждения. [Сквозной MAX-путь](docs/PRODUCT_ARCHITECTURE.md#сквозной-max-путь--planned) зависит также от A-05/B-03/B-06/B-07/A-09/B-08 и live gate B-01; delivery не входит целиком в A-16/B-14.

## 8. Kill-фичи и их минимальные доказательства

| Фича | Почему полезна | Task slices / Owner | Что показывает завершённость |
|---|---|---|---|
| **Общая проблема без спама** | Соседи перестают заново собирать историю | DEV-B: A-06/Product, A-07, B-06; DEV-A: optional A-06/AI ranking | Два независимых сигнала → одна актуальная карточка, отдельные сообщения сохранены |
| **Маршрут с объяснением + готовый редактируемый текст** | Не нужно угадывать адресата и писать с нуля | DEV-B: A-02, A-04, B-04/B-05 | Неполное описание → уточнение → основание → сохранённый draft → handoff |
| **Тот же инцидент в чате, DM и mini app** | Нет повторного ввода и потери контекста | DEV-B: A-07, B-07 | Переходы с реальным доступом и вторым пользователем в MAX |
| **Не «закрыто», а история наблюдений и следующий шаг** | Становится видно, что известно и что нужно проверить | DEV-B: A-06/Product, A-09, B-08 | Self-report, reminder, противоречие, recurrence без подмены статуса |
| **Новый дом/регион без fork кода** | Видно, как переносится продукт | DEV-B: A-10, A-11/Product, B-09; DEV-A: A-11/AI evaluation | Два config набора, один код и различающиеся реальные данные/явная синтетика |
| **Голос/фото → черновик** | Дополнительный простой вход | DEV-B: A-14/Product, B-13; DEV-A: A-14/AI только с provider, P2 | Настоящий provider/attachment, редактирование и понятный fallback |

Последняя строка не должна вытеснить первые четыре. Групповое автообнаружение возможно только при реальных правах и согласованном процессе; иначе остаётся осмысленный «поделиться и присоединиться».

## 9. Каталог продуктовых сценариев

**Десять основных кандидатов + два условных расширения.** Это цели acceptance, не сообщение о количестве уже реализованных функций. Технические ошибки следующего раздела не прибавляем к числу продуктовых сценариев.

| ID / приоритет | START → полезный результат | Ответственные задачи / Owner | Доказательство / тест |
|---|---|---|---|
| **SC-01 / P0** | Житель пишет в DM → уточнение → источник адресата → отредактированный draft → handoff → сохранённая отметка | DEV-B: A-02, A-03/Product, A-04, B-03/B-04/B-05; DEV-A: A-03/AI enhancement | Реальный MAX + запись API/PG; reload показывает ту же историю |
| **SC-02 / P0** | Житель открывает mini app → находит нужную проблему → видит актуальный маршрут/свои действия | DEV-B maintenance: FND-01, A-04, B-02/B-05 | E2E против настоящего backend; forbidden house negative |
| **SC-03 / P0** | Возможный риск в сообщении → немедленный безопасный off-ramp без ожидания LLM | DEV-A: A-03/AI risk signal; DEV-B: A-03/Product, A-05, B-04 safety priority | Safety fixtures + проверка задержки/порядка действий; без обещания устранения аварии |
| **SC-04 / P1 group gate** | Два соседа сообщают в группе об одном объекте → одна карточка + корректные counts | DEV-B: A-06/Product, A-07, B-06; DEV-A: optional A-06/AI | Два пользователя; race и разные подъезды отдельно |
| **SC-05 / P1** | Сосед получает ссылку/QR → контекст → разрешённый вход → присоединение к инциденту | DEV-B: A-07, B-07 | Mobile/web, чужая ссылка не даёт private access |
| **SC-06 / P1** | Пользователь отметил подачу → настроил напоминание → нет ответа → подготовил следующий шаг | DEV-B: A-09, B-08 | Fake clock для автоматизации + настоящее уведомление в MAX |
| **SC-07 / P1** | Житель сообщил об устранении → сосед возразил → видна необходимость проверки; новый случай связан со старым | DEV-B: A-06/Product, B-08 | Наблюдения/версии сохранены, спор не решён большинством голосов |
| **SC-08 / P1** | УК разрешила подключение → администратор чата подтвердил права → дом активирован → сотрудник настроил режим/тишину в web-кабинете → отключил бота | DEV-B: A-07/A-10, B-09 | Scoped admin E2E и остановка group processing |
| **SC-09 / P1** | Тот же тип проблемы в другом demo-регионе → иной source/config → корректный путь без изменения кода | DEV-B: A-10/A-11 Product, B-05/B-09; DEV-A: A-11/AI evaluation | Параметризованный тест двух пакетов; происхождение данных видно |
| **SC-10 / P1** | Неполное/разговорное сообщение → уточнение → пользователь исправил распознавание → нормальный путь | DEV-A: A-03/AI, optional A-08; DEV-B: A-03/Product, B-04/B-05 | Rules/manual и optional provider проходят один boundary, неизвестность не скрывается |
| **SC-11 / P2** | Пользователь приложил фото → просмотрел/удалил → отправил выбранный материал с сигналом | DEV-B: A-14/Product, B-13 | Настоящие bytes/storage/access; нет автоматической публикации в группу |
| **SC-12 / P2** | Голос → настоящая расшифровка → исправление → draft/сигнал | DEV-A: A-14/AI provider; DEV-B: A-14/Product, B-13 | Live provider evidence; текстовый fallback при отказе |

### Покрытие категорий — отдельная ось

Исходная таксономия из § 6.4 сохраняется как каталог: лифт, стояк, крыша, горячая вода, отопление, канализация, мусоропровод, ТКО, освещение, уборка, двор, сосульки, домофон, шум, газ, другое. Это **не шестнадцать гарантированно проверенных правовых маршрутов**.

Для P0 планируем четыре полноценных неэкстренных пути: лифт без признаков угрозы людям, освещение без признаков электрической опасности, уборка подъезда, отсутствие горячей воды. Для P1 целимся в восемь: добавить ТКО, протечку крыши, домофон и дефект дворовой территории — только с вопросами о применимости и проверенными данными. DEV-B владеет маршрутами/пакетами и safety policy; DEV-A — model support/evaluation категорий. Риски в любом пути переводят в safety-off-ramp. Выбор первых четырёх можно изменить после интервью; task IDs не меняются.

«Маршрут готов» означает: распознавание/ручной выбор, недостающие поля, граница ответственности, основание/неопределённость, draft, handoff, сохранение, тест позитивной и проблемной ветки. Одного нового enum недостаточно.

## 10. Матрица устойчивости и безопасности

Каждый пункт входит в задачу владельца, а B-11 проверяет связку. Не откладывать всю матрицу на последний день.

| ID | Ситуация | Обязательное поведение | Основной owner |
|---|---|---|---|
| N-01 | Неизвестный дом | Черновик/следующий шаг; нет случайной УК | DEV-B — A-02/B-04 |
| N-02 | Невалидный initData / повтор ключей / истёкший срок | Отказ без утечки деталей и безопасный повтор входа | DEV-B — FND maintenance/A-12 |
| N-03 | Публичный deep link на чужой дом | Навигация не выдаёт членство | DEV-B — A-07/B-07 |
| N-04 | Повтор webhook / callback | Один доменный эффект | DEV-B — A-05/B-03 |
| N-05 | DB сбой до commit входящего события | Нет ложного accepted, можно повторить | DEV-B — A-05 |
| N-06 | Два сигнала одновременно | Предсказуемый matching без двух конфликтующих карточек | DEV-B — A-06/Product; DEV-A только candidate ranking |
| N-07 | У двух лифтов неизвестен подъезд | Уточнение, а не merge разных объектов | DEV-B — A-06/Product/B-06; DEV-A возвращает uncertainty |
| N-08 | Нажатие старой кнопки/версия draft | 409/актуализация, текст не теряется | DEV-B — A-04/B-05 |
| N-09 | MAX 429/5xx/timeout | Retry/очередь, доменный статус не подделывается | DEV-B — A-05/B-03 |
| N-10 | Ответ send потерян | Не обещать exactly-once; зафиксировать неопределённость/политику retry | DEV-B — A-05/B-03 |
| N-11 | Worker умер после claim | Lease recovery, устаревший worker не коммитит чужую задачу | DEV-B — A-05 |
| N-12 | LLM не отвечает / invalid JSON / injection | Без tools; rules/manual; без ложных нормативов | DEV-A — A-08 provider/fallback signal; DEV-B — product fallback/B-04 |
| N-13 | Источник/срок не проверен | needs_verification, due_at отсутствует, причина видна | DEV-B — A-02/B-05 |
| N-14 | Бота удалили/сняли права | Остановка группы и ошибочных повторов; DM fallback | DEV-B — A-07/B-06 |
| N-15 | Пользователь прервал ввод | Минимальное session state восстановлено | DEV-B — A-04/B-04/B-05 |
| N-16 | «Решено» и «не решено» одновременно | Видимое расхождение, аудит, не автоистина | DEV-B — A-06/Product/B-08 |
| N-17 | Перезапуск/повторная миграция/seed | Данные не исчезают; нет повторного создания справочников | DEV-B — A-12 |
| N-18 | Критичная возможность Bridge отсутствует | Рабочий web-compatible путь | DEV-B — B-02/B-07 |
| N-19 | Demo reset другого пользователя | Нет доступа к чужим данным/текущей проверке | DEV-B — A-12/B-12 |
| N-20 | Фото oversized/private или ASR fail | Валидация/403, текстовый fallback, draft сохранён | DEV-B — storage/access/UI; DEV-A — optional ASR/vision provider failure |

## 11. Definition of Done и правила интеграции

Карточка считается **реализованной в ветке**, когда acceptance выполнены и прошли соответствующие тесты. **MERGED** — только после PR в актуальный main. **LIVE VERIFIED** — после настоящего внешнего прогона с указанным commit/клиентом. Эти три состояния нельзя смешивать.

Для каждого продуктового API обязателен [общий DoD](docs/CONTRACTS.md#definition-of-done-продуктовых-api): runtime OpenAPI/generated TS, auth/scope/actions, чтение сохранённого результата, idempotency/timeout/conflict, concurrency/stale и безопасные Problem Details. Evidence разделяется на A (unit/contract), B (реальный HTTP/PG/services/worker) и C (live MAX/LLM); A/B не заменяют C. Новые требования Q&A — PLANNED / NOT RUN, прежние PASS не повышаются. Для docs-only diff достаточно diff/ссылок/repository-sanity без тяжёлого продуктового прогона; перед main обязательный CI сохраняется.

Для готового PR достаточно шести коротких блоков: task IDs; изменение; contracts/migrations; проверки; manual path; ограничения. Скриншот для UX-изменения — полезное доказательство, но не требуется для правки чистого domain helper.

Проверки по риску:
- Локальная функция → targeted unit; bug → regression.
- DTO/route → producer+consumer+contract; генерируемые types должны совпасть.
- AI internal contract → invalid/timeout/fallback + evaluation regression; product validation и transaction проверяются отдельно владельцем DEV-B.
- DB/matching/job/auth → настоящие PostgreSQL integration и отрицательные ветки, не замена SQLite.
- UI → component + связанный E2E/браузер; не только build.
- MAX → recording contract tests и отдельный LIVE smoke; не считать первый заменой второго.
- Main → актуальный merge-result CI и review второго разработчика; DEV-A обязательно review PR DEV-B, а интегратор DEV-B не обходит protection; после двух связанных merge — общий smoke.

В готовый PR не попадает незавершённая следующая фича из постоянной ветки. Параллельную работу держим локально отдельно. Не создавать новую обязательную ветку для каждого сценария и не переводить команду на сложный Gitflow.

**Скрытый флаг не освобождает от безопасности.** P2 backend может оставаться выключенным, но код, включённый в main, не должен обходить auth или ломать миграции. UI показывает только реально поддержанные capabilities.

## 12. Корректировка курса без переписывания плана

Roadmap — спецификация и зависимости. Текущая работа: `docs/status/dev-a.md` и `dev-b.md` на ветках владельцев; история завершения — merged PR. Не проставлять вручную одинаковые статусы ещё в трёх местах.

При изменении задачи:
1. Сохранить ID; изменить только её результат/acceptance/dependencies/priority.
2. Для owner change записать прежнего и нового владельца в короткое решение, сообщить коллеге.
3. Если меняется общий контракт, сначала маленький согласованный PR и fixtures; совместимые additions предпочтительнее удаления полей.
4. Для отмены отметить DEFERRED в handoff/решении с причиной, не удалять доказательства уже выполненной части.
5. Интегратор DEV-B обновляет общий контекст только когда это меняет общую картину, по проверенному main/ref и без отчёта на каждую строку кода.

Шаблон новой карточки:

```markdown
### <исторический префикс>-<новый ID> — пользовательский результат
- Priority / size / explicit Owner:
- Depends:
- Allowed paths:
- Сделать:
- Acceptance + проверки:
- Handoff / ограничения:
```

### Условия изменения объёма

| Триггер | Действие |
|---|---|
| Нет group rights | Не ждать неделями: DEV-B откладывает B-06 auto-group; A-07/B-07 access/sharing остаются; P0 не меняется |
| Нет доступа к выбранному допустимому provider/реальной выборки | LLM в принципе разрешено по Q&A. DEV-A поставляет проверяемый baseline/fixtures; release идёт rules/manual, без выдуманной measured ML quality |
| Не проверены нормы части категорий | DEV-B сокращает активные маршруты, сохраняет explicit unknown path; не подставляет универсальную УК/10 дней |
| B-02 расходится с producer C0 | DEV-B сначала делает минимальный A-01 producer+consumer convergence; DEV-A review, но не становится writer общего backend |
| P0 не проходит на 21.09 | DEV-B останавливает P2 и неготовые P1; команда парно проверяет критический путь и AI fallback |
| DEV-A исчерпал полезные AI-задачи | Не добавлять RAG/vector DB/сложное обучение; усилить evaluation/regression/latency-cost evidence или помочь review без смены ownership |
| DEV-B перегружен product/fullstack/MAX | Порядок срезов: A-01 convergence → A-15 access → B-02 binding/personal golden path → проверенное подключение/кабинет → A-16/B-14 очередь → reliability/release; P2 после принятых P1; агенты делят UI/bot/backend только по непересекающимся paths |
| Все P0/P1 зелёные до freeze, есть ресурс review | Взять A-14/Product и B-13 сначала attachments; ASR/vision — только после настоящей provider проверки A-14/AI |

## 13. Что не входит даже при быстрых агентах

Подача от имени гражданина в ГИС ЖКХ без официального доступа; фальшивые external IDs; оплата/счётчики/ОСС; полноценная диспетчерская CRM; хранение всех чатов; автоматическая диагностика аварий; универсальный юридический советчик; инфраструктура «на будущее»; статистика из синтетических интервью под видом real research; автоматический ночной push или изменение стенда проверки.

## 14. Связь с материалами

- [docs/PRODUCT_ARCHITECTURE.md](docs/PRODUCT_ARCHITECTURE.md) — единственная согласованная продуктовая/системная цель ARCH-PLATFORM-v1; TARGET, не отчёт.

- `docs/product/domsignal_plan.md` — исходное обоснование; в выданном комплекте это `source/domsignal_plan.md`.
- `01_CODEX_REPOSITORY_BOOTSTRAP.md` — промпт настройки repo; после выполнения постоянные правила находятся в root/WORKFLOW, не нужно перечитывать bootstrap.
- `02_CODEX_ARCHITECTURE_FOUNDATION.md` — второй промпт; после выполнения текущая архитектура находится в `docs/ARCHITECTURE.md`.
- `IMPLEMENTATION_CONTEXT.md` — коротко, что реально есть на main.

При копировании этого roadmap в репозиторий bootstrap-промпты не обязаны храниться внутри: названия выше — справочные названия файлов выданного комплекта, не обязательные зависимости для ежедневной работы.
