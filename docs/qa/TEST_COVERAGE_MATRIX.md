# ДомСигнал — матрица покрытия

**Версия:** 1.1 от 29.09.2026 (срез F1). Версия 1.0 от 27.09.2026 описывала код `bc23cda`, сервер `00aafba`.

**F1:** автоматическое покрытие тех же кейсов (какой автотест проверяет какой TC и ПР) — в [`ACCEPTANCE_MATRIX.md`](ACCEPTANCE_MATRIX.md); прогон — [`ACCEPTANCE_RUN_2026-09-29.md`](ACCEPTANCE_RUN_2026-09-29.md). Блокер B-03 закрыт аккаунтами жюри ([`docs/JURY_GUIDE.md`](../JURY_GUIDE.md)); эмулятор MAX (B-09) позволяет пройти сценарии бота и группы на локальном стенде.

Связывает проектные сценарии, возможности, роли, интерфейсы, API, переходы состояний и интеграции с тест-кейсами из `TEST_CASES.md`.

**Статусы:**
- **FULL** — сценарий целиком проверяется ручными кейсами;
- **PARTIAL** — часть шагов вручную не проверяется (причина указана);
- **BLOCKED** — вручную проверить нельзя (причина указана).

«Исполнимость сейчас» показывает, можно ли выполнить кейс немедленно или сначала нужны данные владельца (🔑, блокер B-03). С F1 данные для входа в кабинеты демо-УК выдаются жюри (B-03 закрыт); отметки 🔑 ниже означают «нужен аккаунт из закрытой передачи».

## 1. Проектный сценарий → тест-кейсы

| ID | Проектный сценарий | Ручные TC — ЛОК | Ручные TC — ПРОД | Автотесты проекта | Покрытие | Исполнимость сейчас | Комментарий |
|---|---|---|---|---|---|---|---|
| S01 | Посторонний житель: бот → «Попробовать» → выбор открытого дома → карточка маршрута → черновик → «Я отправил(а) обращение» | TC-005, TC-036, TC-047, TC-099 | TC-049, TC-050 | scenario_run сц. 1; test_d1_personal_bot, test_appeal_drafts; browser access.spec | **FULL** | ЛОК — сразу; ПРОД — после 🔑 |  |
| S02 | Сообщение о проблеме в личке боту: зона УК → заявка; внешний адресат → карточка; не определено → уточнение; «не проблема»; дубль; лимит в сутки | TC-037, TC-038 | TC-051, TC-052, TC-053, TC-054, TC-056, TC-059 | test_d1_personal_bot, test_explicit_reports, test_explicit_intake | **FULL** | ЛОК — сразу; ПРОД — после 🔑 |  |
| S03 | `/report` в группе → заявка → принятие → отчёт исполнителя → проверка жителем → закрытие; «Проблема осталась» → та же T-N снова в работе | TC-034, TC-035 | TC-057, TC-059, TC-060 | scenario_run сц. 2; test_explicit_reports, test_tickets, test_notifications | **FULL** | ЛОК — сразу; ПРОД — после 🔑 |  |
| S04 | Пассивное чтение: ветка реплик → сигнал → «Создать заявку» → пост в чате → правка поста при смене статуса → «Меня тоже касается» | — | TC-058, TC-061, TC-062 | scenario_run сц. 3; test_passive_capture, test_passive_signals, test_signal_inbox, test_d3_ticket_chat | **FULL** | Только ПРОД; нужны данные 🔑 (B-03) |  |
| S05 | Опасность: памятка в чат и оповещение оператора без модели; модель недоступна → правила | TC-005, TC-039 | TC-055, TC-064, TC-065, TC-094 | scenario_run сц. 4; test_p6b_chat_memo, test_p6c_gas_subtype, test_p7b_alerts, test_window_fallback | **FULL** | ЛОК — сразу; ПРОД — после 🔑 |  |
| S06 | Мини-приложение: сообщить через форму, доска дома, карточка проблемы, данные после перезагрузки | TC-034, TC-036, TC-037, TC-038, TC-039, TC-040, TC-045, TC-046, TC-081 | — | test_report_preview_and_join, test_resident_experience; browser resident-experience.spec, experience.spec | **FULL** | Сразу на ЛОК |  |
| S07 | Проверка результата жителем: «Исправлено» / «Проблема осталась» — в мини-приложении и в личке бота | TC-035 | TC-057 | test_tickets, test_notifications; browser tickets.spec, notifications.spec | **FULL** | ЛОК — сразу; ПРОД — после 🔑 |  |
| S08 | Решения по сигналам в кабинете: создать заявку, присоединить, внешний маршрут, выбрать маршрут, закрыть | — | TC-062, TC-063 | test_signal_inbox; browser signals.spec | **FULL** | Только ПРОД; нужны данные 🔑 (B-03) |  |
| S09 | Работа с заявкой в кабинете: назначение, принятие, начало, уточнение, ожидание другой службы, возобновление, отмена; конфликт версий | TC-029, TC-035, TC-037, TC-041, TC-042, TC-043, TC-097 | — | test_tickets; browser tickets.spec | **FULL** | Сразу на ЛОК |  |
| S10 | Подключение УК: заявка → уточнения → одобрение с квотой → администратор создаёт свой аккаунт | TC-005, TC-014, TC-015, TC-016, TC-017, TC-018 | — | scenario_run сц. 5; test_d2_company_signup, test_administration; browser d2.spec, administration.spec | **FULL** | Сразу на ЛОК |  |
| S11 | Дома УК: одиночная заявка, список до 200 адресов, адреса из заявки УК; одобрение платформой с регионом, в том числе пачкой | TC-020, TC-021, TC-022, TC-023 | TC-087 | scenario_run сц. 5; test_d5_bulk_houses, test_d4_house_region | **FULL** | ЛОК — сразу; ПРОД — после 🔑 |  |
| S12 | Подключение MAX-чата кодом с проверкой прав; квота; «Лимит исчерпан»; расширение квоты | TC-033 | TC-068, TC-069, TC-070, TC-071 | scenario_run сц. 5; test_chat_bindings, test_d2_chat_quota, test_d2_connect_command | **FULL** | ЛОК — сразу; ПРОД — после 🔑 |  |
| S13 | Сотрудники: приглашение, назначения на дома, отзыв доступа, сброс пароля и MFA, открытая регистрация | TC-012, TC-016, TC-025, TC-026, TC-028, TC-029, TC-030, TC-031 | — | test_administration, test_employee_auth; browser administration.spec | **FULL** | Сразу на ЛОК |  |
| S14 | Вход сотрудников: пароль + TOTP, коды восстановления, выход, блокировка при переборе, требования к паролю | TC-006, TC-007, TC-008, TC-009, TC-010, TC-011, TC-012, TC-016, TC-025, TC-028 | TC-013 | test_employee_auth; browser employee-auth.spec | **FULL** | ЛОК — сразу; ПРОД — после 🔑 |  |
| S15 | Открытый доступ к дому: включение, вход постороннего, выключение, закрытие платформой | TC-005, TC-047, TC-048 | TC-049 | scenario_run сц. 9; test_d1_open_access; browser access.spec | **FULL** | ЛОК — сразу; ПРОД — после 🔑 |  |
| S16 | Житель = участник домового чата: вступил — дом появился, вышел — пропал | TC-005 | TC-071, TC-072 | scenario_run сц. 8; test_d1_chat_membership | **FULL** | ЛОК — сразу; ПРОД — после 🔑 |  |
| S17 | Чтение чата: включение и выключение, сообщение о чтении, повторная отправка, что публикует бот, тихие часы | — | TC-066, TC-067 | test_passive_capture, test_d3_mailings (настройки чата) | **FULL** | Только ПРОД; нужны данные 🔑 (B-03) |  |
| S18 | Объявления и рассылки: черновик → предпросмотр → подтверждение → доставка в чат, личку, ленту → исправление → удаление; отписка | TC-005, TC-073, TC-074, TC-092 | TC-067, TC-076, TC-077 | scenario_run сц. 6; test_d3_mailings, test_d5_queue (приоритет опасности) | **FULL** | ЛОК — сразу; ПРОД — после 🔑 |  |
| S19 | Опросы: пост с «Голосовать», голос, изменение голоса, итоги правкой того же поста, закрытие | TC-005, TC-075 | TC-076 | scenario_run сц. 7; test_d3_polls | **FULL** | ЛОК — сразу; ПРОД — после 🔑 |  |
| S20 | «Мой дом» — навигатор: аварийный блок, контакты УК, сведения о доме, официальные сервисы региона, тарифы и капремонт, политика данных | TC-045, TC-078, TC-081 | TC-050 | test_d3_resident, test_d4_references | **FULL** | ЛОК — сразу; ПРОД — после 🔑 |  |
| S21 | Совет дома и предложения жителей | TC-079 | TC-079 | test_d4_council | **FULL** | ЛОК — сразу; ПРОД — после 🔑 |  |
| S22 | Приём жителей: время приёма, запись, отмена, напоминание | TC-080 | TC-080 | test_d3_resident (приём, напоминание) | **FULL** | ЛОК — сразу; ПРОД — после 🔑 |  |
| S23 | Ежедневная сводка сотруднику в MAX; сообщения платформы для УК | TC-083 | TC-082 | test_d3_mailings (сводка, сообщения платформы) | **FULL** | ЛОК — сразу; ПРОД — после 🔑 |  |
| S24 | Вопрос «Пришёл ли ответ?» через 14 дней после «Я отправил(а)» | — | TC-084 | test_d3_resident (сопровождение, fake clock) | **BLOCKED** | Нет (BLOCKED) | Нужно ждать 14 дней, доставка только через MAX. Покрыто автотестами (fake clock); найдено F-16 |
| S25 | Регион и часовой пояс дома: RU-MOW → «Наш город», RU-TA → «Народный контроль», RU-PSK и RU-PRI → федеральный слой; «Регион не задан»; тихие часы по местному времени | TC-005, TC-020, TC-022, TC-023, TC-024, TC-085, TC-086, TC-088 | TC-087 | scenario_run сц. 10; test_d4_house_region, test_d4_region_time, test_routing | **PARTIAL** | ЛОК — сразу; ПРОД — после 🔑 | Маршруты по регионам проверяются полностью (TC-085, TC-086, TC-087). Тихие часы по местному времени вручную — только частично (TC-088), полностью — автотестом (TC-005, сц. 10) |
| S26 | Обзоры: платформы (плитки, воронка, очередь задач, справочник регионов) и УК (графики, CSV) | TC-089, TC-090 | — | test_d2_dashboards, test_d2_export, test_d5_queue | **FULL** | Сразу на ЛОК |  |
| S27 | Организации: квота, приостановка и возобновление; аудит; состояние системы; спорные привязки | TC-024, TC-031, TC-032, TC-033, TC-048, TC-083, TC-091 | — | test_administration, test_d4_platform_ops | **FULL** | Сразу на ЛОК |  |
| S28 | Публичные страницы и защита production: лендинг, `/privacy`, `/version`, вебхук без секрета, тестовый вход выключен | — | TC-001, TC-002, TC-003, TC-013 | .github/workflows/uptime.yml; test_api_slice | **FULL** | Только ПРОД; нужны данные 🔑 (B-03) |  |
| S29 | Локальный запуск одной командой, демо-данные, автоматический регресс | TC-004, TC-005, TC-093 | — | scripts/docker_smoke.py, scripts/scenario_run.py | **FULL** | Сразу на ЛОК |  |
| S30 | Асинхронная обработка (очередь задач в PostgreSQL, два пула воркеров) и сохранность данных при перезапуске | TC-092, TC-093, TC-095 | TC-094 | test_jobs, test_worker_pools, test_d5_queue | **FULL** | ЛОК — сразу; ПРОД — после 🔑 |  |
| S31 | Идемпотентность и ошибки API: повтор с тем же ключом, конфликт версий, 422, формат Problem Details | TC-043, TC-096, TC-097, TC-099 | — | test_api_slice, test_tickets, test_convergence | **FULL** | Сразу на ЛОК |  |
| S32 | Разграничение доступа: жители — свой дом; сотрудники — по роли и назначению; платформа — отдельно; 403 и 404 по правилам маскирования | TC-010, TC-026, TC-027, TC-042, TC-044, TC-098 | TC-002 | test_tenant_access, test_d1_*; browser access.spec | **FULL** | ЛОК — сразу; ПРОД — после 🔑 |  |
| S33 | Личный бот: `/start`, `/help`, `/version`, неизвестная команда, короткий текст | — | TC-049, TC-051 | test_d1_personal_bot | **FULL** | Только ПРОД; нужны данные 🔑 (B-03) |  |
| S34 | Уведомления жителю в личку о ходе заявки: принята, выполнена — с кнопками проверки | — | TC-057 | test_notifications | **FULL** | Только ПРОД; нужны данные 🔑 (B-03) |  |
| S35 | Бот сообщает заявителю УК о статусе заявки | — | TC-019 | test_d2_application_notifications | **FULL** | Только ПРОД; нужны данные 🔑 (B-03) |  |
| S36 | Политика данных и хранение: `/privacy`, ссылки из бота и мини-приложения, буфер переписки не дольше 72 ч, цитаты с псевдонимами | TC-078, TC-095 | TC-003, TC-050, TC-062, TC-066 | test_passive_capture (буфер 72 ч) | **FULL** | ЛОК — сразу; ПРОД — после 🔑 |  |

**Итого:** 36 сценариев: FULL — 34, PARTIAL — 1, BLOCKED — 1. Сценариев без тест-кейсов нет.

## 2. Проектная возможность → сценарий → тест-кейсы

| Проектная возможность | Scenario | TC | Статус покрытия |
|---|---|---|---|
| Приём сообщения о проблеме в личке бота | S02 | TC-052, TC-053, TC-054, TC-055, TC-056 | FULL |
| Приём `/report` в домовом чате | S03 | TC-057, TC-059, TC-060 | FULL |
| Пассивное чтение переписки и сигналы | S04, S08 | TC-062, TC-063 | FULL |
| Распознавание опасности правилами: памятка в чат, оповещение оператору | S05 | TC-064, TC-065, TC-055, TC-039 | FULL |
| Маршрутизация по справочнику: УК / внешний / неопределён | S02, S06, S25 | TC-034, TC-036, TC-037, TC-052, TC-085, TC-086 | FULL |
| Карточка «Куда обратиться» с источником и датой проверки | S01 | TC-036, TC-049 | FULL |
| Черновик обращения, копирование, «Я отправил(а)» | S01 | TC-036, TC-049, TC-099 | FULL |
| Форма «Сообщить о проблеме» в мини-приложении (2 шага) | S06 | TC-034, TC-046 | FULL |
| Дубли: осознанное присоединение («Это та же проблема») | S02, S06 | TC-038, TC-053, TC-058 | FULL |
| Заявка УК (Ticket): полный жизненный цикл | S03, S09 | TC-035, TC-041, TC-057 | FULL |
| Проверка результата жителем, возврат той же заявки | S07 | TC-035, TC-057 | FULL |
| Пост заявки в чате и его правка при смене статуса | S04 | TC-057, TC-062 | FULL |
| «Меня тоже касается» | S04 | TC-058 | FULL |
| Личные уведомления жителю о ходе заявки | S34 | TC-057 | FULL |
| Решения по сигналам | S08 | TC-062, TC-063 | FULL |
| Заявка УК на подключение и страница статуса | S10 | TC-014…TC-019 | FULL |
| Самостоятельное создание администратора УК | S10 | TC-016 | FULL |
| Перевыпуск приглашения первого администратора | S27 | TC-016 шаг 3а | FULL |
| Дома УК: одиночно, списком, из заявки; одобрение пачкой с регионом | S11 | TC-020…TC-024 | FULL |
| Регион и часовой пояс дома | S25 | TC-020, TC-022, TC-024, TC-085…TC-088 | PARTIAL (тихие часы по поясу вручную частично) |
| Сотрудники: приглашение, назначения, отзыв, сброс | S13 | TC-025…TC-030 | FULL |
| Открытая регистрация сотрудников `/join` | S13 | TC-031 | FULL |
| Вход по паролю и TOTP, коды восстановления, блокировка | S14 | TC-006…TC-013 | FULL |
| Открытый доступ к дому | S15 | TC-047, TC-048, TC-049 | FULL |
| Житель = участник чата | S16 | TC-072, TC-071 | FULL |
| Подключение MAX-чата кодом | S12 | TC-068, TC-069 | FULL |
| Квота чатов и расширение | S12 | TC-033, TC-070 | FULL |
| Приостановка привязки при удалении бота | S12, S16 | TC-071 | FULL |
| Включение чтения чата, сообщение о чтении | S17 | TC-066 | FULL |
| Настройки публикаций бота и тихие часы чата | S17 | TC-067 | FULL |
| Объявления: черновик, предпросмотр, отправка, исправление, удаление | S18 | TC-073, TC-074, TC-076 | FULL |
| Личные рассылки и отписка | S18 | TC-077 | FULL |
| Опросы | S19 | TC-075, TC-076 | FULL |
| «Мой дом»: навигатор, контакты, аварийный блок, тарифы | S20 | TC-078, TC-050, TC-045 | FULL |
| Совет дома и предложения жителей | S21 | TC-079 | FULL |
| Приём жителей и напоминание | S22 | TC-080 | FULL |
| Ежедневная сводка сотруднику | S23 | TC-082 | FULL |
| Сообщения платформы для УК | S23 | TC-083 | FULL |
| Вопрос о результате обращения через 14 дней | S24 | TC-084 | BLOCKED (14 дней, только MAX) |
| Обзор платформы: очередь, бюджет модели, справочник | S26 | TC-089 | FULL |
| Обзор УК и CSV | S26 | TC-090 | FULL |
| Организации: квота, приостановка | S27 | TC-032, TC-033 | FULL |
| Аудит, состояние системы, спорные привязки | S27 | TC-091 | FULL |
| Публичные страницы и защита production | S28 | TC-001…TC-003 | FULL |
| Локальный запуск и демо-данные | S29 | TC-004, TC-005, TC-093 | FULL |
| Очередь задач в PostgreSQL, два пула воркеров | S30 | TC-092, TC-094, TC-095 | FULL |
| Идемпотентность и Problem Details | S31 | TC-096, TC-097, TC-099 | FULL |
| Разграничение доступа и маскирование 403/404 | S32 | TC-010, TC-027, TC-042, TC-044, TC-098 | FULL |
| Команды бота | S33 | TC-051 | FULL |
| Уведомления заявителю УК в MAX | S35 | TC-019 | FULL |
| Политика данных и срок хранения переписки | S36 | TC-003, TC-050, TC-062, TC-078, TC-095 | FULL |
| Сроки заявки («Указать срок») | — | — | Не покрыто — в интерфейсе нет (F-19); только API |
| Отзыв привязки чата (`revoke`) | — | TC-071 (приостановка) | Не покрыто — нет в API или UI (F-20) |

## 3. Роли → тест-кейсы

| Роль | Тест-кейсы | Позитив | Негатив / RBAC |
|---|---|---|---|
| Аноним | TC-002, TC-003, TC-010, TC-014, TC-018, TC-098 | да | да |
| Заявитель УК (по секретной ссылке) | TC-014…TC-019 | да | да |
| Житель — участник домового чата | TC-057…TC-062, TC-064, TC-072, TC-076, TC-077 | да | да |
| Житель по открытому доступу («посторонний») | TC-047, TC-049, TC-050, TC-079, TC-080, TC-086 | да | да |
| Демо-житель (ЛОК) | TC-034…TC-040, TC-044…TC-046, TC-081 | да | да |
| Сосед / второй житель | TC-038, TC-040, TC-058, TC-075 | да | да |
| Житель другого дома | TC-044, TC-098 | да | да |
| Член совета дома | TC-079 | да | да |
| Администратор УК | TC-016, TC-020…TC-033, TC-041, TC-047, TC-057, TC-062…TC-080 | да | да |
| Ответственный за дом | TC-026, TC-041…TC-043 | да | да |
| Оператор с назначением | TC-026, TC-035, TC-037 | да | да |
| Оператор без назначения | TC-025, TC-042, TC-098 | да | да |
| Отозванный сотрудник | TC-029, TC-042 | да | да |
| Администратор другой УК | TC-042, TC-098 | да | да |
| Оператор с MAX (получатель оповещений и сводки) | TC-064, TC-082 | да | да |
| Суперадмин платформы | TC-006…TC-011, TC-013…TC-024, TC-031…TC-033, TC-048, TC-083, TC-087, TC-089, TC-091 | да | да |

## 4. Интерфейсы (маршруты frontend) → тест-кейсы

| Интерфейс / маршрут | Тест-кейсы |
|---|---|
| `/` (лендинг на ПРОД) и `/site` | TC-003 |
| `/privacy` | TC-003, TC-050 |
| `/company/apply` | TC-014, TC-017, TC-018, TC-019 |
| `/company/apply/status/<секрет>` | TC-014…TC-019 |
| `/login` | TC-006…TC-013 |
| `/admin/login`, `/admin/` (Заявки, `?ticket=`) | TC-010, TC-034, TC-035, TC-041…TC-043 |
| `/admin/?section=signals&signal=` | TC-062…TC-064 |
| `/admin/houses` (Дома / Мои дома, совет, открытый доступ, сведения) | TC-020…TC-022, TC-026, TC-047, TC-078, TC-079 |
| `/admin/staff` | TC-025…TC-030 |
| `/admin/max` | TC-033, TC-066…TC-071 |
| `/admin/organization` | TC-027, TC-078 |
| `/admin/mailings` | TC-067, TC-073…TC-077, TC-092 |
| `/admin/notices` | TC-082, TC-083 |
| `/admin/reception` | TC-080 |
| `/admin/` Обзор | TC-016, TC-090 |
| `/admin/invite/<секрет>` | TC-016, TC-025, TC-030 |
| `/admin/reset/<секрет>` | TC-028 |
| `/join/<код>` | TC-031 |
| `/platform-admin/` Обзор | TC-006, TC-024, TC-089 |
| `/platform-admin/applications` | TC-014…TC-017 |
| `/platform-admin/quota-requests` | TC-033, TC-070 |
| `/platform-admin/companies` | TC-016, TC-031…TC-033 |
| `/platform-admin/house-management-requests` | TC-020…TC-023 |
| `/platform-admin/houses` | TC-024, TC-048 |
| `/platform-admin/binding-disputes`, `health`, `audit` | TC-071, TC-091 |
| `/platform-admin/mailings` | TC-083 |
| Мини-приложение: доска, карточка проблемы, форма | TC-034, TC-035, TC-044…TC-046 |
| Мини-приложение: «Куда обратиться», черновик | TC-036, TC-049 |
| Мини-приложение: «Мои обращения», «Объявления», опрос, «Мой дом», работы, приём | TC-073, TC-075, TC-077…TC-081 |
| Мини-приложение: «Как открыть свой дом» (нет дома) | TC-047, TC-072 |
| Бот в личке | TC-049…TC-056, TC-059, TC-068, TC-077, TC-082 |
| Домовой чат MAX | TC-057…TC-067, TC-076 |
| Служебные адреса, `/docs` | TC-001, TC-004 |

## 5. Переходы состояний → тест-кейсы

| Объект | Переход | Тест-кейсы |
|---|---|---|
| Заявка (Ticket) | new → accepted → in_progress → verification_pending → closed | TC-035, TC-057 |
| Заявка | verification_pending → in_progress («Проблема осталась», та же T-N) | TC-035, TC-057 |
| Заявка | accepted → needs_clarification → accepted (resume) | TC-041 |
| Заявка | accepted → waiting_external → cancelled | TC-041 |
| Заявка | создание сразу в needs_clarification (ответственный не определён) | TC-037 |
| Заявка | конфликт версий: повторное accept → 409 | TC-043, TC-097 |
| Заявка | снятие исполнителя при отзыве сотрудника | TC-029 |
| Сигнал | new → converted (создать заявку / присоединить) | TC-062, TC-063 |
| Сигнал | new → routed_external | TC-063 |
| Сигнал | new → in_review (выбрать маршрут) → dismissed | TC-063 |
| Сигнал | решение по закрытому сигналу недоступно; устаревшая версия | TC-063 |
| Заявка УК | submitted → needs_info → under_review → approved | TC-014…TC-016 |
| Заявка УК | submitted → rejected; повторное решение запрещено | TC-017 |
| Заявка на дом | submitted → approved (одиночно, пачкой); rejected; конфликт периода | TC-020…TC-023 |
| Приглашение | pending → accepted; pending → revoked; повторное использование | TC-016, TC-025, TC-030 |
| Сотрудник | active → revoked | TC-029 |
| Организация | active → suspended → active | TC-032 |
| Подключение чата | created → connector_claimed → chat_detected → max_verified → completed; cancelled; expired | TC-068, TC-069 |
| Привязка чата | active → suspended (удаление бота) | TC-071 |
| Квота | запрос: pending → partially_approved / approved; cancelled | TC-033, TC-070 |
| Открытый доступ | выключен → включён → выключен; закрыт платформой | TC-047, TC-048 |
| Членство жителя | нет → chat_member (вступил) → revoked (вышел); open_access → revoked (выключение) | TC-072, TC-047 |
| Рассылка | draft → scheduled → sent; scheduled → cancelled; sent → retracted; правка отправленного | TC-073, TC-074, TC-092 |
| Опрос | открыт → голос → изменение → закрыт | TC-075, TC-076 |
| Черновик обращения | draft → filed (неизменяем) | TC-036, TC-099 |
| Запись на приём | booked → cancelled | TC-080 |
| Предложение жителя | new → converted | TC-079 |
| Сессия сотрудника | login → password_change → mfa_enroll → authenticated → logout; блокировка | TC-006…TC-011 |

## 6. Интеграции → тест-кейсы

| Интеграция | Режим в тестах | Позитивные TC | Отказ / негатив |
|---|---|---|---|
| MAX Bot API — входящие события (вебхук) | Реальная, ПРОД | TC-049…TC-072 | TC-002 (без секрета → 401) |
| MAX — отправка и правка сообщений, кнопки | Реальная, ПРОД | TC-057, TC-062, TC-064, TC-076, TC-077 | TC-059 (нет диалога → ответ в группе) |
| MAX — проверка участника и прав администратора чата | Реальная, ПРОД | TC-068, TC-072 | TC-069 (у бота нет прав), TC-071 (бот удалён) |
| MAX Mini App — вход по initData | Реальная, ПРОД | TC-049, TC-061 | TC-002 (тестовый вход в production выключен) |
| Модель (polza.ai, `openai/gpt-5-mini`) | Реальная, ПРОД | TC-062, TC-052 | TC-094 (модель недоступна → правила); на ЛОК — правила (`LLM_PROVIDER=rules`) |
| Официальные сервисы (Народный контроль, Наш город, Госуслуги) | Внешние ссылки из справочника: продукт никуда не отправляет | TC-036, TC-049, TC-086 | — |
| PostgreSQL как БД и очередь задач | Реальная, ЛОК и ПРОД | TC-092, TC-093, TC-095 | TC-092 (воркер остановлен) |
| Двойник MAX и фейковая модель | **Заглушки** — только в TC-005 (`scenario_run`) | TC-005 | Это не проверка реальной интеграции |
| RabbitMQ / Redis / брокер | В проекте нет | — | — |

## 7. API → тест-кейсы

Все 172 обработчика из `src/domsignal/api/routes/*.py`. Большинство вызываются интерфейсом: кейс проверяет их через UI, а не прямым запросом.

| Роутер | Метод | Путь | Тест-кейсы | Статус |
|---|---|---|---|---|
| `administration.py` | GET | `/api/v1/admin/bootstrap` | TC-016, TC-026, TC-027 | Покрыт |
| `administration.py` | GET | `/api/v1/companies/{company_id}/employee-invitations` | TC-025, TC-030 | Покрыт |
| `administration.py` | GET | `/api/v1/companies/{company_id}/house-management-requests` | TC-020…TC-022 | Покрыт |
| `administration.py` | GET | `/api/v1/companies/{company_id}/houses` | TC-020, TC-026 | Покрыт |
| `administration.py` | GET | `/api/v1/companies/{company_id}/houses/{house_id}` | TC-020, TC-026 | Покрыт |
| `administration.py` | GET | `/api/v1/companies/{company_id}/organization` | TC-027, TC-078 | Покрыт |
| `administration.py` | GET | `/api/v1/companies/{company_id}/overview` | TC-090 | Покрыт |
| `administration.py` | GET | `/api/v1/companies/{company_id}/staff` | TC-025…TC-030, TC-098 | Покрыт |
| `administration.py` | GET | `/api/v1/companies/{company_id}/staff/{user_id}` | TC-025…TC-030, TC-098 | Покрыт |
| `administration.py` | GET | `/api/v1/platform/audit` | TC-091 | Покрыт |
| `administration.py` | GET | `/api/v1/platform/binding-disputes` | TC-071, TC-091 | Покрыт |
| `administration.py` | GET | `/api/v1/platform/bootstrap` | TC-006, TC-027 | Покрыт |
| `administration.py` | GET | `/api/v1/platform/companies` | TC-031, TC-032, TC-033 | Покрыт |
| `administration.py` | GET | `/api/v1/platform/companies/{obj}` | TC-031, TC-032, TC-033 | Покрыт |
| `administration.py` | GET | `/api/v1/platform/company-applications` | TC-014…TC-017 | Покрыт |
| `administration.py` | GET | `/api/v1/platform/company-applications/{obj}` | TC-014…TC-017 | Покрыт |
| `administration.py` | GET | `/api/v1/platform/health` | TC-091 | Покрыт |
| `administration.py` | GET | `/api/v1/platform/house-management-requests` | TC-020…TC-023 | Покрыт |
| `administration.py` | GET | `/api/v1/platform/house-management-requests/{obj}` | TC-020…TC-023 | Покрыт |
| `administration.py` | GET | `/api/v1/platform/houses` | TC-024, TC-048 | Покрыт |
| `administration.py` | GET | `/api/v1/platform/open-houses` | TC-048 | Покрыт |
| `administration.py` | GET | `/api/v1/platform/region-packs` | TC-020, TC-022, TC-024 | Покрыт |
| `administration.py` | POST | `/api/v1/auth/employee/invitations/accept` | TC-016, TC-025, TC-030 | Покрыт |
| `administration.py` | POST | `/api/v1/auth/employee/invitations/claim` | TC-016, TC-025, TC-030 | Покрыт |
| `administration.py` | POST | `/api/v1/auth/employee/invitations/preview` | TC-016, TC-025, TC-030 | Покрыт |
| `administration.py` | POST | `/api/v1/auth/employee/invitations/register` | TC-016, TC-025, TC-030 | Покрыт |
| `administration.py` | POST | `/api/v1/companies/{company_id}/employee-invitations` | TC-025, TC-030 | Покрыт |
| `administration.py` | POST | `/api/v1/companies/{company_id}/employee-invitations/{invite_id}/revoke` | TC-025, TC-030 | Покрыт |
| `administration.py` | POST | `/api/v1/companies/{company_id}/house-management-requests` | TC-020…TC-022 | Покрыт |
| `administration.py` | POST | `/api/v1/companies/{company_id}/house-management-requests/batch` | TC-021 | Покрыт |
| `administration.py` | POST | `/api/v1/companies/{company_id}/houses/{house_id}/open-access` | TC-047 | Покрыт |
| `administration.py` | POST | `/api/v1/companies/{company_id}/staff/{user_id}/assignments` | TC-026 | Покрыт |
| `administration.py` | POST | `/api/v1/companies/{company_id}/staff/{user_id}/revoke` | TC-029, TC-030 | Покрыт |
| `administration.py` | POST | `/api/v1/onboarding/company-applications` | TC-014, TC-017, TC-018 | Покрыт |
| `administration.py` | POST | `/api/v1/platform/companies/{obj}/invitations/first-admin` | TC-016 шаг 3а | Покрыт |
| `administration.py` | POST | `/api/v1/platform/companies/{obj}/{action}` | TC-031, TC-032, TC-033 | Покрыт |
| `administration.py` | POST | `/api/v1/platform/company-applications/{obj}/{action}` | TC-014…TC-017 | Покрыт |
| `administration.py` | POST | `/api/v1/platform/house-management-requests/approve-batch` | TC-020 | Покрыт |
| `administration.py` | POST | `/api/v1/platform/house-management-requests/{obj}/approve` | TC-020…TC-023 | Покрыт |
| `administration.py` | POST | `/api/v1/platform/house-management-requests/{obj}/{action}` | TC-020…TC-023 | Покрыт |
| `administration.py` | POST | `/api/v1/platform/houses/{house_id}/open-access/close` | TC-048 | Покрыт |
| `administration.py` | POST | `/api/v1/platform/houses/{house_id}/region` | TC-024 | Покрыт |
| `appeals.py` | GET | `/api/v1/appeal-drafts/{draft_id}` | TC-036, TC-049, TC-099 | Покрыт |
| `appeals.py` | PATCH | `/api/v1/appeal-drafts/{draft_id}` | TC-036, TC-049, TC-099 | Покрыт |
| `appeals.py` | POST | `/api/v1/appeal-drafts` | TC-036, TC-049, TC-099 | Покрыт |
| `appeals.py` | POST | `/api/v1/appeal-drafts/{draft_id}/mark-filed` | TC-036, TC-049, TC-099 | Покрыт |
| `auth.py` | POST | `/api/v1/auth/max` | TC-049, TC-061 (вход мини-приложения из MAX) | Покрыт |
| `auth.py` | POST | `/api/v1/auth/test-session` | TC-002 (запрет на ПРОД), TC-004 | Покрыт |
| `chat_connections.py` | GET | `/api/v1/chat-connections/{request_id}` | TC-068, TC-069 | Покрыт |
| `chat_connections.py` | POST | `/api/v1/chat-bindings/{binding_id}/notice` | TC-066, TC-068 | Покрыт |
| `chat_connections.py` | POST | `/api/v1/chat-bindings/{binding_id}/passive-capture` | TC-066 | Покрыт |
| `chat_connections.py` | POST | `/api/v1/chat-connections/{request_id}/approve` | TC-068, TC-069 | Покрыт |
| `chat_connections.py` | POST | `/api/v1/chat-connections/{request_id}/cancel` | TC-068, TC-069 | Покрыт |
| `chat_connections.py` | POST | `/api/v1/chat-connections/{request_id}/reject` | TC-068, TC-069 | Покрыт |
| `chat_connections.py` | POST | `/api/v1/houses/{house_id}/chat-connections` | TC-033 (инициация), TC-068…TC-070 | Покрыт |
| `community.py` | GET | `/api/v1/houses/{house_id}/announcements` | TC-073, TC-075 | Покрыт |
| `community.py` | GET | `/api/v1/houses/{house_id}/completed-works` | TC-081 | Покрыт |
| `community.py` | GET | `/api/v1/houses/{house_id}/council` | TC-079 | Покрыт |
| `community.py` | GET | `/api/v1/houses/{house_id}/overview` | TC-078, TC-050 | Покрыт |
| `community.py` | GET | `/api/v1/houses/{house_id}/reception` | TC-080 | Покрыт |
| `community.py` | GET | `/api/v1/me/activity` | TC-036, TC-081 | Покрыт |
| `community.py` | GET | `/api/v1/me/preferences` | TC-077 | Покрыт |
| `community.py` | GET | `/api/v1/polls/{poll_id}` | TC-075, TC-076 | Покрыт |
| `community.py` | POST | `/api/v1/houses/{house_id}/council/announcements` | TC-079 | Покрыт |
| `community.py` | POST | `/api/v1/houses/{house_id}/council/polls` | TC-079 | Покрыт |
| `community.py` | POST | `/api/v1/houses/{house_id}/proposals` | TC-079 | Покрыт |
| `community.py` | POST | `/api/v1/houses/{house_id}/reception/bookings` | TC-080 | Покрыт |
| `community.py` | POST | `/api/v1/houses/{house_id}/reception/bookings/{booking_id}/cancel` | TC-080 | Покрыт |
| `community.py` | POST | `/api/v1/me/preferences` | TC-077 | Покрыт |
| `community.py` | POST | `/api/v1/polls/{poll_id}/vote` | TC-075, TC-076 | Покрыт |
| `company_signup.py` | GET | `/api/v1/auth/employee/destinations` | TC-007, TC-029, TC-032 | Покрыт |
| `company_signup.py` | GET | `/api/v1/companies/{company_id}/chat-quota` | TC-033, TC-070 | Покрыт |
| `company_signup.py` | GET | `/api/v1/platform/chat-quota-requests` | TC-033, TC-070 | Покрыт |
| `company_signup.py` | GET | `/api/v1/platform/companies/{company_id}/chat-quota` | TC-033, TC-070 | Покрыт |
| `company_signup.py` | GET | `/api/v1/platform/companies/{company_id}/open-registration` | TC-031 | Покрыт |
| `company_signup.py` | POST | `/api/v1/auth/employee/credential-reset/complete` | TC-028 | Покрыт |
| `company_signup.py` | POST | `/api/v1/auth/employee/credential-reset/preview` | TC-028 | Покрыт |
| `company_signup.py` | POST | `/api/v1/auth/employee/join/preview` | TC-031 | Покрыт |
| `company_signup.py` | POST | `/api/v1/auth/employee/join/register` | TC-031 | Покрыт |
| `company_signup.py` | POST | `/api/v1/companies/{company_id}/chat-quota/requests` | TC-033, TC-070 | Покрыт |
| `company_signup.py` | POST | `/api/v1/companies/{company_id}/chat-quota/requests/{request_id}/cancel` | TC-033, TC-070 | Покрыт |
| `company_signup.py` | POST | `/api/v1/companies/{company_id}/staff/{user_id}/credential-reset` | TC-028, TC-030 | Покрыт |
| `company_signup.py` | POST | `/api/v1/onboarding/application-status` | TC-014…TC-017 | Покрыт |
| `company_signup.py` | POST | `/api/v1/onboarding/application-status/admin-invitation` | TC-016 | Покрыт |
| `company_signup.py` | POST | `/api/v1/onboarding/application-status/notify-link` | TC-019 | Покрыт |
| `company_signup.py` | POST | `/api/v1/onboarding/application-status/reply` | TC-015 | Покрыт |
| `company_signup.py` | POST | `/api/v1/platform/chat-quota-requests/{request_id}/decide` | TC-033, TC-070 | Покрыт |
| `company_signup.py` | POST | `/api/v1/platform/companies/{company_id}/chat-quota` | TC-033, TC-070 | Покрыт |
| `company_signup.py` | POST | `/api/v1/platform/companies/{company_id}/open-registration` | TC-031 | Покрыт |
| `dashboards.py` | GET | `/api/v1/companies/{company_id}/dashboard` | TC-090 | Покрыт |
| `dashboards.py` | GET | `/api/v1/companies/{company_id}/dashboard.csv` | TC-090 | Покрыт |
| `dashboards.py` | GET | `/api/v1/platform/dashboard` | TC-089 | Покрыт |
| `employee_auth.py` | GET | `/api/v1/auth/employee/session` | TC-006…TC-011 | Покрыт |
| `employee_auth.py` | POST | `/api/v1/auth/employee/login` | TC-006…TC-011 | Покрыт |
| `employee_auth.py` | POST | `/api/v1/auth/employee/logout` | TC-006…TC-011 | Покрыт |
| `employee_auth.py` | POST | `/api/v1/auth/employee/mfa/challenge` | TC-006, TC-009, TC-012 | Покрыт |
| `employee_auth.py` | POST | `/api/v1/auth/employee/mfa/enroll` | TC-006, TC-009, TC-012 | Покрыт |
| `employee_auth.py` | POST | `/api/v1/auth/employee/mfa/verify` | TC-006, TC-009, TC-012 | Покрыт |
| `employee_auth.py` | POST | `/api/v1/auth/employee/password/change` | TC-006, TC-009, TC-012 | Покрыт |
| `employee_auth.py` | POST | `/api/v1/auth/employee/recovery` | TC-006, TC-009, TC-012 | Покрыт |
| `incidents.py` | GET | `/api/v1/houses/{house_id}/incidents` | TC-034, TC-044, TC-098 | Покрыт |
| `incidents.py` | GET | `/api/v1/incidents/{incident_id}` | TC-034, TC-044, TC-045 | Покрыт |
| `incidents.py` | GET | `/api/v1/route-outcomes/{outcome_id}` | TC-036, TC-049 | Покрыт |
| `incidents.py` | POST | `/api/v1/houses/{house_id}/reports/preview` | TC-034…TC-040, TC-046 | Покрыт |
| `incidents.py` | POST | `/api/v1/houses/{house_id}/reports/submit` | TC-034…TC-040, TC-046 | Покрыт |
| `incidents.py` | POST | `/api/v1/incidents/{incident_id}/join` | TC-038 | Покрыт |
| `incidents.py` | POST | `/api/v1/reports` | TC-096 | Покрыт |
| `mailings.py` | GET | `/api/v1/broadcasts/{broadcast_id}` | TC-073…TC-077, TC-092 | Покрыт |
| `mailings.py` | GET | `/api/v1/broadcasts/{broadcast_id}/preview` | TC-073…TC-077, TC-092 | Покрыт |
| `mailings.py` | GET | `/api/v1/chat-bindings/{binding_id}/settings` | TC-067 | Покрыт |
| `mailings.py` | GET | `/api/v1/companies/{company_id}/broadcast-houses` | TC-073…TC-077 | Покрыт |
| `mailings.py` | GET | `/api/v1/companies/{company_id}/broadcasts` | TC-073…TC-077 | Покрыт |
| `mailings.py` | GET | `/api/v1/companies/{company_id}/houses/{house_id}/council` | TC-079 | Покрыт |
| `mailings.py` | GET | `/api/v1/companies/{company_id}/me/settings` | TC-082 | Покрыт |
| `mailings.py` | GET | `/api/v1/companies/{company_id}/platform-notices` | TC-083 | Покрыт |
| `mailings.py` | GET | `/api/v1/companies/{company_id}/profile` | TC-078 | Покрыт |
| `mailings.py` | GET | `/api/v1/companies/{company_id}/reception-slots` | TC-080 | Покрыт |
| `mailings.py` | GET | `/api/v1/platform/broadcast-regions` | TC-083 | Покрыт |
| `mailings.py` | GET | `/api/v1/platform/broadcasts` | TC-083 | Покрыт |
| `mailings.py` | POST | `/api/v1/broadcasts/{broadcast_id}/cancel` | TC-073…TC-077, TC-092 | Покрыт |
| `mailings.py` | POST | `/api/v1/broadcasts/{broadcast_id}/close-poll` | TC-073…TC-077, TC-092 | Покрыт |
| `mailings.py` | POST | `/api/v1/broadcasts/{broadcast_id}/confirm` | TC-073…TC-077, TC-092 | Покрыт |
| `mailings.py` | POST | `/api/v1/broadcasts/{broadcast_id}/edit` | TC-073…TC-077, TC-092 | Покрыт |
| `mailings.py` | POST | `/api/v1/broadcasts/{broadcast_id}/retract` | TC-073…TC-077, TC-092 | Покрыт |
| `mailings.py` | POST | `/api/v1/broadcasts/{broadcast_id}/update` | TC-073…TC-077, TC-092 | Покрыт |
| `mailings.py` | POST | `/api/v1/chat-bindings/{binding_id}/settings` | TC-067 | Покрыт |
| `mailings.py` | POST | `/api/v1/companies/{company_id}/broadcasts` | TC-073…TC-077 | Покрыт |
| `mailings.py` | POST | `/api/v1/companies/{company_id}/houses/{house_id}/council/members` | TC-079 | Покрыт |
| `mailings.py` | POST | `/api/v1/companies/{company_id}/houses/{house_id}/council/members/{member_id}/revoke` | TC-079 | Покрыт |
| `mailings.py` | POST | `/api/v1/companies/{company_id}/houses/{house_id}/facts` | TC-078 | Покрыт |
| `mailings.py` | POST | `/api/v1/companies/{company_id}/me/settings` | TC-082 | Покрыт |
| `mailings.py` | POST | `/api/v1/companies/{company_id}/profile` | TC-078 | Покрыт |
| `mailings.py` | POST | `/api/v1/companies/{company_id}/proposals/{proposal_id}/poll` | TC-079 | Покрыт |
| `mailings.py` | POST | `/api/v1/companies/{company_id}/reception-slots` | TC-080 | Покрыт |
| `mailings.py` | POST | `/api/v1/companies/{company_id}/reception-slots/{slot_id}/cancel` | TC-080 | Покрыт |
| `mailings.py` | POST | `/api/v1/platform/broadcasts` | TC-083 | Покрыт |
| `max_ingress.py` | POST | `/max/replay` | — (служебный вход для тестов; на ПРОД выключен) | Не покрыт |
| `max_ingress.py` | POST | `/max/webhook` | TC-002; все кейсы блоков H–L (события MAX) | Покрыт |
| `me.py` | GET | `/api/v1/me` | TC-010, TC-098 | Покрыт |
| `me.py` | GET | `/api/v1/open-houses` | TC-047, TC-049 | Покрыт |
| `me.py` | POST | `/api/v1/open-houses/{house_id}/join` | TC-047, TC-049 | Покрыт |
| `signals.py` | GET | `/api/v1/signals` | TC-062, TC-063, TC-064 | Покрыт |
| `signals.py` | GET | `/api/v1/signals/{signal_id}` | TC-062, TC-063, TC-064 | Покрыт |
| `signals.py` | POST | `/api/v1/signals/{signal_id}/choose-route` | TC-062, TC-063, TC-064 | Покрыт |
| `signals.py` | POST | `/api/v1/signals/{signal_id}/create-ticket` | TC-062, TC-063, TC-064 | Покрыт |
| `signals.py` | POST | `/api/v1/signals/{signal_id}/dismiss` | TC-062, TC-063, TC-064 | Покрыт |
| `signals.py` | POST | `/api/v1/signals/{signal_id}/join` | TC-062, TC-063, TC-064 | Покрыт |
| `signals.py` | POST | `/api/v1/signals/{signal_id}/route-external` | TC-062, TC-063, TC-064 | Покрыт |
| `system.py` | GET | `/api/v1/capabilities` | TC-001, TC-004 | Покрыт |
| `system.py` | GET | `/health` | TC-001, TC-004 | Покрыт |
| `system.py` | GET | `/ready` | TC-001, TC-004 | Покрыт |
| `system.py` | GET | `/version` | TC-001, TC-004 | Покрыт |
| `tickets.py` | GET | `/api/v1/incidents/{incident_id}/work-status` | TC-035 | Покрыт |
| `tickets.py` | GET | `/api/v1/notification-launch/{ref}` | TC-061, TC-076 (кнопки «Открыть»/«Голосовать») | Покрыт |
| `tickets.py` | GET | `/api/v1/tickets` | TC-034, TC-041, TC-042, TC-097 | Покрыт |
| `tickets.py` | GET | `/api/v1/tickets/{ticket_id}` | TC-034, TC-041, TC-042, TC-097 | Покрыт |
| `tickets.py` | GET | `/api/v1/tickets/{ticket_id}/assignees` | TC-041 | Покрыт |
| `tickets.py` | GET | `/api/v1/tickets/{ticket_id}/deadlines` | TC-041 (блок «Сроки» в карточке заявки) | Покрыт |
| `tickets.py` | GET | `/api/v1/tickets/{ticket_id}/events` | TC-041 | Покрыт |
| `tickets.py` | GET | `/api/v1/tickets/{ticket_id}/work-attempts` | TC-035, TC-041, TC-057 | Покрыт |
| `tickets.py` | GET | `/api/v1/work-attempts/{attempt_id}/my-observations` | TC-035 | Покрыт |
| `tickets.py` | GET | `/api/v1/work-attempts/{attempt_id}/observations` | TC-035, TC-057 | Покрыт |
| `tickets.py` | POST | `/api/v1/tickets/{ticket_id}/accept` | TC-035, TC-041, TC-057 | Покрыт |
| `tickets.py` | POST | `/api/v1/tickets/{ticket_id}/assign` | TC-041, TC-042, TC-098 | Покрыт |
| `tickets.py` | POST | `/api/v1/tickets/{ticket_id}/cancel` | TC-041, TC-042, TC-098 | Покрыт |
| `tickets.py` | POST | `/api/v1/tickets/{ticket_id}/clarify` | TC-041, TC-042, TC-098 | Покрыт |
| `tickets.py` | POST | `/api/v1/tickets/{ticket_id}/deadlines` | — (нет в UI, F-19) | Не покрыт |
| `tickets.py` | POST | `/api/v1/tickets/{ticket_id}/resume` | TC-041, TC-042, TC-098 | Покрыт |
| `tickets.py` | POST | `/api/v1/tickets/{ticket_id}/start` | TC-035, TC-041, TC-057 | Покрыт |
| `tickets.py` | POST | `/api/v1/tickets/{ticket_id}/wait-external` | TC-041, TC-042, TC-098 | Покрыт |
| `tickets.py` | POST | `/api/v1/tickets/{ticket_id}/work-attempts` | TC-035, TC-041, TC-057 | Покрыт |
| `tickets.py` | POST | `/api/v1/work-attempts/{attempt_id}/observations` | TC-035, TC-057 | Покрыт |

**Итого:** 172 обработчиков; не покрыто ручными кейсами — 2:
- `POST /api/v1/tickets/{ticket_id}/deadlines` — в интерфейсе нет (F-19);
- `POST /max/replay` — служебный вход для тестов, на production выключен.

## 8. Индекс тест-кейсов

| TC | Название | Окружение | Приоритет | Сценарии | ⚠ | 🔑 |
|---|---|---|---|---|---|---|
| TC-001 | Служебные адреса production отвечают, версия совпадает с заявленной | ПРОД | Critical | S28 |  |  |
| TC-002 | Production закрыт от вызовов без авторизации | ПРОД | Critical | S28, S32 |  |  |
| TC-003 | Публичные страницы открываются и ведут куда нужно | ПРОД | High | S28, S36 |  |  |
| TC-004 | Локальный стенд запускается одной командой с демо-данными | ЛОК | Critical | S29 |  |  |
| TC-005 | Автоматический регресс сквозных сценариев (для разработчика) | ЛОК | High | S29, S01, S05, S10, S15, S16, S18, S19, S25 |  |  |
| TC-006 | Первый вход суперадмина: временный пароль → свой пароль → TOTP → коды восстановления | ЛОК | Critical | S14 |  |  |
| TC-007 | Повторный вход с кодом TOTP и выбор кабинета через /login | ЛОК | Critical | S14 |  |  |
| TC-008 | Неверный пароль, неизвестный логин и повтор временного пароля | ЛОК | High | S14 |  |  |
| TC-009 | Неверный код TOTP; вход по коду восстановления; код восстановления одноразовый | ЛОК | High | S14 |  |  |
| TC-010 | Выход из кабинета и доступ к защищённым адресам без входа | ЛОК | Critical | S14, S32 |  |  |
| TC-011 | Блокировка входа после серии неудачных попыток | ЛОК | Medium | S14 |  |  |
| TC-012 | Требования к паролю при смене и регистрации | ЛОК | Medium | S14, S13 |  |  |
| TC-013 | Вход сотрудников в production-кабинеты | ПРОД | Critical | S14, S28 |  | 🔑 |
| TC-014 | Заявка УК и страница статуса | ЛОК | Critical | S10 |  |  |
| TC-015 | Платформа запрашивает уточнения, заявитель отвечает | ЛОК | High | S10 |  |  |
| TC-016 | Одобрение с квотой и самостоятельное создание администратора УК | ЛОК | Critical | S10, S13, S14 |  |  |
| TC-017 | Дубль ИНН: одобрение запрещено, отказ виден заявителю | ЛОК | High | S10 |  |  |
| TC-018 | Проверки формы заявки и неверная ссылка на статус | ЛОК | Medium | S10 |  |  |
| TC-019 | Уведомления о статусе заявки УК приходят в MAX | ПРОД | Medium | S35 | ⚠ | 🔑 |
| TC-020 | Адреса из заявки → заявки на дома → платформа одобряет их пачкой с регионом | ЛОК | Critical | S11, S25 |  |  |
| TC-021 | Список адресов: пропуск дублей и уже управляемых домов | ЛОК | High | S11 |  |  |
| TC-022 | Одиночная заявка на дом в другом регионе → одобрение «Создать новый дом» (Москва) | ЛОК | High | S11, S25 |  |  |
| TC-023 | Одобрение дома: без региона нельзя, пересечение периода и прошлая дата отклоняются | ЛОК | High | S11, S25 |  |  |
| TC-024 | Дом без региона: «Регион не задан» → «Задать регион» | ЛОК | Medium | S25, S27 |  |  |
| TC-025 | Приглашение оператора и регистрация по ссылке | ЛОК | Critical | S13, S14 |  |  |
| TC-026 | Назначения на дома определяют разделы и очередь сотрудника | ЛОК | Critical | S13, S32 |  |  |
| TC-027 | Прямые адреса чужих разделов и чужого кабинета | ЛОК | High | S32 |  |  |
| TC-028 | Сброс пароля и MFA сотруднику | ЛОК | Medium | S13, S14 |  |  |
| TC-029 | Отзыв доступа сотрудника: его заявки возвращаются в очередь | ЛОК | High | S13, S09 |  |  |
| TC-030 | Защитные правила: последний администратор, сброс самому себе, отзыв приглашения | ЛОК | Medium | S13 |  |  |
| TC-031 | Открытая регистрация сотрудников по ссылке (/join) | ЛОК | Medium | S13, S27 |  |  |
| TC-032 | Приостановка и возобновление организации | ЛОК | High | S27 |  |  |
| TC-033 | Квота чатов: запрос расширения, частичное одобрение, изменение квоты платформой | ЛОК | High | S12, S27 |  |  |
| TC-034 | Житель сообщает о проблеме в зоне УК через мини-приложение | ЛОК | Critical | S06, S03 |  |  |
| TC-035 | Полный цикл заявки: принять → начать → выполнено → «Проблема осталась» → та же заявка → «Исправлено» → закрыта | ЛОК | Critical | S03, S07, S09 |  |  |
| TC-036 | Внешний маршрут: карточка «куда обратиться» → черновик обращения → «Я отправил(а) обращение» | ЛОК | Critical | S01, S06 |  |  |
| TC-037 | Ответственный не определён → заявка «Нужно уточнение» у диспетчера | ЛОК | High | S02, S06, S09 |  |  |
| TC-038 | Дубль: «Это та же проблема» / «Нет, это другое» | ЛОК | High | S06, S02 |  |  |
| TC-039 | Опасность в форме: блок 112 первым | ЛОК | Critical | S05, S06 |  |  |
| TC-040 | «Всё равно сообщить в УК» из внешней карточки | ЛОК | Medium | S06 |  |  |
| TC-041 | Управление заявкой: назначение, уточнение, ожидание другой службы, возобновление, отмена | ЛОК | High | S09 |  |  |
| TC-042 | Кто что может делать с заявкой | ЛОК | High | S09, S32 |  |  |
| TC-043 | Одновременное изменение заявки в двух вкладках | ЛОК | Medium | S09, S31 |  |  |
| TC-044 | Житель видит только свой дом | ЛОК | Critical | S32 |  |  |
| TC-045 | Навигация мини-приложения, перезагрузка, мобильная ширина | ЛОК | High | S06, S20 |  |  |
| TC-046 | Проверки формы сообщения о проблеме | ЛОК | Medium | S06 |  |  |
| TC-047 | Открытый доступ: включить → посторонний выбирает дом и сообщает → выключить → доступ пропал, заявка осталась у УК | ЛОК | Critical | S15, S01 |  |  |
| TC-048 | Платформа закрывает открытый доступ к дому | ЛОК | Medium | S15, S27 |  |  |
| TC-049 | Посторонний житель на телефоне: приветствие → «Попробовать» → выбор дома → карточка → черновик → «Я отправил(а) обращение» | ПРОД | Critical | S01, S15, S33 |  | 🔑 |
| TC-050 | Тот же путь в MAX Web и навигатор «Мой дом» | ПРОД | High | S01, S20, S36 |  |  |
| TC-051 | Команды бота: /help, /version, неизвестная команда, короткий текст | ПРОД | High | S33, S02 |  |  |
| TC-052 | Проблема в зоне УК в личке → заявка у УК | ПРОД | Critical | S02 | ⚠ | 🔑 |
| TC-053 | Дубль в личке: «Это та же проблема» / «Другое» | ПРОД | High | S02 |  |  |
| TC-054 | «Не проблема» в личке | ПРОД | Medium | S02 |  |  |
| TC-055 | Опасность в личке → блок безопасности | ПРОД | High | S05 |  |  |
| TC-056 | Лимит 10 сообщений о проблемах в сутки (опционально) | ПРОД | Medium | S02 | ⚠ |  |
| TC-057 | /report в чате → заявка → пост в чате → принятие → уведомление → выполнено → «Проблема осталась» → та же заявка → «Исправлено» → закрыта | ПРОД | Critical | S03, S07, S34 | ⚠ | 🔑 |
| TC-058 | «Меня тоже касается»: присоединение из чата | ПРОД | High | S04 |  |  |
| TC-059 | /report от человека без диалога с ботом → ответ в группе, карточка после «Начать» | ПРОД | High | S03, S02 | ⚠ |  |
| TC-060 | /report с внешним маршрутом от автора с диалогом → карточка в личку | ПРОД | High | S03 |  |  |
| TC-061 | Кнопка «Открыть» у поста заявки открывает мини-приложение на этой заявке | ПРОД | High | S04 |  |  |
| TC-062 | Ветка реплик в чате → сигнал в кабинете → «Создать заявку» → пост в чате | ПРОД | Critical | S04, S08, S36 | ⚠ | 🔑 |
| TC-063 | Решения по сигналам: присоединить, внешний маршрут, выбрать маршрут, закрыть | ПРОД | High | S08 | ⚠ |  |
| TC-064 | Опасность в чате: памятка в чат и оповещение оператору, повтор без второй памятки | ПРОД | Critical | S05 | ⚠ |  |
| TC-065 | Ложные срабатывания: отрицание, чужой дом, бытовой дым, учения | ПРОД | High | S05 | ⚠ |  |
| TC-066 | Чтение чата: включение и выключение, сообщение о чтении, повторная отправка | ПРОД | Medium | S17, S36 | ⚠ |  |
| TC-067 | Что бот публикует в чате и тихие часы | ПРОД | Medium | S17, S18 | ⚠ |  |
| TC-068 | Подключение нового чата кодом с проверкой прав | ПРОД | Critical | S12 | ⚠ | 🔑 |
| TC-069 | Ошибки подключения чата: нет прав у бота, неверный код, отмена | ПРОД | High | S12 |  |  |
| TC-070 | Лимит квоты → «Лимит исчерпан» → расширение → подключение | ПРОД | Critical | S12 | ⚠ | 🔑 |
| TC-071 | Удаление бота из чата приостанавливает привязку | ПРОД | High | S12, S16 | ⚠ |  |
| TC-072 | Вступление в чат даёт дом, выход — отнимает | ПРОД | High | S16 | ⚠ | 🔑 |
| TC-073 | Объявление в ленту дома: черновик → предпросмотр → подтверждение → лента → исправление → удаление | ЛОК | Critical | S18 |  |  |
| TC-074 | Отложенная отправка, отмена, ошибки времени | ЛОК | Medium | S18 |  |  |
| TC-075 | Опрос: голос, изменение голоса, второй житель, закрытие | ЛОК | High | S19 |  |  |
| TC-076 | Объявление и опрос в домовом чате: пост, «Голосовать», итоги правкой того же поста | ПРОД | High | S18, S19 | ⚠ | 🔑 |
| TC-077 | Рассылка в личку и «Не получать рассылки» | ПРОД | High | S18 | ⚠ |  |
| TC-078 | «Мой дом»: контакты УК, сведения о доме, аварийный блок, официальные сервисы | ЛОК | High | S20, S36 |  |  |
| TC-079 | Совет дома и предложения жителей | ЛОК+ПРОД | Medium | S21 |  | 🔑 |
| TC-080 | Приём жителей: время, запись, отмена | ЛОК+ПРОД | Medium | S22 |  | 🔑 |
| TC-081 | «Что сделано в доме» и «Мои обращения» | ЛОК | Medium | S20, S06 |  |  |
| TC-082 | Ежедневная сводка сотруднику в MAX | ПРОД | Medium | S23 |  |  |
| TC-083 | Сообщения платформы для УК | ЛОК | Medium | S23, S27 |  |  |
| TC-084 | Вопрос «Пришёл ли ответ?» через 14 дней после «Я отправил(а)» | ПРОД | Medium | S24 |  |  |
| TC-085 | Сравнение регионов: один код, разные пакеты данных | ЛОК | High | S25 |  |  |
| TC-086 | Московский дом → «Наш город» в мини-приложении | ЛОК | High | S25 |  |  |
| TC-087 | Новый дом RU-MOW в production: житель видит «Наш город» (шаг 5 D4) | ПРОД | High | S25, S11 | ⚠ | 🔑 |
| TC-088 | Часовой пояс дома: тихие часы по местному времени | ЛОК | Medium | S25 |  |  |
| TC-089 | Обзор платформы: плитки, воронка, очередь задач, справочник регионов | ЛОК | High | S26 |  |  |
| TC-090 | Обзор УК и выгрузка CSV | ЛОК | Medium | S26 |  |  |
| TC-091 | Аудит, состояние системы, спорные привязки | ЛОК | Medium | S27 |  |  |
| TC-092 | Операционный воркер остановлен: рассылка ждёт, после запуска уходит | ЛОК | Critical | S30, S18 |  |  |
| TC-093 | Перезапуск стенда без потери данных | ЛОК | High | S30, S29 |  |  |
| TC-094 | Модель недоступна или ai-worker остановлен → разбор правилами | ПРОД | High | S05, S30 |  |  |
| TC-095 | Состояние очереди после прогона | ЛОК | Medium | S30, S36 |  |  |
| TC-096 | Повтор POST /reports с тем же Idempotency-Key; тот же ключ с другим телом → 409 | ЛОК | High | S31 |  |  |
| TC-097 | Устаревшая версия заявки → 409; ошибка валидации → 422 в формате Problem Details | ЛОК | Medium | S31, S09 |  |  |
| TC-098 | Разграничение доступа на уровне API | ЛОК | Critical | S32 |  |  |
| TC-099 | Отправленный черновик нельзя изменить (в том числе через API) | ЛОК | Medium | S31, S01 |  | 🔑 |

## 9. Аудит полноты

| Вопрос | Ответ | Где |
|---|---|---|
| Все ли маршруты (routes) имеют пользовательский сценарий? | Да: 33 интерфейса и 170 из 172 обработчиков API. Не покрыты сроки заявки (нет UI) и служебный replay | Разделы 4, 7 |
| Все ли роли проверены? | Да: 16 ролей и контекстов, у каждой позитив и негатив | Раздел 3 |
| Все ли основные бизнес-процессы? | Да: 36 сценариев, у каждого есть TC | Раздел 1 |
| Все ли переходы состояний? | Да: 28 переходов по 17 объектам | Раздел 5 |
| Все ли интеграции? | Да. Реальные MAX и модель — на ПРОД; заглушки явно помечены | Раздел 6 |
| Асинхронная обработка? | Да: воркер остановлен → задача ждёт → выполнена один раз; модель остановлена → правила | TC-092, TC-094, TC-095 |
| Права доступа? | Да: UI и API, 403 и 404 по правилам маскирования | TC-010, TC-027, TC-042, TC-044, TC-098 |
| Happy path? | Да | TC-014→TC-016→TC-020→TC-034→TC-035; TC-049; TC-057 |
| Critical negative path? | Да: неверный вход, блокировка, дубль ИНН, пересечение периода, лимит квоты, конфликт версий, чужой дом, idempotency 409 | TC-008, TC-011, TC-017, TC-023, TC-043, TC-044, TC-070, TC-096 |
| Persistence? | Да: F5 и перезапуск стенда | TC-034, TC-036, TC-093 |
| Взаимодействие нескольких ролей? | Да: житель ↔ оператор ↔ администратор ↔ платформа | TC-035, TC-041, TC-047, TC-057, TC-062 |
| Полный E2E от первого действия до результата? | Да | ЛОК: TC-014 → TC-035; ПРОД: TC-049, TC-057 |

Пробелы, найденные при аудите, закрыты новыми шагами: перевыпуск приглашения первого администратора (TC-016, шаг 3а), пост совета в чат (TC-079, шаг 8), напоминание о приёме (TC-080, шаг 6), срок хранения переписки (TC-095, шаг 4).
