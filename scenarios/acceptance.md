# ДомСигнал — acceptance matrix B-00

## Статус и правила чтения

Q&A уточнения — [журнал решений](../docs/decisions.md#qa-alignment-2026-09-18).
Новая матрица ниже PLANNED / NOT RUN; прежние C/MT/CB IDs и результаты сохранены.

## QA alignment — PLANNED / NOT RUN

Уровни evidence: **A** unit/contract с тестовыми адаптерами/записанными входами;
**B** integration с настоящим HTTP, services, PostgreSQL и worker;
**C** live MAX с реальными провайдером/клиентами и отдельно live LLM для принятой
AI-функции. HTTPX MockTransport/ASGI in-process сам по себе не доказывает внешний
HTTP/live. A/B не заменяют C. Нет токена — NOT RUN / PENDING TOKEN, даже если
transport=off/recording и локальный стек прошли проверки.

Для A-16 предусловия: реализованный согласованный срез, две УК/два дома,
сотрудник с назначением, два разрешённых жителя, чужой actor и конкретные
Incident/Ticket/WorkAttempt. До его реализации все строки остаются NOT RUN.
При выполнении фиксировать ref, роли/scope, данные, ожидаемый/фактический результат,
команду и уровень evidence. Таблица уточняет существующие задачи, не создаёт новые.

| ID | Задачи / Owner | Шаг и ожидаемый результат | Evidence | Статус |
|---|---|---|---|---|
| QA-01 | A-13/B-11, все product API / DEV-B | Проверить runtime OpenAPI requests/responses/status/headers/required fields, generated TS без drift; auth/tenant/house/allowed_actions, действующие Problem Details без private/secrets. Успешную запись подтвердить отдельным API read. | A + B | PLANNED / NOT RUN |
| QA-02 | A-16/A-06/Product / DEV-B | Два сообщения одного дефекта и race создания работы на одном Incident → нет дубля активных Ticket; исходные Report/заявители/индивидуальная история сохранены. | A + B, counts и API read | PLANNED / NOT RUN |
| QA-03 | A-16 / DEV-B | Повторить команду после timeout с тем же key/body → та же WorkAttempt без нового эффекта; тот же key с другим содержимым → определённый конфликт без молчаливой другой операции. | A + B | PLANNED / NOT RUN |
| QA-04 | A-16/B-14 / DEV-B | Чужой tenant/дом читает/меняет Ticket по прямому ID → безопасный отказ; resident projection не содержит internal-only, приватных контактов/комментариев. | A + B + browser | PLANNED / NOT RUN |
| QA-05 | A-16/B-06/B-14 / DEV-B | Конкурентное принятие/обновление и stale attempt/callback → определённый конфликт/актуальный read, без потери истории и переноса наблюдения на новую попытку; проверены actor/scope/actions. | A + B | PLANNED / NOT RUN |
| QA-06 | A-16/A-05 / DEV-B | Искусственный rollback Ticket mutation → ни ложной истории, ни notification intent; успешный commit сохраняет все три согласованно. | B, PG transaction + worker | PLANNED / NOT RUN |
| QA-07 | A-05/B-03/A-16 / DEV-B | Сбой send, потерянный ответ, 200+success=false у поддерживающего это метода → Ticket сохранён, delivery error/unknown отдельно; retry без повторной работы, без exactly-once claim. | A fault fixtures + B HTTP/PG/worker; C отдельно | PLANNED / NOT RUN |
| QA-08 | A-16/A-12/B-14 / DEV-B | Reload и restart API/worker → те же Ticket, попытки, наблюдения и история; номер/текст/срок не выдаются за внешнее подтверждение. | B + browser | PLANNED / NOT RUN |
| QA-09 | A-16/B-14 / DEV-B | Первый житель подтвердил последнюю попытку, второй позже возразил → оба наблюдения сохранены и расхождение видно, включая отсутствие ответа/повтор. Закрытие/reopening проверять только после отдельного согласования правила A-16. | A + B + browser; правило перехода PENDING DECISION | PLANNED / NOT RUN |
| QA-10 | A-16/B-14/A-05/B-03/B-06/B-07/A-09/B-08; B-01/B-11 / DEV-B | Report→Incident→Ticket→WorkAttempt→outbox→MAX→нужная Mini App карточка→явная проверка→ResultObservation→обновление. Ссылка только контекст, свежий API read; API accepted не read receipt. Sharing cancel/fallback, group privacy, отзыв и смена management/binding до send/open/callback проверены. | A/B + отдельно C по [live smoke](../docs/MAX_LIVE_SMOKE.md) | PLANNED / NOT RUN / PENDING TOKEN |
| QA-11 | A-02/A-11/Product/A-16/A-09 / DEV-B | Проверить четыре вида срока, основание/редакцию/applicability и исходное событие; неизвестные ответственность/anchor → диспетчерская проверка/неопределённость без выдуманного due_at. Модель не определяет нормы. | A fake clock/rules + B | PLANNED / NOT RUN |
| QA-12 | A-12/A-13/B-11 / DEV-B | Чистый клон→документированная конфигурация→Docker→миграции→изолированные данные→проверки→restart без потерь; сборка ≤5 минут без первоначальной загрузки base images. Отдельно собственный HTTPS API, роли/данные, обязательные проверки и DATA-API по полученному официальному шаблону. | B + release evidence; MAX стенд C отдельно | PLANNED / NOT RUN |
| QA-13 | A-08 / DEV-A; A-03/Product / DEV-B | Для принятого provider: invalid schema/timeout/uncertainty → validation/clarification/manual fallback без частичной записи; стабильный контракт, а не одинаковый текст. Provider/data/license gate отдельно от общего разрешения LLM. | A + B; C LLM отдельно при доступе | PLANNED / NOT RUN |

## A-16 — backend evidence 18.09.2026

Согласованный scope A16_TICKET_BACKEND_CODEX.md; IMPLEMENTED IN BRANCH,
не MERGED/LIVE. Старые C/MT/CB/QA строки и их историческое evidence сохранены.
Текущий backend delta сопоставлен ниже; combined QA с B-14/MAX delivery не
становятся PASS только из-за backend. Закрытие/возобновление теперь согласовано
и реализовано согласно A-16.1 в CONTRACTS.

Уровень B: реальные отдельные PostgreSQL connections/transactions и HTTP ASGI
через FastAPI/services; дополнительно сетевой HTTP smoke против отдельного API.
Две УК, три дома, admin/responsible/operator без назначения, multi-house resident,
реальные авторы fixture Report, outsider; варианты revoked/ended/suspended.
Связанные Report — явные fixtures существующего Incident, не A-06 matching.

| A-16 ID | Сценарий / тест | Связь с прежними IDs | Результат |
|---|---|---|---|
| TK-01 | Общий intake, explicit flag, один Ticket и отдельные Report; GET без backfill | QA-02, MT-13/14 | PASS |
| TK-02 | accept/start/report, silence, close, late objection, conflict, correction, новая/stale попытка, история | QA-05/09, MT-15 | PASS |
| TK-03 | Tenant/house/role scope всех списков, totals и nested endpoints (5 ролей) | QA-04, MT-10/12/16 | PASS |
| TK-04 | Resident allowlist, приватность comments, собственные ревизии | QA-04 | PASS |
| TK-05 | Self-verification через dual role; нужен собственный Report | QA-04/09 | PASS |
| TK-06 | Concurrent same-key attempt, same effect/current replay, body conflict, revoke | QA-03/05 | PASS |
| TK-07 | Parallel resolved/unresolved/ensure, без потери возражения и второго Ticket | QA-02/05/09 | PASS |
| TK-08 | Внешняя PG-транзакция реально блокирует команду; concurrent attempts | QA-05 | PASS |
| TK-09 | Single/multiple/no responsible, unknown category, concurrent accept | MT-13, QA-02/05 | PASS |
| TK-10 | Waiting/reassign/resume, личное принятие, cancel и invalid transition | MT-13/15 | PASS |
| TK-11 | Cancelled + observation остаётся историей | QA-05/09 | PASS |
| TK-12 | Management switch/ended/tenant suspended (3 варианта), чужая УК | MT-10/16, QA-04 | PASS |
| TK-13 | Три kind, internal/agreed, null due, revisions, запрет client normative | QA-11 backend facts | PASS; нормативный engine NOT IMPLEMENTED |
| TK-14 | Injected outbox failure откатывает Report/Incident/Ticket/Event/Intent | QA-06 | PASS |
| TK-15 | Новое приложение/engine, те же данные, pending unique safe intents | QA-06/08 | PASS |
| TK-16 | DB immutable scope/number/authorship/history и active unique | QA-02/05 | PASS |
| TK-17 | Context spoofing, mandatory headers, bounded pagination, bearer | QA-01/04 | PASS |
| TK-18 | 5 независимых concurrent ensure отсутствующей работы; double HTTP report | QA-02/03/05 | PASS |
| TK-19 | Revoked assignee при reopening, admin reserve, новая acceptance | MT-10/13/16 | PASS |
| TK-20 | Более новый Ticket: old observation/replay сохраняют историю без reopen | QA-05/09 | PASS |
| TK-21 | DB scope/foreign latest-attempt rejection | QA-04/05 | PASS |
| TK-22 | Unknown job не блокирует healthy job, Ticket/intents сохранены | QA-06/07 boundary | PASS; новый network delivery NOT RUN |
| TK-23 | A-07 общий intake; unbound/ordinary/suspended; binding provenance | CB-02/03/11, QA-10 backend | PASS; fake provider, не live |
| TK-24 | Operator другого дома/назначенный оператор, foreign assignee denied | MT-12/13, QA-04 | PASS |
| TK-25 | Diagnostic replay actor/house spoof rejected, diagnostic без Ticket | A-01/A-15, QA-04 | PASS |
| TK-26 | Populated A-07 → 0004: ID/content/access/ChatBinding unchanged, no backfill, downgrade guard | QA-08/12 | PASS |

Актуальный общий прогон `scripts/check.py --scope all`: 53 unit/contract,
97 PostgreSQL integration, 73 frontend; ruff/mypy, schema/TS checks, build PASS.
31 A-16 HTTP/PG cases + 1 migration case, прежние 65 integration также PASS.
B-02 `npm run test:browser`: 8 PASS; реальный board/detail/report/reload сохранён.
Docker clean-store/API restart smoke PASS; A-16 network smoke через
`scripts/ticket_smoke.py` и явный `seed_tickets`. Полные команды/refs и restart
evidence — [DEV-B](../docs/status/dev-b.md).

MAX Web/iOS/Android, новая delivery, B-14 UI, нормативная применимость,
внешняя регистрация/прочтение — NOT RUN / NOT IMPLEMENTED, не переименованы в PASS.

## Исходная матрица и evidence

Это acceptance-контракт целевого UX/API `v0.1`, а не отчёт о реализованных
возможностях. Упомянутые target endpoints реализует DEV-B как writer public
producer+consumer contract и сверяет с OpenAPI; DEV-A review AI boundary.
Текущая реализация отделена в [CONTRACTS](../docs/CONTRACTS.md).
[ARCH-PLATFORM-v1](../docs/PRODUCT_ARCHITECTURE.md) расширяет цель: C39–C41
переносятся в отдельный web-кабинет без смены ID; остальные C01–C49 и основной
личный путь сохранены. MT-01…MT-20 ниже — будущие проверки, все NOT RUN.
Default House Board в C34 означает последний разрешённый дом либо явный выбор
из доступных домов; потерянный контекст не разрешает угадывать дом отправки.

Во всех сценариях backend повторно проверяет identity, доступ к дому и
`allowed_actions`. Deep link передаёт только контекст. Stateful POST-запросы
передают `Idempotency-Key`; draft update передаёт текущую версию. `reported`
всегда означает self-report пользователя. Обозначение «оба MAX» ниже означает
mobile MAX и web MAX с одинаковым пользовательским результатом.

## P0 — личный golden path

| ID | Priority | Preconditions | Steps | Expected UI | Expected backend state | Failure behaviour | Platforms |
|---|---|---|---|---|---|---|---|
| C01 Personal report without group chat | P0 | Пользователь авторизован, имеет доступ к дому; `group_mode=false`, текстовый ввод доступен. | Открыть mini app из личного контекста → описать проблему → пройти анализ/уточнение → подтвердить → подготовить и отредактировать draft → скопировать → открыть официальный канал → самостоятельно отправить → вернуться → нажать «Я отправил(а) обращение». | Весь путь доступен без групповых элементов; после отметки показан честный текст о неподтверждённой внешней регистрации и следующий шаг. | Созданы/обновлены report, incident и сохранённый draft; только последний явный шаг создаёт user-reported filing event и при допустимом переходе `reported`. | Анализ/LLM падает — ручная категория; сеть падает — ввод и draft не очищаются, доступен безопасный retry; внешний канал недоступен — статус не меняется. | Оба MAX. |
| C02 Create new incident | P0 | Доступный дом; подходящего активного инцидента нет. | Ввести и проверить `ProblemDetails`, отправить report. | Показана новая Incident Detail с маршрутом, provenance и доступными действиями. | Один report и один новый incident в `open`; решение о создании принято backend. | Ошибка/timeout не показываются как успех; повтор с тем же idempotency key не создаёт дубль. | Оба MAX. |
| C03 Open existing incident | P0 | На House Board есть разрешённый пользователю инцидент. | Нажать карточку. | Открывается Incident Detail с актуальными status, route, provenance и actions. | Read-only запрос не меняет incident, counters или activity. | `404` — возврат на обновлённую доску; `403` — отказ без данных инцидента; retry только для retryable error. | Оба MAX. |
| C04 Edit recognized problem before submit | P0 | Analyze вернул распознанные поля, incident ещё не создан. | Изменить описание/категорию/место → подтвердить. | Review немедленно отражает правки; исходное распознавание не блокирует редактирование. | Сохраняются подтверждённые `ProblemDetails`; неподтверждённый analysis не создаёт report/incident. | Validation подсвечивает конкретные `field_errors`, сохраняя остальные правки. | Оба MAX. |
| C05 Prepare appeal draft | P0 | Incident Detail содержит enabled `prepare_appeal`. | Нажать действие. | Открывается Appeal Draft с editable текстом, адресатом, provenance и пометкой «не отправлено». | Создан или идемпотентно возвращён `AppealDraft` с id/version; incident ещё не становится `reported`. | Disabled/исчезнувшее action даёт актуальный reason; retry не создаёт второй draft. | Оба MAX. |
| C06 Draft survives refresh | P0 | Draft открыт и `edit_draft` enabled. | Изменить текст → дождаться «Сохранено» → reload/reopen по `draft_id`. | После reload показан точно сохранённый текст и новая версия; draft остаётся editable, если действие разрешено. | `PATCH` сохранил текст/version; `GET` возвращает ту же подтверждённую версию. | Сбой save оставляет текст на экране и показывает «Не сохранено»; stale conflict не затирает локальную версию. | Оба MAX. |
| C07 Copy draft | P0 | Draft загружен; `copy_draft` enabled. | Нажать «Скопировать текст». | Скопирован текущий видимый текст, показано короткое подтверждение; статус обращения не меняется. | Нет filing event, status transition или изменения draft от одного copy. | Clipboard API недоступен — выделить текст/показать ручное копирование; не показывать filed. | Оба MAX. |
| C08 Open official channel | P0 | Draft и server-provided official channel доступны; `open_official_channel` enabled. | Нажать «Открыть официальный канал», затем вернуться без отметки. | Открывается внешний канал; после возврата draft на месте, видна отдельная кнопка self-report. | Launch/callback/focus не создаёт filing event и не переводит incident в `reported`. | Невозможно открыть ссылку — показать безопасную ссылку/инструкцию и retry; backend state неизменен. | Mobile MAX: внешний app/webview; Web MAX: новая вкладка. |
| C09 Mark appeal as filed | P0 | Пользователь действительно отправил обращение самостоятельно; `mark_filed` enabled. | Вернуться и нажать «Я отправил(а) обращение» один раз. | Показано: «Вы отметили обращение как отправленное. Регистрация во внешней системе ДомСигналом не подтверждена.» | Идемпотентно создана пользовательская отметка с `user_reported` provenance; status становится `reported`, если backend разрешает переход; внешнее подтверждение отсутствует. | Timeout допускает retry тем же key; неизвестный результат не формулируется как успех. | Оба MAX. |
| C10 Filed is NOT external registration | P0 | C09 завершён; внешняя система не интегрирована/не дала подтверждение. | Переоткрыть Incident Detail и My Activity. | Везде используется «пользователь отметил отправку» и видна плашка «внешней системой не подтверждено»; запрещённых формулировок нет. | Filing остаётся self-report; нет invented external registration id/status/confirmed_at. | При отсутствии provenance UI показывает неопределённость и refresh, а не официальный статус. | Оба MAX. |
| C11 Resolve incident | P0 | Incident содержит enabled `mark_resolved`. | Нажать «Проблема решена» и подтвердить наблюдение. | Карточка показывает `resolved`, событие и доступные дальнейшие действия backend. | Сохранён feedback/activity event; backend выполняет допустимый переход в `resolved`. | Stale/disabled action обновляет карточку; повторный submit не создаёт второе наблюдение. | Оба MAX. |
| C12 Report unresolved problem | P0 | Incident содержит enabled `mark_unresolved`. | Нажать «Не решено»/«Проблема остаётся». | Показано сохранённое наблюдение и server-provided reminder/next step; новый статус не придумывается. | Сохранён feedback/activity event; incident остаётся или переходит только в один из семи target statuses по backend rules. | При конфликте наблюдений оба сохраняются, UI не объявляет победителя; retry идемпотентен. | Оба MAX. |

## P0 — состояния, доступ и платформы

| ID | Priority | Preconditions | Steps | Expected UI | Expected backend state | Failure behaviour | Platforms |
|---|---|---|---|---|---|---|---|
| C20 Empty house | P0 | Пользователь имеет доступ; у дома нет инцидентов. | Открыть House Board. | Empty-state «В этом доме пока нет активных проблем» и CTA «Сообщить о проблеме»; не error. | Список пуст, никаких demo incidents не создаётся автоматически. | Ошибка загрузки не маскируется под empty; показывается error/retry. | Оба MAX. |
| C21 Loading state | P0 | Ответ списка/detail/analyze/draft искусственно задержан. | Открыть экран или запустить действие. | Видны skeleton/progress и текущий контекст; зависимая кнопка защищена от повторного нажатия, ввод не исчезает. | До успешного ответа UI не предполагает mutation; один intent соответствует одному idempotency key. | Timeout переводит в retryable error без ложного успеха. | Оба MAX, slow network. |
| C22 Network error + retry | P0 | Первый запрос обрывается, второй доступен. | Выполнить действие → получить ошибку → нажать «Повторить». | Понятная ошибка, trace id при наличии; текст/фильтр/черновик сохранены; retry показан только если разрешён. | Повтор либо завершает исходную идемпотентную операцию, либо возвращает её результат без дубля. | Повторная ошибка остаётся error; UI не меняет status оптимистично. | Оба MAX. |
| C23 Unauthorized | P0 | Нет/истекла session либо initData не прошло проверку. | Запросить любой защищённый экран. | Экран безопасного повторного входа; приватные данные и draft не рендерятся, причина подписи не раскрывается. | `401 application/problem+json`; бизнес-данные не меняются. | Повтор возможен только после новой валидной MAX session; бесконечного retry нет. | Оба MAX. |
| C24 Forbidden house | P0 | Session валидна, membership нужного дома отсутствует. | Подставить `house_id` в URL/API. | Явный «Нет доступа к этому дому», без адреса, инцидентов и источников; возврат к разрешённым домам. | `403`; никаких read side effects, membership не создаётся. | `404` не превращается в доступ; UI не предлагает deep link как способ вступить. | Оба MAX. |
| C25 Stale state | P0 | Между загрузкой и mutation status/action/draft version изменены другим запросом. | Нажать старую кнопку или сохранить старую версию. | Показано, что данные обновились; актуальная версия загружена; локальный draft сохранён для сравнения/повтора. | `409`/stale code; запрещённый transition не применён, текущий resource возвращаем/перечитываем. | Автоматический retry допустим только после обновления preconditions; текст не затирается. | Оба MAX. |
| C26 Double submit/idempotency | P0 | Mutation подготовлена с одним idempotency key. | Дважды быстро нажать report/prepare/mark/feedback или повторить после timeout. | Одна загрузка и один итог; нет двойных карточек, событий или счётчиков. | Одинаковый key+payload возвращает исходный результат; key с другим payload даёт `409`. | При `409 idempotency_conflict` UI просит обновить состояние и не генерирует ложный успех. | Оба MAX. |
| C27 Manual category fallback | P0 | NLP/LLM недоступен или категория неизвестна. | Ввести описание → выбрать категорию вручную → проверить details → submit. | Ручной список/поиск категорий доступен, основная цепочка продолжается без модели. | Report хранит подтверждённую категорию и способ анализа/fallback; route вычисляет backend. | Если справочник не загрузился — retry и сохранённый текст; нельзя подставлять случайную категорию. | Оба MAX. |
| C36 Web MAX | P0 | Валидная web MAX session; Bridge-only возможности могут отсутствовать. | Пройти C01 целиком клавиатурой/мышью, включая внешний канал и возврат. | Все обязательные шаги и тексты доступны; новая вкладка не маркирует filed; responsive layout без mobile-only зависимости. | Тот же target API и итоговое состояние, что на mobile. | Clipboard/Bridge fallback не блокирует ручное копирование и текстовый путь. | Web MAX. |
| C37 Mobile MAX | P0 | Валидная mobile MAX session. | Пройти C01 на поддерживаемом мобильном клиенте. | Одноколоночный layout, доступная клавиатура, возврат из внешнего канала сохраняет draft; результат равен web. | Тот же target API и итоговое состояние, что на web. | Потеря focus/background не считается filed; reload восстанавливает server-saved draft. | Mobile MAX (iOS/Android при доступности проверки). |
| C45 Invalid initData | P0 | Подпись, auth date, обязательное поле или формат initData неверны. | Запустить mini app/вызвать auth boundary. | Общий безопасный unauthorized без технических деталей и без частичного UI приватных данных. | `401 application/problem+json`; session не создаётся, raw initData не логируется. | Повтор только с новым initData; детали в клиент/URL не выводятся. | Оба MAX. |
| C46 Foreign house access denied | P0 | Пользователь A авторизован только в доме A; известны ID дома/инцидента B. | Вызвать list/detail/report/draft/admin endpoint для B. | Ни один объект B не отображается; понятный forbidden. | Каждый endpoint проверяет scope и возвращает `403` (либо согласованный non-enumerating `404`), без mutation. | Несогласованные ответы считаются дефектом доступа; frontend не кэширует чужие данные. | Оба MAX + API security test. |
| C47 Deep-link does not grant access | P0 | Пользователь без membership получает ссылку на house/incident/draft/admin context. | Открыть ссылку. | Может быть показан только безопасный контекст входа; приватный экран не открывается, роль/дом не добавляются. | Start parameter не участвует в авторизации; backend возвращает `403/404`, membership неизменен. | Повтор/изменение payload не расширяет доступ. | Оба MAX. |

## P1 — анализ, matching и совместный контекст

| ID | Priority | Preconditions | Steps | Expected UI | Expected backend state | Failure behaviour | Platforms |
|---|---|---|---|---|---|---|---|
| C13 Duplicate detection | P1 | В доме есть совместимый активный incident; новый report совпадает по backend rules. | Проанализировать и подтвердить похожую проблему. | Analysis может показать кандидата; итог ведёт в существующий Incident Detail с обновлёнными counters, а не в копию. | Новый report связан с существующим incident; новый incident не создаётся. | Неоднозначность требует подтверждения/создаёт отдельный incident по backend policy; UI сам не merge. | Оба MAX. |
| C14 Similar incidents remain separate | P1 | Есть похожий incident, но различается значимый объект/подъезд/контекст. | Подтвердить новый report с отличающимися details. | UI показывает отдельную карточку и не заявляет объединение. | Backend создаёт новый incident; исходный не меняется. | Если данных мало — запросить уточнение; нельзя объединять только по похожему тексту. | Оба MAX. |
| C15 High-confidence classification | P1 | Анализатор доступен и даёт high confidence без emergency. | Ввести однозначное описание. | Категория и поля предзаполнены, clearly reviewable/editable; подтверждение остаётся у пользователя. | `ProblemAnalysis.requires_confirmation` соответствует контракту; incident не создаётся до submit. | Если route/source не готов — ручной/needs-verification путь, а не выдуманные сведения. | Оба MAX. |
| C16 Low-confidence confirmation | P1 | Анализатор возвращает low confidence/несколько вариантов. | Ввести неоднозначный текст → выбрать/исправить вариант → подтвердить. | Видна неопределённость и 2–3 server-provided варианта либо ручной выбор; нет автоматической отправки. | До подтверждения нет report; после — сохраняются выбранные details. | Сбой вариантов переводит на ручную категорию с сохранённым текстом. | Оба MAX. |
| C17 LLM unavailable fallback | P1 | Provider timeout/invalid output/disabled; rules/manual доступны. | Запустить analysis и завершить report/draft path. | Коротко сообщается об упрощённом анализе; emergency rules, ручной выбор и шаблонный draft работают. | Ошибка LLM не создаёт partial incident; backend использует rules/manual/template provenance. | Если и rules API недоступен — retry + ручной безопасный ввод, без нормативных догадок frontend. | Оба MAX. |
| C18 Emergency override | P1 | Описание содержит server-recognized риск. | Ввести рискованное описание. | Emergency Mode появляется раньше обычного результата: инструкции и контакты с provenance; обычный CTA вторичен. | Emergency decision сформирован backend без зависимости от LLM; filing/route не помечаются выполненными автоматически. | Сбой последующего анализа не скрывает уже полученные safety instructions; UI не диагностирует сам. | Оба MAX. |
| C19 Manual correction | P1 | Analysis распознал неверную категорию/место или пользователь выбирает manual. | Открыть поля → выбрать корректное значение → повторно проверить маршрут → submit. | Исправление заметно; route обновляется по ответу backend, не по hardcoded UI rules. | Сохраняются corrected details и audit-safe analysis mode; неверный вариант не становится incident fact. | Validation сохраняет ввод; stale analysis требует пересчёта перед submit. | Оба MAX. |
| C29 Two residents report same issue | P1 | Два авторизованных жителя одного дома одновременно описывают совместимую проблему. | Оба подтверждают report почти одновременно. | Оба получают один Incident Detail; counters после refresh согласованы. | Транзакционно один incident и два reports/participants по matching policy; нет lost update. | Race, создавший два incident, считается дефектом; предусмотрен безопасный retry/reconciliation без UI merge. | Две сессии, оба MAX. |
| C30 Existing incident counter increases | P1 | Активный incident существует; новый житель репортит/joins. | Завершить report или enabled `join`. | После ответа счётчик увеличен ровно один раз и доступен updated timestamp. | Backend идемпотентно добавляет report/participation и пересчитывает counter. | Double tap не увеличивает повторно; stale card обновляется. | Оба MAX. |
| C31 Filed state visible to other resident | P1 | Житель A выполнил C09; житель B имеет доступ к тому же дому. | B обновляет board/detail. | B видит `reported` и «Житель отметил отправку · внешней системой не подтверждено», без лишних персональных данных. | Общий incident/status/event доступен в house scope; provenance `user_reported`, external confirmation отсутствует. | При stale cache показывается refresh; нельзя повышать self-report до official. | Две сессии, оба MAX. |
| C33 Group → personal context | P1 | `group_mode=true`, реальный доступ подтверждён, карточка группы содержит incident link. | Нажать «Оформить» в группе → перейти в личный контекст. | Личный Report/Incident экран открыт с правильным context; групповой текст не нужно вводить заново, если backend его разрешённо связал. | Context lookup и membership проверены; переход сам не joins и не marks filed. | Нет group capability/access — личный `/start` остаётся рабочим; чужая ссылка даёт forbidden. | MAX group → personal mobile/web. |
| C34 Bot → Mini App context | P1 | Бот показывает разрешённую кнопку mini app с start context. | Открыть mini app. | После auth открывается нужный House Board/Incident/Draft; back navigation возвращает в безопасную точку. | Backend валидирует session и resource scope; context не является credential. | Bridge/start param потерян — открыть default House Board, не угадывать resource. | Оба MAX. |
| C35 Mini App → official channel | P1 | Incident/draft содержит enabled channel action и server URL. | Открыть канал из mini app, затем вернуться. | Переход понятен; draft и позиция восстановлены; есть отдельное self-report действие. | Никакой status/event mutation от одного открытия URL. | Blocked popup/deep link — показать разрешённую ссылку/инструкцию; status неизменен. | Оба MAX. |
| C44 Demo provenance visible | P1 | Дом, route или incident использует demo data. | Открыть board/detail/draft/source drawer. | Контрастная метка «Демонстрационные данные» видна в каждом месте, где данные влияют на решение. | DTO содержит `provenance.type=demo`; данные не переименованы в official. | Отсутствие метки блокирует acceptance; fallback — считать источник непроверенным, не official. | Оба MAX. |

## P2 — deep links, admin, регионы и защита

| ID | Priority | Preconditions | Steps | Expected UI | Expected backend state | Failure behaviour | Platforms |
|---|---|---|---|---|---|---|---|
| C28 Direct incident deep-link | P2 | Валидная ссылка на incident; пользователь имеет membership. | Запустить mini app напрямую по ссылке. | После auth открывается Incident Detail; back ведёт на House Board. | Read-only context разрешён сервером; membership/status не меняются. | Недействительный ID — безопасный not found; отсутствие membership проходит C47. | Оба MAX. |
| C32 Conflicting resident confirmations | P2 | Два жителя видят один incident; один сообщает «решено», другой — «не решено». | Отправить оба feedback события. | Видно расхождение и необходимость проверки; интерфейс не решает голосованием и не вводит новый status. | Оба ActivityEvent сохранены; итоговый status/allowed actions определяет backend в пределах семи статусов. | Race не теряет событие; retry идемпотентен, stale detail обновляется. | Две сессии, оба MAX. |
| C39 Admin house summary | P2 (исходная группа B-00; кабинет roadmap P1) | Действующая web-session сотрудника, capability и assignment конкретного tenant/дома. | Открыть сводку дома в отдельном web-кабинете. | Server aggregates, период и provenance; нет чужих домов/личной переписки. | Target summary read проверяет tenant/house scope и не меняет данные. | Нет capability — вход скрыт; нет permission — безопасный отказ без данных. | Обычный браузер без Bridge; MAX residents отдельно. |
| C40 Dismiss false positive | P2 (исходная группа B-00; кабинет roadmap P1) | Web-session, assignment tenant/дома, enabled dismiss. | Открыть incident в кабинете → подтвердить dismiss. | `dismissed`, reason/audit event и актуальные действия; это Incident, не Ticket lifecycle. | Target dismiss проверяет object scope и идемпотентно меняет допустимый Incident. | Stale/forbidden не меняет status; повтор не создаёт второй effect. | Обычный браузер без Bridge; доступное resident read отдельно в обоих MAX. |
| C41 Anti-spam settings | P2 (исходная группа B-00; кабинет roadmap P1) | Web-session и assignment tenant/дома. | Открыть настройки кабинета → изменить quiet/limit fields → сохранить → reload. | Только поля реального settings DTO, «Сохранено» после ответа и сохранение после reload. | Target versioned settings проверяет tenant/house/action scope. | Validation у поля; stale не затирает чужое изменение; forbidden не применяет patch. | Обычный браузер без Bridge. |
| C42 Same UI with second region | P2 | Пользователь имеет по дому в двух region packs; backend отдаёт одинаковые DTO shapes. | Переключить дом/регион и пройти report → route → draft. | Те же пять экранов и действия; меняются только server-provided тексты/источники/каналы. | Одинаковый API contract, разные region-resolved значения; frontend config fork отсутствует. | Неполный region pack показывает needs-verification/manual next step, не данные первого региона. | Оба MAX. |
| C43 Different regional provenance/routing | P2 | Для одинаковой категории два дома имеют разные проверенные региональные правила. | Сравнить Incident Detail и Source Drawer. | Различаются адресат/канал/основание и provenance с корректными source/date; UI явно показывает региональный контекст. | Backend выбрал route по house region/config; provenance относится к использованному правилу. | Нет проверенного источника — нет выдуманного срока/official badge; доступен безопасный следующий шаг. | Оба MAX. |
| C48 Sensitive auth not exposed | P2 | Валидная и невалидная auth попытки; доступны browser devtools/test logs. | Запустить app, навигировать, вызвать ошибки, проверить URL/DOM/storage/logs. | Raw initData/token/секреты не видны в URL, пользовательских ошибках или persistent browser storage. | Backend не пишет raw initData/secret в логи/problem; session short-lived и scoped согласно foundation. | Любая утечка блокирует acceptance; generic `401` остаётся без диагностических секретов. | Оба MAX + security inspection. |
| C49 Demo source cannot masquerade as official | P2 | Один объект demo, другой official. | Открыть одинаковые UI-блоки и drawers. | Demo всегда маркирован «Демонстрационные данные» и визуально не получает official label; official показывает источник и дату проверки. | Provenance enum/validation не допускает demo payload как `official` без обязательных official fields. | Неизвестный/некорректный provenance отображается как непроверенный и не влияет на решение как official. | Оба MAX + contract test. |

## Acceptance gate B-00

B-00 считается принятым как документационный контракт, когда все перечисленные
ID присутствуют, личный C01 не требует group access, C06 подтверждает server
persistence, C08/C09/C10 разделяют handoff и self-report, C17/C27 обеспечивают
путь без LLM, C23–C25 и C45–C49 закрывают отрицательные ветки, а mobile/web дают
одинаковый основной результат. Исполнение сценариев становится задачей
соответствующих backend/frontend этапов и не заявляется выполненным этим файлом.


## MT — ARCH-PLATFORM-v1, будущая приёмка

Соответствие § 13 архитектуры: **MT-01…MT-20 → MT-01…MT-20**, конфликтов ID нет.
Owner всех проверок — DEV-B; ссылки на карточки определяют зависимости, а не
второе владение. Все строки — **TARGET / NOT RUN**; столбец evidence описывает
требуемое свидетельство, не полученный результат. Наличие прежнего C0 теста
не даёт PASS целому MT. После выполнения фиксировать ref, дату, роли/окружение,
команду/артефакт и ограничение: IMPLEMENTED IN BRANCH, MERGED TO MAIN и LIVE
VERIFIED независимы. HTTP коды новых lifecycle-ошибок согласуются в contracts;
ниже задан ожидаемый безопасный смысл, а не новый опубликованный enum.

| ID | Зависимые карточки | Предусловия / роли | Действие | Ожидаемое состояние / UI | Ошибка / отрицательная ветка | Требуемое evidence | Статус |
|---|---|---|---|---|---|---|---|
| MT-01 | A-15, A-07, B-02 | Две одобренные УК, по дому/назначенному сотруднику/жителю; один общий бот/Mini App. | Обе роли каждой УК читают/создают свои данные; затем запрашивают чужие ID. | Одна платформа обслуживает обе УК; контекст и данные изолированы. | Чужие объекты не раскрываются, мутаций нет; клиентский tenant не grant. | API/PG positive+negative, две сессии Mini App; отдельно live общего бота. | NOT RUN |
| MT-02 | A-15, A-10, A-07 | Superadmin одобрил УК; её администратор не имеет подтверждённого управления домом B. | Добавить/активировать B, в том числе прямым API ID. | Заявка/проверка управления без доступа к B; одобрение УК не разрешает любой дом. | Отказ/ожидание подтверждения, чужой дом не активирован. | API/PG: до/после HouseManagement, аудит и отсутствие чужих данных. | NOT RUN |
| MT-03 | A-07, A-10 | Администратор УК; осталось одно место лимита, два подтверждаемых дома и истекающий резерв. | Активировать одновременно, повторить событие и проверить истечение резерва. | Не больше лимита активных домов; несколько чатов одного дома не списывают места. | Конфликт/лимит явно показан; повтор не списывает место, ошибка не success. | PG concurrency с двумя транзакциями, audit/limit snapshots и expiry clock. | NOT RUN |
| MT-04 | B-03, A-07 | Бот разрешён для группы; добавляющий не имеет org assignment/ConnectionRequest. | Доставить bot_added, включая повтор. | Только ожидающая установка; дом не активен, роль сотрудника не выдана. | Ни обработка переписки, ни доступ УК не включаются от события. | Normalized/adapter tests и отдельно обезличенное live event evidence. | NOT RUN |
| MT-05 | A-07, B-07 | Разрешение УК есть; ссылку получил человек без текущих admin прав MAX. | Пройти мастер, запросить подтверждение/активацию. | MAX-проверка не подтверждает полномочия; tenant/дом не меняются. | Безопасный отказ; URL не выдаёт роль и не раскрывает рабочие данные. | API/transport negative и отдельно реальный non-admin MAX клиент. | NOT RUN |
| MT-06 | A-07, B-07 | Действующий admin MAX-чата без делегирования УК на выбранный дом. | Попытаться подключить чат к чужому дому. | MAX-права сами по себе не подтверждают назначение/HouseManagement. | Отказ без активной привязки/доступа к tenant. | Раздельные positive MAX и negative org проверки; аудит и live gate. | NOT RUN |
| MT-07 | A-07, B-07 | ConnectionRequest конкретного tenant/дома/человека с TTL. | Подменить дом/пользователя, повторить использованный контекст, дождаться TTL через clock. | Активация возможна только в исходном действующем контексте один раз. | Altered/replayed/expired отказ; ссылку нельзя обменять на новые права. | API negative, fake clock и PG проверка единственной активации. | NOT RUN |
| MT-08 | A-07, B-03 | Назначение УК есть, MAX-проверка admins/bot membership недоступна. | Получить timeout/5xx; затем безопасно повторить. | Pending и причина, ни verified, ни отрицательное членство не выдуманы. | Нет success/активации; разрешённый retry не дублирует эффект. | Fault-injection transport/API + проверка UI pending и сохранённого состояния. | NOT RUN |
| MT-09 | A-07, A-06/Product, B-06 | Один дом, два проверенных чата с разным охватом; жители и приватные Report. | Создать сигналы в обоих чатах, прочитать общую проблему/карточки. | Привязки сосуществуют, общие разрешённые данные связаны, оригинальные Report сохранены. | Приватные сообщения одного чата не появляются в другом. | PG/API и recording payload assertions; два реальных чата отдельно для LIVE. | NOT RUN |
| MT-10 | A-15, A-07, A-05, A-09 | Сотрудник/житель имеет действующее основание, бот — права; уже поставлен job. | Отозвать assignment, resident basis или bot rights, выполнить новые запросы и старый job. | Права пересчитаны перед действием; независимое действующее основание учтено отдельно. | Нет запрещённых mutation/доставок; lost rights приостанавливают группу без удаления истории. | API/PG + controlled worker run после отзыва и аудит отказов. | NOT RUN |
| MT-11 | A-15, B-02, B-07 | Житель с несколькими разрешёнными домами; запуск DM/вне чата/с неверным контекстом. | Открыть Mini App, выбрать дом, отправить; повторить с чужим ID. | Явный разрешённый контекст и видимый адрес; нет молчаливого выбора другого дома. | Чужой контекст даёт отказ/запрос подтверждения, а не fallback отправку. | Browser/API tests; реальные MAX mobile/web launch paths отдельно. | NOT RUN |
| MT-12 | A-15, A-12, A-14/Product | Два tenant, дома и объекты; сотрудник/житель A знает ID B. Для attachment/export — только после их реализации. | Вызвать read/write по прямым ID объекта/файла, jobs/analytics/export в доступном срезе. | Tenant/house/object scope соблюдён во всех реализованных каналах. | Безопасный отказ без содержимого/изменений/утечки в кеш или выгрузку. | API/PG negative по каждой поверхности; неподключённые поверхности остаются NOT RUN. | NOT RUN |
| MT-13 | A-16, B-14 | Активная УК с резервной очередью; неизвестная категория или нет доступного назначенного исполнителя. | Создать/маршрутизировать Ticket; два сотрудника пытаются принять его. | Заявка в резервной очереди tenant, один текущий владелец после принятия. | Не исчезает и не идёт в чужую УК; конфликт принятия обновляет состояние. | PG/API routing/concurrency + web UI очереди на реальном backend. | NOT RUN |
| MT-14 | A-04, A-16, B-14 | Житель с Incident/ExternalAppeal и сотрудник с Ticket. | Создать внутреннюю заявку; вручную указать внешний номер/filing. | Внутренняя регистрация и user-reported external filing раздельны. | Ни номер Ticket, ни ручной внешний номер не дают verified registration. | Contract/API/PG provenance assertions и UI тексты двух направлений. | NOT RUN |
| MT-15 | A-16, B-14 | Сотрудник заявил выполнение конкретной попытки; жители могут наблюдать результат. | Один подтвердил, другой возразил; отдельно случай без ответа и новый WorkReport. | Отчёт/наблюдения раздельны, расхождение сохранено и требует проверки. | Молчание/большинство не подтверждают; старый ответ не подтверждает новую попытку. | API/PG race/idempotency/history + web/resident UI, раздельное live evidence. | NOT RUN |
| MT-16 | A-15, A-10, A-12 | Дом управляется УК A; сохранены заявки/обращения; утверждается новый период УК B. | Закрыть старую HouseManagement, начать новую; сменить сотрудника/чат, запросить историю. | История сохраняет исходный tenant/период; собственные обращения жителя не удалены. | Новая УК не читает старые приватные обращения; старый assignment не действует автоматически. | PG migration/access tests, snapshots истории и negative API двух организаций. | NOT RUN |
| MT-17 | A-07, A-05, A-12 | Ожидающая/активная установка и job; возможен crash после записи до ack. | Повторить события и activation, перезапустить API/worker, восстановить lease. | Реестр и связь установки сохранены, один доменный эффект и лимит. | Stale worker не коммитит чужую задачу; потерянный send response не exactly-once обещание. | PG crash/restart/retry tests, audit/limit/job counts и recovery evidence. | NOT RUN |
| MT-18 | A-15, B-02, B-04, B-05 | Житель без групповых прав и без LLM; согласованный личный канал, чужая доска недоступна. | Пройти личный manual путь, вернуться к своему обращению после отзыва доступа к доске. | Собственный путь/история работают в разрешённом scope без группы и модели. | Нет выдачи чужой доски по введённому адресу; fallback сохраняет ввод без выдуманного анализа. | Сохранённые C01/C06/C17/C27 + negative API; реальный MAX personal path отдельно. | NOT RUN |
| MT-19 | A-10, B-09, B-14, B-11 | Сотрудник с web-session и назначениями; житель с валидной MAX-session. | Открыть кабинет без window.WebApp; отдельно пройти основной путь в MAX web/mobile. | Кабинет работает в обычном браузере; MAX-путь одинаков по результату на клиентах. | Отсутствующий Bridge не блокирует кабинет; недоступный live клиент отмечен NOT VERIFIED. | Browser/API E2E без Bridge и отдельные live записи ref/клиент/роль/дата. | NOT RUN |
| MT-20 | B-11, B-12 | Demo/target и реальные интеграционные данные разделены; доступны UI/материалы с источниками. | Сопоставить карточки, кабинет, демо и release evidence с ref/источником. | Demo marker не исчезает из-за official source; TARGET, локальный тест и LIVE различимы. | Неизвестное provenance не становится official, browser replay не становится live evidence. | Contract/UI assertions и review материалов; ref/дата/окружение для каждого утверждения. | NOT RUN |


## A-01 / B-02 — фактический прогон 18.09.2026

IMPLEMENTED IN BRANCH `dev/b-experience`, baseline `804f198`. A-01 PASS;
текущий B-02 board/detail/manual binding DONE после нового прогона. Это не
MERGED TO MAIN, не выполнение будущего golden path и не LIVE VERIFIED.
Команды/окружение: [DEV-B evidence](../docs/status/dev-b.md).

| Проверка среза | Фактический результат / свидетельство |
|---|---|
| Два дома, incident через неверный доступный/недоступный house | PASS: PostgreSQL `test_house_context_direct_id_and_untrusted_selectors`; 404 для несовпадения в доступном доме, 403 для недоступного |
| Прямой ID, неизвестный selector, client tenant/chat/start_param/roles | PASS: нет обхода membership; metadata не повышает права; extra body → 422 |
| Неоднозначный/потерянный house context | PASS в C0: отсутствие house в POST → 422; resolver None → отказ; UI с двумя домами требует выбора, foreign/empty selector не выбирает default |
| Отзыв membership, включая idempotent retry | PASS: detail и повтор create → 403 |
| Diagnostic replay actor/house spoofing | PASS: 403 до записи Job; прежние valid replay/worker tests тоже PASS |
| Counts/read model/provenance | PASS: 4 reports одного actor → 1 участник; ещё один actor → 2. Board/detail совпадают; demo отделён от rule verification, missing location/update/due = null |
| Старые C0 receipts | PASS: те же report/incident IDs, один эффект; текущий DTO и actions=[], без view |
| Error runtime/schema | PASS: problem+json, trace_id и безопасные field_errors; 401/403/404/405/409/422/500/503 проверены в contract/integration; без input/auth/SQL/stack |
| OpenAPI/TS drift | PASS: export check и штатная генерация/сравнение TS |
| B-02 real API/reload | PASS: Chrome → API → PostgreSQL → board/detail/reload; нет domain CTA; реальный outsider 403 |
| B-02 presentation/recovery | PASS: 73 Vitest tests, 8 browser tests, typecheck/build; unknown enums/actions, null source/count, retryable, keyboard/axe/contrast, 320/430/1280px × light/dark |
| Tenant isolation, управление домом/assignments | NOT IMPLEMENTABLE UNTIL A-15; текущие проверки membership не имитируют две УК |
| Active ChatBinding/version/real group context | NOT IMPLEMENTABLE UNTIL A-15 + A-07; fake bindings не созданы |
| Live MAX Web/iOS/Android, реальные initData/webhook/host reload | NOT VERIFIED; browser emulation статус не повышает |

MT-01…MT-20 остаются NOT RUN как полные target-сценарии. Локальные проверки
C0 house isolation и явного выбора выше — только существующая foundation,
не замена tenant/lifecycle/connection acceptance. `reported` остаётся self-report;
filing, feedback, route, appeals и AI/NLP в этом срезе не реализованы.


## A-15 / MT-01…MT-10 — фактическая приёмка tenant/access

**PASS / IMPLEMENTED IN BRANCH `dev/b-experience`, 18.09.2026**, parent A-01
`e66c351`. Не MERGED TO MAIN / LIVE VERIFIED. Здесь ID из задания A-15 имеют
namespace **A-15/MT**: они не переопределяют прежние ARCH MT-01…MT-20 выше.
Полные сценарии подключения/кабинета/Ticket не становятся PASS этим прогоном.

Окружение: отдельный PostgreSQL 16 `domsignal-a15-db` (127.0.0.1:55474),
реальные HTTP/ASGI bearer sessions и SQL, без MAX. Dataset: Alpha/A1/A2,
Beta/B1; Alice=Alpha company_admin, Bob=Alpha operator + responsible A1,
Carol=resident A1, Dave=resident B1, Eve=resident A1+B1; operator без назначения,
Beta admin и platform superadmin. Не один demo tenant.

Команда: `uv run pytest tests/integration/test_tenant_access.py -x -q` и полный
`scripts/check.py --scope all`; evidence/tests/ограничения — [DEV-B](../docs/status/dev-b.md).

| ID среза | Предусловие/действие | Фактический результат | Test suffix |
|---|---|---|---|
| A-15/MT-01 | Alice читает Beta board/detail; /me houses | PASS: 404; только A1/A2 в /me | `mt01_tenant_isolation` |
| A-15/MT-02 | Bob A1 против A2; operator без assignment | PASS: A1 200, A2 404; без assignment нет домов | `mt02_same_tenant_assignment` |
| A-15/MT-03 | Carol A1 board/detail и чужой B1 | PASS: A1 200, B1 404 | `mt03_resident` |
| A-15/MT-04 | Eve A1 → B1 → A1 | PASS: независимые tenant/management context, обе доски/detail 200 | `mt04_multi_house_context` |
| A-15/MT-05 | Carol знает incident UUID B1 | PASS: 404; body совпадает с отсутствующим ID кроме trace_id, без данных | `mt05_idor` |
| A-15/MT-06 | Подстановка tenant/management/chat/role/permissions; mismatch selector | PASS: query не выдаёт доступ; body extra 422; mismatch 404 | `mt06_client_context_is_not_authority` |
| A-15/MT-07 | Alpha → Beta, прежний incident/assignment, новое сообщение Carol | PASS: Beta не видит старое, старый Bob не получает новое; resident basis сохранён, новый incident с новым management; retry старого receipt 404 | `mt07_management_switch` |
| A-15/MT-08 | Bob assignment active → revoked при той же session | PASS: следующий board/detail 404 без login | `mt08_revoke_without_login` |
| A-15/MT-09 | Incident A1 + management B1; попытка перепривязки истории | PASS: composite FK/immutable triggers отвергают SQL | `mt09_composite_fk_and_immutable_history` |
| A-15/MT-10 | Два active периода одного дома, конечный/open и соседние | PASS: service validation + DB exclusion; соседние допустимы, будущая Beta ещё без доступа | `mt10_overlap_domain_and_database` |

Дополнительно PASS: concurrent insert не обходит exclusion; resident revoke/expiry,
organization revoke, tenant suspend; superadmin без read-all; worker после revoke
не создаёт report; idempotency после switch не раскрывает старый ответ.

Migration test создаёт настоящую C0.1 DB из revision 0001: сохранены IDs/тексты/
reports/legacy evidence; demo не повышен до verified; non-demo suspended.
Upgrade/repeat upgrade/downgrade C0/upgrade/downgrade base/clean upgrade и
`alembic check` PASS. Нужен CREATEDB только тестовому/migration harness.

B-02: 8 browser tests на настоящем API/PG, board/detail/reload и создание report,
новый masked 404 очищает cached detail; 73 component/integration tests,
typecheck/production build, OpenAPI/TS drift PASS. Local restore всех 15 таблиц
и retention 7 PASS; подробности в [database runbook](../deploy/database.md).

Ограничения: текущие board/detail показывают только текущий management, включая
жителей; история остаётся в БД, архивный/own-history endpoint не сделан.
MAX ChatBinding, Ticket, onboarding/admin UI не начаты. Real MAX Web/iOS/Android,
VPS/TLS, off-site backups, main merge/review — NOT VERIFIED/PENDING.

## A-07 CB acceptance — IMPLEMENTED IN BRANCH, 18.09.2026

All outcomes below are deterministic PostgreSQL tests in
`tests/integration/test_chat_bindings.py`, with an explicit test-only MAX adapter.
They are not live MAX evidence. Two synthetic companies/houses, independent
employees, a dual-house resident and outsider are created per test. No fixtures
are installed as production bindings. Group product messages use the existing
manual `/report category description` path; ordinary conversation/NLP is outside A-07.

| ID | Result checked | Evidence function | Outcome |
|---|---|---|---|
| CB-01 | existing chat binds to A1 with explicit confirmation | `test_cb01_existing_chat_binds_with_explicit_confirmation` | PASS |
| CB-02 | unbound messages never enter Core; raw text not retained | `test_cb02_unbound_message_never_enters_core_or_retains_text` | PASS |
| CB-03 | same command/mid in two chats has separate management/house results | `test_cb03_same_message_different_house_results` | PASS |
| CB-04 | Alpha chat never resolves Beta; foreign actor has no effect | `test_cb04_alpha_chat_never_resolves_beta` | PASS |
| CB-05 | connector admin status rechecked at approval | `test_cb05_connector_must_still_be_admin_at_approval` | PASS |
| CB-06 | bot admin + read_all_messages mandatory | `test_cb06_required_bot_permissions` | PASS |
| CB-07 | expired request cannot activate and persists expired | `test_cb07_expired_cannot_activate` | PASS |
| CB-08 | duplicate bot_added does not duplicate chat/request/job | `test_cb08_duplicate_bot_added_idempotent` | PASS |
| CB-09 | one chat cannot bind two houses; conflict hides owner | `test_cb09_chat_cannot_bind_two_houses` | PASS |
| CB-10 | one house can have multiple active chats | `test_cb10_house_has_multiple_chats` | PASS |
| CB-11 | bot_removed suspends once and retains history | `test_cb11_removed_suspends_idempotently_and_retains_history` | PASS |
| CB-12 | health suspends on permission/admin loss, missing chat or timeout | `test_cb12_health_permission_or_access_loss` | PASS |
| CB-13 | management switch suspends without transfer or queued effect | `test_cb13_management_switch_suspends_without_transfer` | PASS |
| CB-14 | old job and stale version fail closed after revoke/rebind | `test_cb14_stale_job_after_revoke_and_rebind` | PASS |
| CB-15 | valid signed Mini App chat/start_param do not grant access | `test_cb15_signed_miniapp_chat_and_start_do_not_grant_access` | PASS |
| CB-16 | title changes snapshot only | `test_cb16_chat_title_changes_only_snapshot` | PASS |
| CB-17 | concurrent webhook delivery has one product effect | `test_cb17_concurrent_duplicate_delivery_has_one_effect` | PASS |
| CB-18 | timeout/429/5xx leave chat_detected, retry pending, no binding | `test_cb18_max_temporary_failure_is_pending_with_durable_retry` | PASS |
| CB-19 | token cannot activate alone or change claimed identity | `test_cb19_token_not_authority_and_cannot_be_stolen` | PASS |
| CB-20 | five concurrent approvals return one binding | `test_cb20_concurrent_approvals_one_binding` | PASS |
| CB-21 | external/Beta connector requires Alpha employee approval | `test_cb21_external_connector_requires_target_company_approval` | PASS |
| CB-22 | entrance hint preserved; text never changes house/binding | `test_cb22_entrance_context_preserves_house` | PASS |

Additional PostgreSQL negatives cover wrong webhook secret/malformed update, raw
token non-retention, repeated initiation/claim, cancel/reject, unauthorized fields
and explicit confirmation, two-house concurrent approval, direct DB uniqueness /
composite FK / immutable-version rejection, access revocation, suspended tenant,
management end, channels/unrelated add and delayed pre-activation messages.
A-07 suite: 38 cases; full integration suite including A-15, jobs and migration
harnesses: 65 PASS. Unit/provider tests independently exercise fake configurations,
production selection, timeout/HTTP failures and documented response mapping.
See [DEV-B](../docs/status/dev-b.md) for exact commands and regression results, and
[MAX live checklist](../docs/MAX_LIVE_SMOKE.md) for pending real-token verification.
