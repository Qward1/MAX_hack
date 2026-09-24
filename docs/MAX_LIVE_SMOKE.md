# MAX live smoke — RESIDENT / GROUP / TICKET PRODUCT LOOP LIVE VERIFIED (MAX WEB)

## P6c — закрытие AI-ступени, 24 сентября 2026

Выкладка — строка 6 таблицы чекпоинта P6b ниже. После выкладки (13:04 UTC):
`/ready` 200 снаружи, `/version` = `38cb5dfb4258972199d119162d4b110f13a918e7`,
`passive_ai_analysis: true`, webhook без секрета 401; перезапусков и ошибок
0; `ai_provider_composed` — `openai/gpt-5-mini`, таймаут 30 с; подписка MAX —
одна, тот же URL (по хэшу) и шесть типов, не менялась. Миграций нет. Время —
UTC; два критических сигнала P6b (дым, «человек не может выйти») оставались
открытыми, поэтому окна шли с `reasoning: low`. CI на `main` (`38cb5df`) —
зелёный (владелец, вкладка Actions).

| Шаг | Статус | Доказательства |
|---|---|---|
| 1. Житель A: газ в первом подъезде | **LIVE VERIFIED** | `preliminary_critical gas` 13:05:51 → памятка и оповещение `processed`; модель `window.v3`, `ok`, 8,97 с, 0,176 ₽, 601 токен ответа → `preliminary_reconciled critical/gas.smell` 13:06:01; подъезд «1», `place_from_rules`, маршрут `emergency_service`. События `subtype_from_danger` нет — `gas.smell` вернула модель. Владелец (снимок кабинета): «Запах газа», «Подъезд 1», «Экстренные службы» |
| 2. Оповещение оператору и сообщение с карточкой | **LIVE VERIFIED** | владелец смотрел личное оповещение оператору: цитата, время МСК и ссылка в кабинет — в порядке. `/report` об остановке и фонарях: первая попытка — в личном чате бота (13:08, событие принято, обращения и ответа нет: `/report` — команда домового чата); в группе TEST_MAX — приём 13:12:56, модель `ok` 3,4 с, 0,048 ₽, `municipality / pos_gosuslugi`, `route.action_card.v1` → доставка `accepted` 13:13:02. Владелец: «Все работает, все хорошо» — блок «Что делать:» понятен без пояснений |
| 3. Житель A: прошлое время (щиток) | **LIVE VERIFIED** (проверено по серверу, оператор недоступен) | `preliminary_critical electric` и `chat_memo_not_eligible electric` 13:15:58.916 — **памятки в чат нет**; оповещение оператору — `accepted` 13:15:59 (по прошлому времени остаётся). Модель `ok` 7,0 с, 0,133 ₽: `electrical.panel`, опровержение «прошлое» вместе с опасностью → `refutation_rejected`, сигнал критический |

**Модель за живой прогон:** 3 вызова, 0,357 ₽. **Находка вне AI-ступени:**
`/report` в личном чате бот молча игнорирует — без подсказки «пишите в
домовом чате».

## P6b checkpoint — 24 сентября 2026: памятка только по высокоточным срабатываниям, LLM-слой включён, шаг 6

Время — UTC (МСК = UTC+3). Участники: житель A (TEST_MAX); житель B —
оператор через `live_staff`, **доступа к его аккаунту у владельца в этот день
не было**: реплики «жителя B» отправлял житель A, оповещения оператору
(личный чат B) проверены по серверу — доставка `accepted` в MAX, цитата —
реплика-доказательство; текст оповещения глазами не подтверждён. Сотрудник
`live-test.operator` — в кабинете. Тексты людей и их идентификаторы не
приводятся.

| Выкладка | `BUILD_COMMIT` | Резервная копия до выкладки | Откат |
|---|---|---|---|
| 1 | `9fe99f2` (P6b: памятка, место из правил, режим модели, окна 6, таймаут профиля) | `domsignal-20260924T052804229056Z.dump`, 220 646 байт, 600, 369 строк оглавления; env `env-production-pre-p6b-20260924` (600) | `pre-72f3222` |
| 2 | `703a32a` (промпт `window.v3`, `low` при открытой опасности, черновик) | `domsignal-20260924T065443052845Z.dump`, 228 542 байт, 600, 369 | `pre-9fe99f2` |
| 3 | `fda0fa8` (склейка по ключу держит инвариант P6) | `domsignal-20260924T081650170516Z.dump`, 230 474 байт, 600, 369 | `pre-703a32a` |
| 4 | `12975c8` (короткое сообщение с карточкой, письмо без повторов; шаг 7в) | `domsignal-20260924T085950030647Z.dump`, 235 862 байт, 600, 369; env не менялся | `pre-fda0fa8` |
| 5 | `05a574f` (пошаговая инструкция «Что делать:» в сообщении с карточкой) | `domsignal-20260924T092403995820Z.dump`, 236 408 байт, 600, 369; env не менялся | `pre-12975c8` |
| 6 — P6c, итоговая | `38cb5df` («merge: AI stage close (P6c)»: газ → `gas.smell`, прошлое время без памятки, лимит ответа 2800 при открытой опасности), образ `sha256:d8bc6426ae60…` | `domsignal-20260924T130350697590Z.dump`, 236 408 байт, 600, 369; снята `pg_dump` без чистки старых копий; env не менялся (кроме `BUILD_COMMIT`), 600 | `pre-05a574f` |

Окружение (по именам): `LLM_TIMEOUT_SECONDS` убран — таймаут профиля 30 с
(`ai_provider_composed … ai_timeout_seconds=30.0`); `PASSIVE_WINDOW_MAX_LINES=6`,
`PASSIVE_LLM_ENABLED=true` у `api`, `worker`, `ai-worker`; mode 600. После
каждой выкладки: `/ready` 200 снаружи, `/version` = SHA, capabilities
`passive_ai_analysis: true`, webhook без секрета 401, подписка — одна, тот же
URL (по хэшу) и шесть типов, перезапусков и ошибок 0. Миграций в P6b нет.

| Шаг | Статус | Доказательства |
|---|---|---|
| 0. Очистка очереди | выполнено владельцем | два открытых сигнала P7b → `dismissed` 05:42 |
| 1. Учения | **LIVE VERIFIED** | приём 05:44:52 → `danger_negated` (учения отменили срабатывание); окно по тишине, модель `ok` 2,1 с, 0,021 ₽; сигналов 0, доставок 0 — ни памятки, ни оповещения |
| 2. «Спасибо пожарным» (отправлял житель A) | **LIVE VERIFIED** | приём 05:46:58 → `danger_negated`; модель `ok` 2,5 с, 0,022 ₽; сигналов и доставок 0 |
| 3. Освещение, подъезд словом | **LIVE VERIFIED** | сигнал `lighting.stairwell`, `strong`, **подъезд «3»**, флаг `place_from_rules`, маршрут `uk_internal`; «не горит» — `danger_negated`; доставок нет; модель 3,3 с, 0,043 ₽ |
| 4. Газ, подъезд 2 | **LIVE VERIFIED** | `preliminary_critical gas` 05:53:17.488, маршрут `emergency_112`, **подъезд «2»**; `chat_memo_queued` → памятка `accepted` 05:53:18.159 (текст подтверждён владельцем); `signal_alert` `accepted` 05:53:18.641, получатель 1, `evidence_mid` = реплика с газом; модель 2,96 с, 0,047 ₽. Подтип после разбора — `other.unspecified` (не `gas.smell`) |
| 5. «и дымом тоже тянет» | **LIVE VERIFIED** | новый критический сигнал только `smoke_fire` (газ из контекста не приписан), маршрут `emergency_112`; `signal_alert` `accepted` 05:56:32.778; `chat_memo_not_eligible` — памятки нет (реплика без места); модель 8,0 с, 0,046 ₽ |
| 6. Человек не может выйти (все реплики от жителя A) | **LIVE VERIFIED** с третьей попытки | **Попытка 1** (`9fe99f2`, окно 05:59): модель отнесла три реплики к открытому дымовому сигналу, `person_trapped` не вернула — FAILED; воспроизведено офлайн 0/6 при открытых сигналах об опасности (отчёт §11.9) → промпт `window.v3` и `reasoning: low` при открытой опасности. **Попытка 2** (`703a32a`, 07:20): модель вернула новый сигнал `person_trapped` (7,9 с, 0,14 ₽), но продукт склеил его с дымовым по ключу дедупликации (`other.unspecified` у обоих) → `danger_kind_added`, оповещение «новый признак» — FAILED → `danger_fits` на склейке по ключу. **Попытка 3** (`fda0fa8`, 08:31–08:32): ядро переименовало ссылку модели на открытый дымовой сигнал в новый (`field_dropped … нет опасности person_trapped, это новый сигнал`), продукт не склеил (`danger_not_joined`) → **отдельный** критический сигнал `person_trapped`, дымовой остался только с дымом; `signal_alert` `accepted` 08:32:06 (первое оповещение сигнала); памятки нет; модель 6,4 с, 0,13 ₽. Маршрут нового сигнала — «Не определён»: экстренного правила для `person_trapped` в справочнике нет |
| 7. `/report` → карточка → черновик → ПОС | **LIVE VERIFIED** | `/report` 06:12:37, модель `ok` 3,3 с, 0,038 ₽; `street_lighting.failure / municipal_territory → municipality / pos_gosuslugi`; `route_action_card` `accepted` 06:12:41; черновик v1 06:15:09; «Открыть официальный сервис ↗» активна и открыла Госуслуги / ПОС (владелец). Замечания владельца: «Скопировать текст» неактивна, текст нельзя править, текст слишком краткий — исправлено в `703a32a` |
| 7б. Черновик после исправлений | **LIVE VERIFIED** | `/report` 08:35:00 (модель 3,2 с, 0,129 ₽), карточка `accepted` 08:35:05, черновик v1 08:36:07; текст — письмо «Здравствуйте! / Обращаюсь как житель дома по адресу… / Суть проблемы… / Прошу сообщить о принятых мерах. / С уважением» (владелец прислал текст целиком). Новое замечание: сообщение с карточкой маршрута «слишком длинное и перегружено» — исправлено в `52251c8` |
| 7в. Короткое сообщение с карточкой (`12975c8`) | **LIVE VERIFIED** | владелец: «Устраивает»; без «Источник: …» и «Проверено без входа», в конце «Информация взята с: pos.gosuslugi.ru/landing». Пожелание владельца — пошаговая инструкция по кнопкам — добавлено (блок «Что делать:», шесть шагов) в итоговой выкладке; вживую инструкция не проверялась — **NOT RUN** |

**Модель за живой прогон:** 11 вызовов (9 окон + 2 `/report`), все `ok`,
**0,8302 ₽** (окна 0,6638 ₽, `/report` 0,1664 ₽), задержка окон 2,1–8,0 с;
окна при открытом сигнале об опасности после `703a32a` стоят 0,13–0,14 ₽
(`reasoning: low`), остальные — 0,02–0,05 ₽.

**Находки:** (1) экстренного правила для `person_trapped` в справочнике нет —
маршрут «Не определён»; основание по п. 21 ПП № 2071 не добавлялось без
прямой нормы — вопрос владельцу; (2) `reasoning: low` включается и для окна,
в котором сама опасная реплика уже дала открытый предварительный сигнал, и
для `/report` при открытых сигналах об опасности — стоимость таких вызовов
≈ 0,13 ₽ вместо ≈ 0,05 ₽; (3) подтип газового сигнала после разбора —
`other.unspecified`.

## P7b — выкладка роутера, выключателя модели окон и выгрузки D2 — 24 сентября 2026

Живой прогон не повторялся. `BUILD_COMMIT` = `72f32221b7cfdf48eb8525fab9ed26137cffc416`
(«merge: router on the P6 reference, passive model switch, D2 export (P7b)»),
образ `sha256:9bb5be42ca25d6f2d051ad3a079880c9667d8fb2e823d3fd50b9b949f46e3273`,
откат — `domsignal-backend:pre-9d4988d`; миграций нет; резервная копия
`/var/backups/domsignal/domsignal-20260923T211846070419Z.dump` (220 649 байт,
mode 600, `pg_restore --list` — 369 строк). После выкладки (≈21:19 UTC):
`/ready` 200 снаружи, `/version` = `72f3222`, webhook без секрета 401,
подписка — одна, прежние URL и типы; в `ai-worker` `PASSIVE_LLM_ENABLED` =
true (значение по умолчанию), модель `openai/gpt-5-mini`, таймаут 60 с;
перезапусков и ошибок нет.

## P7b — выкладка черновика обращения — 23 сентября 2026

Живой прогон не повторялся. `BUILD_COMMIT` = `9d4988dc0c02cd0d228e0dc54eb623d852a126d4`
(«merge: appeal draft holds only what goes into the service form (P7b)»),
образ `sha256:1b6446a78471d1c184db16162295ac2e721f9b879ff775077891784aeb67be2e`,
откат — `domsignal-backend:pre-286976a`; миграций нет; резервная копия
`/var/backups/domsignal/domsignal-20260923T201524467510Z.dump` (220 647 байт,
mode 600, `pg_restore --list` — 369 строк). После выкладки (≈20:16 UTC):
`/ready` 200 снаружи, `/version` = `9d4988d`, capabilities без изменений,
webhook без секрета 401, подписка — одна, прежние URL и типы; перезапусков и
ошибок нет. Модель — по-прежнему `openai/gpt-5-mini` (решение по
`sber/gigachat-2` — за владельцем).

## P7b — выкладка P6 и проводки — 23 сентября 2026

Живой прогон не повторялся; выкладка кода после слияния P6 и проводки
`OpenItem.danger_kinds`. Время — UTC.

| Параметр | Значение |
|---|---|
| `BUILD_COMMIT` | `286976a35832abca59fb51378d84ed43a39eb224` (`main` = `dev/b-experience` = `dev/a-core`, перенос бандлом) |
| Образ `domsignal-backend:local` | `sha256:f9ba735759da5c518811d2211357d2df494e24cb7aff0c5ff42618f2b231031b` (api, worker, ai-worker) |
| Откат | образ `domsignal-backend:pre-58b31f6`, прежний SHA `58b31f6` |
| Миграции | нет (`migrate` exit 0) |
| Резервная копия | `/var/backups/domsignal/domsignal-20260923T193049292440Z.dump`, 220 647 байт, mode 600, `pg_restore --list` — 369 строк |

После выкладки (≈19:31): `/ready` 200 снаружи, `/version` = `286976a`,
capabilities без изменений (`ai_analysis`, `routes`, `passive_capture` = true,
`test_auth` = false); webhook без секрета 401; `list` — одна подписка, прежние
URL и типы событий; `api`, `worker`, `ai-worker` без перезапусков и ошибок.
Модель — прежняя `openai/gpt-5-mini` (профиль P6: reasoning minimal, промпт
`window.v2`); таймаут в production — 60 с из `compose.prod.yaml`.

## P7b checkpoint — 23 сентября 2026: находки P7a, журналы без IP, основания ПОС

Выкладка без P6 — решение владельца (DEV-A выкладывает обновлённую версию после
слияния P6 сам). Время — UTC (МСК = UTC+3). Участники — как в P7a: житель A,
житель B (оператор через `live_staff`), сотрудник `live-test.operator` в
кабинете. Тексты людей и их идентификаторы не приводятся.

| Параметр | Значение |
|---|---|
| `BUILD_COMMIT` | `58b31f6c240a3c314f17f3d057bef1dabc57cdbb` (`main` = `dev/b-experience` = `dev/a-core`, перенос бандлом) |
| Образ `domsignal-backend:local` | `sha256:17bf1e2e23fa09e039967961473d5819e8b2e21f4c6777a64ba254ccc62fc8f2` (api, worker, ai-worker) |
| Откат | образ `domsignal-backend:pre-c68c9a9`, прежний SHA `c68c9a9` |
| Миграции | `20260923_0009 → 20260924_0010` (`explicit_intakes.analysis`), `migrate` exit 0 |
| Резервная копия | `/var/backups/domsignal/domsignal-20260923T145459117596Z.dump`, 210 109 байт, mode 600, `pg_restore --list` — 369 строк; копия env `env-production-pre-p7b-20260923` (mode 600) |
| Журналы | у всех семи контейнеров `json-file`, `max-size 10m`, `max-file 5`; контейнеры пересозданы (включая `db` и `caddy`, тома сохранены) |

После выкладки (контейнеры запущены в 14:56 UTC; живой прогон — 17:37–18:10 UTC): `/ready` 200 снаружи, `/version` = `58b31f6`,
capabilities без изменений (`ai_analysis`, `routes`, `passive_capture` = true,
`test_auth` = false); webhook без секрета 401; `list` — одна подписка, прежний
URL (не менялась); `ai-worker` работает, перезапусков 0. Журналы после
внешних запросов: адресов клиентов — 0; по одному адресу привязки/loopback в
`api`, `caddy`, `db`; строки `http_request` — только сети /24.

| Шаг (P7b §5) | Статус | Доказательства |
|---|---|---|
| 0. Очистка очереди | выполнено владельцем | три открытых сигнала P7a (`person_trapped` и два слабых) → `dismissed` |
| 1. Газ, подъезд 2 | **LIVE VERIFIED** | окно закрыто по опасности 17:37:49.007 → предварительный `critical` `f8eca647`, маршрут `emergency_service/emergency_112` 17:37:49.117; памятка `accepted` 17:37:49.495; `signal_alert` `accepted` 17:37:50.000 (получатель 1). Оповещение (снимок владельца): «Цитата: «…» — Житель A, 23.09.2026 20:37 МСК». Модель 17:38:14 `ok`, 25 149 мс, 0,4305 ₽: `gas.smell`, подъезд **2** цифрой |
| 2. Дым, новый вид | **LIVE VERIFIED** | новый `critical` `76f02e77` (`smoke_fire`), маршрут `emergency_service/emergency_112` 17:55:07.750; памятка (первая для дыма) `accepted` 17:55:08; `signal_alert` `accepted` 17:55:09 — тот же адресат, что в шаге 1; владелец: у жителя B оба сообщения. Модель (36 513 мс, 0,3609 ₽) отнесла реплику к `gas.smell` и добавила вид «газ» из реплики контекста → `danger_kind_added gas` → второе оповещение «новый признак опасности» `accepted` 17:55:45 |
| 3. Человек не может выйти | **LIVE VERIFIED** (оговорка) | газовые сигналы → «Внешний маршрут»; три реплики A/B/A, окно закрыто тишиной 18:03:33; модель `ok` 32 664 мс, 0,3353 ₽ → **отдельный** новый `critical` `131165a2` с `person_trapped` (не склеен с газовым); памятки нет; `signal_alert` `accepted` 18:04:08 (+35 с). Цитата оповещения — реплика-доказательство жителя B, а не первая реплика окна (жителя A); 21:02 МСК. Оговорка: без P6 модель приписала сигналу `gas.smell`, «газ», «дым» и подъезд 2 из реплик контекста |
| 4. Подъезд цифрой | **LIVE VERIFIED** | «Освещение подъезда», `strong`, **Подъезд: 3** — «В третьем подъезде», маршрут `uk_internal`; окно 18:07:01, модель 21 500 мс, 0,2024 ₽; памятки и оповещения нет («не горит» — отрицание пожара) |
| 5. `/report`, черновик, ссылка ПОС | **LIVE VERIFIED** | `max:` intake 18:09:15 → `ai.report.analyze` `ok`: **17 179 мс, 0,1549 ₽, 7 261 входной токен — записаны в `explicit_intakes.analysis` при внешнем маршруте** (в P7a терялись); `street_lighting.failure` → `municipality/pos_gosuslugi`; `route_action_card` `accepted` 18:09:34; черновик v1 18:10:23. Текст карточки и черновика у владельца: основание и факты с новыми источниками (страница сервиса, «Правила подачи» п. 3/5/9/10, 59-ФЗ ст. 12), «10 файлов» и «календарных» нет; строка канала со ссылкой `https://www.gosuslugi.ru/help/obratitsya_v_pos`. Кнопка «Открыть официальный сервис ↗» в черновике открыла сценарий «Сообщите, что вас волнует» — подтверждение владельца |

**Модель за прогон:** 5 вызовов (4 окна + 1 `/report`), все `ok`, стоимость
записана у каждого — **1,4840 ₽**; задержка 17,2–36,5 с.

**Находки:**
1. (DEV-A, P6) Без P6 модель берёт вид опасности, подтип и подъезд из реплик
   контекста: «и дымом тоже тянет» → `gas.smell` + «газ»; три реплики о
   запертом человеке → `gas.smell` с «газ»/«дым» и подъездом 2. Правка P6
   («только из реплик окна») это закрывает.
2. (DEV-B) Черновик обращения: в копируемый текст попадали факты канала с
   источниками, пометка ИИ и «ДомСигнал не отправляет…» — владелец: «текст
   написан плохо». Исправлено (решение владельца): в тексте только адресат,
   суть и место, остальное — на экране.
3. (владелец) Новое ограничение: разрешены только российские или китайские
   модели; production сейчас на `openai/gpt-5-mini`.

## P7a-закрытие — 23 сентября 2026: выкладка слитой версии, таймаут модели 60 с

Выкладка кода, слитого в `main`; новой функциональности нет, живой прогон в MAX
не повторялся. Время — UTC.

| Параметр | Значение |
|---|---|
| `BUILD_COMMIT` | `c68c9a9b414341f8ec40d51777ebf2985807b7e7` (`main` = `dev/b-experience`, перенос бандлом) |
| Образ `domsignal-backend:local` | `sha256:8d2b4e17c2b1611784cc20fb859dd8b4712d6d8a981a0eb1179d5f2807b95170` (api, worker, ai-worker) |
| Откат | образ `domsignal-backend:pre-1ebbf23`, прежний SHA `1ebbf23` |
| Миграции | нет; `alembic current` = `20260923_0009 (head)` до и после |
| Резервная копия | `/var/backups/domsignal/domsignal-20260923T123258073085Z.dump`, 210 030 байт, mode 600, `pg_restore --list` — 369 строк |
| Таймаут модели / аренда AI-пула | **60 с / 80 с** (было 45 / 65); те же значения — по умолчанию в `compose.prod.yaml` |
| Оператор в MAX | без изменений: роль `live_staff` у жителя B (решение владельца) |

После выкладки (≈13:08): `/ready` 200 снаружи, `/version` = `c68c9a9`,
capabilities без изменений (`ai_analysis`, `routes`, `passive_capture` = true,
`test_auth` = false); webhook без секрета 401; `list` — одна подписка, прежний
URL и шесть типов событий (не менялась); `ai-worker` работает без перезапусков
(аренда 80 ≥ 60 + 20 прошла проверку старта).

## P7a checkpoint — 23 сентября 2026: пассивное чтение, Signal Inbox, модель, явный путь

Этот чекпоинт относится к функциям с 20.09 (роутер, явный путь, экраны жителя,
пассивное чтение, Signal Inbox, модель); базовый цикл 19.09 ниже не
переписывается. Время — UTC (кабинет показывает МСК = UTC+3). Участники:
житель A (житель live-стенда с 19.09), житель B (второй аккаунт владельца; по
решению владельца он же сотрудник-оператор тестовой УК через `live_staff`),
сотрудник в кабинете — веб-вход `live-test.operator`. Текст сообщений людей и
их идентификаторы здесь не приводятся; события — хэши квитанций `max:…`.

| Параметр | Значение |
|---|---|
| `BUILD_COMMIT` | `1ebbf23b22cb3fab7bf8469c55ef9aa1bc7a68eb` (ветка `agent/b/p7a-live`, перенос бандлом) |
| Образ `domsignal-backend:local` | `sha256:fe119eb13bdd6fceeb82b70dfe8d28a79f17573ae169f3304f816ec421602520` (api, worker, ai-worker) |
| Откат | образ `domsignal-backend:pre-aba9de7`, прежний SHA `aba9de7` |
| Миграции | `e107a3cff433 → 20260920_0005 → … → 20260923_0009`, ≈06:23 UTC (api запущен 06:23:06); повторный запуск `migrate` при `start ai-worker` в 11:41 — без изменений, exit 0 |
| Резервная копия до миграций | `/var/backups/domsignal/domsignal-20260923T060748959131Z.dump`, 141 087 байт, mode 600, оглавление `pg_restore --list` читается (256 записей) |
| Модель | только `ai-worker`: `openai_compatible`, `openai/gpt-5-mini`, бюджет 300/сутки; `api`/`worker` — `rules`, без ключа |
| Таймаут модели / аренда AI-пула | 25 с / 60 с при выкладке; после шага 2 (попытка 1) — **45 с / 65 с** (`deploy/.env.production`) |
| Пассивное чтение | глобально `true`, тишина окна 30 с; для привязки TEST_MAX включено в 06:30:08 |
| Профиль дома | `RU-TA / kazan / mixed`, квитанция `operator.house_routing_profile`; в кабинете — версия справочника `_federal@1+RU-TA@1+RU-TA/kazan@1` |

После выкладки: `/ready` 200 снаружи, `/version` = `1ebbf23`, capabilities —
`ai_analysis`, `routes`, `passive_capture` = true, `test_auth` = false; webhook
без секрета 401, `max_subscription preflight` — `preflight_ok`; `list` — одна
подписка, прежний URL и шесть типов событий (не менялась).

| Шаг (v3 §9.3) | Статус | Доказательства |
|---|---|---|
| 1. Сообщение о чтении чата | **LIVE VERIFIED** | `passive_capture --enable` 06:30:08 → `reading_notice_queued=true`; доставка `chat_reading_notice` `accepted` 06:30:11.660, попытка 1, id сообщения MAX получен. Владелец видит в TEST_MAX ровно одно сообщение бота с текстом шаблона. Первая живая групповая отправка |
| 1б. Сотрудник с отображением в MAX | **LIVE VERIFIED** | `bot_started` `max:0f2851324c4421a688f5c6290586c132f35a6d5826a250c6ce6cf1444389ae51` (06:42:58.318), проверенный вход B в mini app («нет доступных домов»); владелец подтвердил аккаунт по времени входа; `live_staff grant` → `operator`/`active`; чтение `_staff_recipients` = 1 |
| 2. Ветка и ответ | **LIVE VERIFIED** (попытка 2) | Попытка 1: `max:5fc1e2af…d58b6`, `max:2c43f9b3…dc50a`, `max:65c8ca47…9eade`, `max:08d2695b…c2871` (07:44:11–07:44:31); окно закрыто тишиной 07:45:00; вызов модели `fallback_timeout` на 25 177 мс → правила → **два** слабых сигнала (`elevator.stopped` подъезд 2 с цитатой и лишний `lighting.stairwell`). Диагноз: `GET /models` 200 за 0,19 с — медленная модель; поправка — таймаут 45 с / аренда 65 с, пересоздан только `ai-worker`; оператор закрыл оба сигнала (`dismissed`, `not_a_problem`, 07:53). Попытка 2: `max:bc762e63…c5cd3`, `max:09b78277…c7c9e`, `max:0a3c315c…0bd66`, `max:bc57c72e…723f4` (07:55:33–07:55:46); окно закрыто 07:56:16 (+32 с тишины), `model`/`ok`, **10 793 мс, 0,2345 ₽** (7 812 / 795 токенов); один сигнал `elevator.stopped`, `strong`, 3 реплики · 2 жителя, подъезд 2 с цитатой, `uk_internal`. **Ссылка ответа:** у ответной реплики `reply_to_mid` заполнен и указывает на реплику из буфера — в обеих попытках |
| 3. Из сигнала — в заявку | **LIVE VERIFIED** | «Создать заявку» 08:02:05 → сигнал `converted`, решение `ticket`, report и incident привязаны; заявка **T-4** «Проблема с лифтом», подъезд 2, описание из дословных цитат; «Взять в работу» 08:04:43 → `accepted` (v2). Кнопки «Принять» нет, пока у дома не назначен ответственный. Уведомления жителям нет и быть не может: автор заявки — сотрудник, жители чата к ней не привязаны; доставка `ticket_accepted` → `superseded`/`ACCESS_REVOKED` |
| 4. Газ | **LIVE VERIFIED** | A: `max:9770fae7…ca5dd` 10:18:01.562 → в ту же секунду `preliminary_critical gas`, окно закрыто по опасности, маршрут **`emergency_service/emergency_112` до разбора окна**; `chat_safety_memo` `accepted` 10:18:02 (попытка 1); `signal_alert` `accepted` 10:18:02, получателей 1 (B, личный чат, строка «Сигнал в кабинете: …»); баннер «Критические сигналы: 1» в кабинете; модель 10:18:18 `gas.smell`/`critical`, `reconciled`+`rules_agree`, 16 428 мс, 0,4283 ₽. Повтор B: `max:8587660d…dbaff` 10:22:24.704 → `danger_grouped`, `chat_memo_suppressed`, новых доставок нет, сигнал 2 реплики · 2 жителя; окно — `model`/`ok`, 16 491 мс, 0,4607 ₽ |
| 5. Опасность без ключевых слов | **LIVE VERIFIED** (попытка 2) | Попытка 1: `max:07e26303…f2a77`, `max:30eb4b03…3a12e`, `max:e43710eb…40565` (10:24:40–10:24:48); `model`/`ok`, 28 690 мс, 0,4203 ₽; модель нашла `person_trapped`, но отнесла реплики к **открытому газовому сигналу** (`signal_grouped · open_item`) — вид опасности дописан в него, повторного оповещения нет. Поправка: оператор отметил по газовому сигналу «Внешний маршрут» (11:16, «ДомСигнал никуда ничего не отправлял»). Попытка 2: `max:c0f9154f…169e2`, `max:9855a7f3…4f40d`, `max:8e8af359…ba69` (11:17:18–11:17:26); окно закрыто 11:17:55, `model`/`ok`, **24 437 мс, 0,3769 ₽** (7 831 / 1 396); новый `critical` сигнал, опасность `person_trapped` (источник — разбор переписки), реплики как доказательство; **памятки в чат нет**; `signal_alert` `accepted` 11:18:21 — через 57 с после последней реплики |
| 6. Внешний маршрут, явный путь | **LIVE VERIFIED** | `/report` `max:72a939d9…3c3478` 11:23:04.234 → `ai.report.analyze` (модель) 11:23:20, сторож `report.fallback` 11:23:35 без изменений; `street_lighting.failure` / `municipal_territory` → `municipality` / `pos_gosuslugi`; `route_action_card` `accepted` 11:23:21; «Открыть карточку» открывает mini app на карточке; черновик v1 (`ai_assisted`) 11:23:57; «Скопировать текст» → «Текст скопирован.»; «Я отправил(а) обращение» → отметка 11:24:45 с подписью «ДомСигнал не подтверждает регистрацию во внешней системе»; «Открыть официальный сервис» выключен с подсказкой входа. `/report` в буфер пассивного чтения не попал |
| 7. Форма и осознанный join | **LIVE VERIFIED** (житель A — решение владельца) | «Сообщить» → «Похоже, об этом уже сообщали» → «Это та же проблема» → `POST …/join` 200; у T-4 2 сообщения от 2 авторов, «участников: 2»; заявок по-прежнему 4 |
| 8. Мобильный клиент | **LIVE VERIFIED** (по словам владельца) | Шаги 6–7 выполнены в MAX на телефоне; `navigator.clipboard` сработал («Текст скопирован.»), запасной путь не понадобился. Серверного признака устройства нет — доказательство только подтверждение владельца |
| 9. Отказоустойчивость | **LIVE VERIFIED** | `ai-worker` остановлен 11:34:45; `max:7480c978…5852b`, `max:c8a0341d…dc9ae`, `max:4a18d1fe…f2ec7` (11:35:56–11:36:03); окно закрыто 11:36:32; `ai.window.analyze` ждёт; сторож `chat.window.fallback` 11:38:03 (+91 с) → `analyzed_by = fallback`, правила, модель не вызывалась; два слабых сигнала (`intercom.broken` подъезд 1, `entrance_door.broken`); `ai-worker` запущен 11:41:08, отложенная задача выполнена 11:41:09 без перезаписи окна |

**Модель за срез:** 7 вызовов (6 окон + 1 `/report`). Известная стоимость —
1,9207 ₽ за 5 успешных окон; у оборванного по таймауту вызова и у `/report`
(внешний маршрут) стоимость в БД не сохраняется. Задержка успешных окон —
10,8–28,7 с (медиана ≈ 16,5 с).

**Находки** (подробно — `docs/status/dev-b.md`, P7a): задержка модели выше
профиля — 25 с мало; без модели правила дробят ветку («не горит» → освещение);
модель склеивает новую опасность с открытым сигналом другого вида, и продукт
не оповещает повторно о новом виде опасности; подъезд «третьем» вместо «3»;
в оповещении оператора цитата — первая реплика окна, время в UTC; у заявки из
сигнала нет пути уведомления жителей (`ACCESS_REVOKED`); источники фактов ПОС —
«скриншоты», владелец считает это недопустимым основанием; у явного пути с
внешним маршрутом не сохраняются задержка и стоимость модели.

**NOT LIVE VERIFIED:** второй житель с членством в доме (стенд одиночный —
форму и join выполнил житель A); настоящий сотрудник УК с MAX, не совпадающий
с жителем чата; оповещение жителей о заявке, созданной из сигнала; повторная
памятка после 30 минут; выключение чтения (чат оставлен демо-чатом для жюри,
чтение включено).

## Current product checkpoint — 19 September 2026, 18:16 UTC

This checkpoint supersedes historical pending labels in the chronological notes
below. **LIVE VERIFIED:** Mini App binding, validated real identity, resident
membership/board/reload, group capability/admin rights, correlated A-07 activation,
real group Report → Incident → Ticket, operator WorkAttempt and personal MAX API
delivery, notification open_app/start_param, real resolved callback, closure,
Mini App correction/reopening of the same Ticket and message reconciliation.
No mandatory client or organizer blocker remains for this MAX Web smoke.
Native mobile, callback replay/stale-attempt scenarios, multi-resident disputes,
restart/retry/rate-limit and historical-message edge cases are not LIVE VERIFIED.

The first group command lacked its description; a second attempt arrived in the
personal dialog. Neither created domain records. The complete command in TEST_MAX
produced genuine message_created receipt
`max:621ed77b6942695346a34491dbabc77fe7985fca704dbd1c1e472b837f8e1046`,
accepted at 18:05:33.404949 UTC (provider event time 18:05:32.067 UTC).
The authenticated webhook and max.group.report worker job succeeded once, using
the active binding/version and real MAX actor recorded below.

| Domain object | Persisted ID |
|---|---|
| Report, author is the real resident, source=max_group | `8fb88a64-4736-45c7-9b01-89e87ad1b017` |
| Incident | `e7d812f0-d7d6-4905-9577-44be43325c0e` |
| Ticket T-1 | `95f526e0-3604-434e-8e21-e71c9e2ccf9a` |
| WorkAttempt 1 | `cf9bdcb0-8be2-480b-94c2-333711cb4872` |
| Work verification delivery | `29c32185-d951-4ad9-a059-86f9bf0093f4` |

Exactly one Report, Incident and Ticket exist, all in the isolated house/management.
The category `other` initially routed T-1 to needs_clarification. At 18:06:53 UTC,
the audited scoped CLI operator used existing TicketService commands with expected
versions and fixed idempotency keys: resume (test-company responsibility explicitly
confirmed), accept, start, work-attempts. Versions advanced 1 → 5, ending in
verification_pending. The work report explicitly describes a product-cycle test;
it does not claim a real repair. The real resident received no employee privilege.

The production worker sent one work_verification message, accepted at
18:06:54.724729 UTC with real provider ID
`mid.00000000066d71cf01a0bad98cf55266`, desired/applied version 5, attempt_count=1,
retry_count=0 and no error. The earlier ticket_accepted intent was superseded before
sending (STALE_INTENT); do not claim a second accepted notification.
Read-only official [GET message](https://dev.max.ru/docs-api/methods/GET/messages/-messageId-)
returned 200 for that exact ID: sender bot 402577719, personal chat 107835855,
recipient 294889720. Actual keyboard contains open_app for t480_hakaton_max_bot
and resolved/unresolved callbacks; all payloads match the stored opaque launch ref.
No raw token, initData, session bearer or launch ref is recorded here.

The normal launch service resolves that recipient/ref to the exact Incident,
House and WorkAttempt above, stale=false. This operator read is not a real client
open_app claim. The user supplied screenshots of the one-problem house board and
T-1/attempt 1 with verification buttons; matching incident/work-status API reads
returned 200. No notification-launch request or ResultObservation was present at
that checkpoint, so a precise click on the notification's open_app button was
requested. API acceptance alone is not push/read confirmation.

The original editable message in this loop is the bot's personal notification.
The source group message belongs to the resident; no edit of that human message
is implemented or claimed. Cross-tenant negatives remain deterministic evidence:
this fresh production database contains no foreign tenant to test against live.

### Notification launch and callback — LIVE VERIFIED

The user clicked the actual notification button and confirmed immediate opening
of the problem/solution card. Fresh auth/max 200 at 18:11:42.952517883 UTC,
notification-launch 200 at 18:11:43.167446239 UTC, followed by exact Incident and
work-status GET 200. Thus genuine initData start_param and the authenticated launch
resolver exercised the correct Incident/House/WorkAttempt in MAX Web.

User then pressed the notification callback «Исправлено». Genuine message_callback
receipt `max:1ce7ccb3a017d83bbae9dc100ca03034e5a0b91e88143d5bbef905a705428768`
was accepted at 18:13:12.880378 UTC. Callback job and answer job both succeeded
once, no errors; the provider answer adapter requires success=true.
ResultObservation `2dd81f56-fb3a-4388-a70a-8fa4773fffd8` at 18:13:13.263118 UTC
has real resident actor, attempt 1, resolved, revision 1. Event
`ab0f1781-5287-4c0c-a8c3-b55ae4bccc20` advanced the same T-1 from
verification_pending v5 to closed v6. No new Ticket/attempt was created.

Delivery desired/applied versions advanced to 6, preserving the original provider
message ID. Exact provider GET 200 confirms the closed-result text and only one
open_app button («Открыть проблему»); verification callbacks were removed.
attempt_count=2 counts send plus edit, not two sends; retry_count remains zero.
Requested a real Mini App unresolved correction to exercise reopening next.

### Mini App correction and same-ticket reopening — LIVE VERIFIED

The user saw T-1 «Завершено», then explicitly pressed «Проблема осталась» in
Mini App and confirmed the action. Fresh validated MAX auth and launch resolver
both returned 200 at 18:15:22 UTC. Actual POST
`/api/v1/work-attempts/cf9bdcb0-8be2-480b-94c2-333711cb4872/observations`
returned 200 at 18:15:25.847033713 UTC, followed by work-status GET 200.

Observation `50f555d8-d831-4db1-abac-104d65fca9c1` at 18:15:25.815783 UTC is
unresolved revision 2, by the same real resident, correcting revision 1's exact ID.
Event `9c744146-ebba-459d-9fae-8669820dc842` changed the same T-1 from closed v6
to in_progress v7; attempt 1 is retained and requires rework. Both observations
remain in history. No new Report/Incident/Ticket/WorkAttempt was created.

Reconciliation advanced delivery desired/applied to 7, with the same original
provider message ID, attempt_count=3 (one send plus two edits), retry_count=0.
Provider GET 200 confirms «Ваш ответ учтён. Проблема возвращена в работу.» and
only the open_app button. This verifies Mini App mutation → outbox → real MAX
edit without another POST/send; it does not claim editing the resident's group post.

Final human client confirmation: the user read the personal notification and
reported «Другая проблема дома. Ваш ответ учтён. Проблема возвращена в работу.»
This confirms the reconciled text is visible in MAX Web, in addition to the
provider GET evidence. It is user confirmation, not an API read receipt or a
claim about operating-system push delivery.

Final access read: canonical MAX user 294889720 still has exactly one active
ResidentMembership, zero organization memberships, no platform role; all sessions
have source=max. A read-only production resolver check using the existing distinct
CLI operator identity rejects the resident's launch ref with ResourceNotFound.
No fabricated MAX identity or extra session was used for the negative check.

Code remains the tested/deployed `6ac08e0`; this continuation only updates evidence
documentation. Scope stays active for review, with the audited revoke path available.
delete-empty correctly cannot erase this fixture now that domain history exists.

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

### Live group continuation — 19 September, after resident verification

**LIVE VERIFIED:** operator added the bot to `TEST_MAX` and assigned admin rights.
Webhook auth succeeded, HTTP 200 at `2026-09-19T17:51:14.626494760Z`.
Real bot_added receipt:
`max:675e080a2bdf65fd4177973c06d13f2394878c1c1ca303f41fbf094dc7470248`,
accepted at `17:51:14.611488+00:00`, actual lifecycle time `17:51:12.762+00:00`.
MAXChat persists group `-79142681723640`, type=chat, bot_present=true.

Real per-chat API reads confirm bot `402577719` is_admin=true and permission
read_all_messages (also write/pin_message and other operator-assigned rights).
Connector `294889720` is the current admin and owner. Group capability is enabled;
no organizer action needed. This confirms group installation/rights, not binding.

There were zero ConnectionRequests and zero ChatBindings. A-07 requires a request
and correlated bot_started before bot_added; the capability smoke addition correctly
did not bind a house. Added operator CLI prepare/approve using the existing A-07
services, pinned to the audited test scope and observed group. Scoped CLI principal
has no MAX identity/session/platform role; resident grants do not change.
See [operator path](../deploy/README.md#8-live-a-07-operator-connection).
No request timestamps or events are backdated, no candidate/binding state forced.
Real correlated installation, binding and product report remain pending.

Operator CLI code `6ac08e09d22a11836fc18a45cb65b594f67bbad4` was pushed and
deployed via verified Git bundle. Runtime image
`sha256:c20f7b3c0d5564e1b2ff842edce78b7afd00e7007cdf0979188e5742c276fb7a`;
API/DB healthy, worker running; BUILD_COMMIT updated, environment mode remains 600.
At 17:59:00 UTC, the CLI created request
`f650a92a-daf8-4a0e-a83a-dc1c64d25d83`, expiring at 18:14:00 UTC,
for the exact test management and pinned chat above. It remains `created` pending
a real token-bearing bot_started; no candidate or binding was assigned.

Scoped CLI User `763c4458-e474-4398-9bc8-16ef79077463` has no MAX identity,
platform role or session. Its company-admin scope contains only the test house.
The real user's me still contains one resident house, with three genuine MAX
sessions from opening/reload and no staff elevation. Operator audit contains no
raw correlation token. One-time connection link was shown only to the operator
in the task; it is intentionally absent from docs and stored receipts.

Checks: 41 targeted PG tests PASS, 100 unit/contract PASS, ruff/mypy 79 source
files PASS, OpenAPI/TS drift PASS, local+VPS production Docker builds PASS,
Gitleaks staged scan PASS and git diff --check PASS. User action requested:
open the one-time link in MAX; afterward a fresh bot addition is needed for the
existing A-07 time ordering. Group/report/notification product effects still pending.

The operator pressed Start. Genuine token-bearing bot_started
`max:eb521bc4d118e3f09faced86718f9a9e4add7c0a9cfcf435daf23978e471c2fb`
was accepted at 17:59:48.816127 UTC. Request transitioned to connector_claimed,
MAX connector `294889720`, claimed_at 17:59:48.007 UTC. This is real correlation,
not a replay or manually assigned identity.

To perform the required subsequent addition, the operator used documented
DELETE `/chats/-79142681723640/members/me`: HTTP 200 and success=true.
Guarded preflight required that exact pinned request/connector, unexpired request,
zero bindings for that chat, and no previous leave attempt. Audit
`operator:live-smoke-readd:v1` records the operation as accepted. It removed only
the bot from the test group, not the chat or participants. No bot_removed webhook
was present at the immediate follow-up check; do not claim one. Requested user
re-add/admin assignment in the same group; binding remains pending.

**LIVE VERIFIED — correlated installation and ACTIVE ChatBinding:** second real
bot_added `max:f59a4c28318a7dcdd273d38b104bc3c72023de5fb935430aef20f3a49edd9c3d`
arrived at 18:01:49.785292 UTC and selected the claimed request. Initial worker
verification ran before the user finished assigning admin rights, correctly leaving
chat_detected/bot_permission_missing. After the user's confirmation, fresh provider
reads and the existing approve service verified admin/read_all_messages/connector
owner plus test-company authority. Request completed; binding
`7786a1b3-b224-48ff-8938-800d79566f6b`, ACTIVE version 1, activated at
18:02:51.407852 UTC. CLI audit records explicit approval and binding audit is saved.

Verified mapping: chat `-79142681723640` → this binding → management
`3119b924-0a47-49a6-975d-2c0c5546894d` → house
`6edbf50b-4bb4-4a74-a6fd-40351010802e` / tenant
`9f0306fa-9660-40ab-8527-f1e361d48d61`. OperationContext resolves real resident,
source=max_group, binding ID/version and these exact IDs with resident permissions.
No title inference, timestamp manipulation or direct binding writes. Requested
one actual `/report other Тестовая проблема live MAX` in TEST_MAX next.

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

## Ticket → MAX → Mini App — historical preflight checklist

Delivery code is now IMPLEMENTED IN BRANCH (A-05/B-03/personal B-06/B-07/B-08).
Deterministic HTTP+PG+worker/browser evidence is in [DEV-B](status/dev-b.md).
This is the preflight checklist recorded before the live run. The current dated
product checkpoint at the top supplies actual evidence and supersedes these
historical pending labels; unchecked additional edge cases remain unverified.

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
