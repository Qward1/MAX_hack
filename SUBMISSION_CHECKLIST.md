# Комплект сдачи — проверка по пунктам

Сверено по требованиям онлайн-этапа трека «Умный город» (задание, стр. 7–13; Q&A
17.09.2026). Каждый пункт проверен, рядом — чем. Итог проверок — в
[`FINAL_JURY_READINESS_REPORT.md`](FINAL_JURY_READINESS_REPORT.md).

**Финальная версия:** тег `online-submission-final` · commit — `git rev-parse online-submission-final^{commit}` =
`/version` production (строка «commit» на служебном слайде) · проверено 28.09.2026.
`/version` возвращает этот же коммит; короткий вид — первые 7 символов.

## Обязательно для всех решений

- [x] **Рабочее решение в MAX** — бот <https://max.ru/t480_hakaton_max_bot>, мини-приложение из
  бота, демо-чат «Дом · Казань, Пилотная, 7»; production `/ready` → ready; путь «заявка из чата →
  «Исправлено»» проверен людьми в MAX 19.09 и 24.09, автоматически — эмулятором MAX
  (`tests/acceptance/test_jury_path.py`).
- [x] **Финальный исходный код зафиксирован** — публичный <https://github.com/Qward1/MAX_hack>, тег
  `online-submission-final`, commit = `/version`.
- [x] **Финальный commit определён** — в строке выше и на служебном слайде закрытой версии PDF.
- [x] **ML-часть в сдаваемом репозитории** — [`ml/`](ml/README.md), merge-коммит ветки DEV-A с историей.
- [x] **ML-часть документирована** — `ml/README.md` («Коротко для проверяющих», запуск без закрытых
  данных), `ml/docs/`, отчёты `ml/experiments/`.
- [x] **README.md актуален** — 16 обязательных разделов, API, ML, структура репозитория.
- [x] **Файлы зависимостей** — `pyproject.toml` + `uv.lock`; `miniapp/package.json` +
  `package-lock.json`; `ml/requirements*.txt`.
- [x] **Docker-конфигурация** — `Dockerfile`, `compose.yaml`, `compose.prod.yaml`, `.dockerignore`,
  `.env.example`.
- [x] **Docker-запуск проверен** — чистый клон → `docker compose build --no-cache` 34 с (лимит 5 мин) →
  `up` → `/ready` за 20 с; перезапуски сервисов и стека без потери данных.
- [x] **PDF-презентация** — публичная [`docs/presentation/DomSignal_presentation.pdf`](docs/presentation/DomSignal_presentation.pdf);
  закрытая (с учётками) — в кабинет сдачи.
- [x] **Первый слайд — техническая информация** — бот, мини-приложение, web, API, OpenAPI,
  репозиторий и commit, учётные записи, порядок проверки, QR на бота и гид.

## Собственный API (заявлен)

- [x] **Публичный API доступен** — `https://domsignal.176-108-244-168.sslip.io/api/v1`, TLS Let's Encrypt до 17.12.2026.
- [x] **OpenAPI 3.1** — `/openapi.json` и [`docs/openapi.json`](docs/openapi.json).
- [x] **OpenAPI соответствует backend** — `scripts/export_openapi.py --check` (в `check.py` и CI).
- [x] **Тестовые учётные записи работают** — `jury.operator`, `jury.admin`, `jury.platform`: вход
  пароль + TOTP на production, проверки ролей в `DATA-API.yaml` прошли.
- [x] **Тестовые данные** — демо-УК «Пилотная, 7» и дом на production; [`docs/api/test_data.json`](docs/api/test_data.json).
- [x] **DATA-API.yaml существует** — [`DATA-API.yaml`](DATA-API.yaml), девять элементов задания.
- [x] **DATA-API.yaml валиден** — YAML разбирается; `scripts/data_api_check.py` на production —
  24 из 24 на финальном коммите: «без входа: 12 из 12», «с входом по TOTP: 12 из 12», 28.09.2026.
- [x] **Проверки с TOTP помечены** — 12 из 24 проверок `requires_totp: true` (`required: true` сохранён);
  в начале `DATA-API.yaml` — `automation_notes`: если платформа оценки не поддерживает TOTP, они будут
  показаны непройденными; запасные пути — раннер с `--accounts` (шаблон
  [`docs/api/accounts.example.json`](docs/api/accounts.example.json)) и ручная проверка по `JURY_GUIDE.md`.

## Дополнительно

- [x] **JURY_GUIDE.md** — [`JURY_GUIDE.md`](JURY_GUIDE.md): быстрый старт за минуту, входы и учётки, 11 сценариев с дословными
  названиями кнопок, «Подключить свою группу MAX за 5 минут», таблица «Если что-то пошло не так».
- [x] **ARCHITECTURE.md** — [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md), обзор финальной версии.
- [x] **SCENARIOS.md** — [`docs/SCENARIOS.md`](docs/SCENARIOS.md), нестандартные ситуации с доказательствами.
- [x] **DEPLOYMENT.md** — [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md), команды проверены 28.09.
- [x] **TESTING.md** — [`docs/TESTING.md`](docs/TESTING.md), результаты прогонов 28.09.
- [x] **Все ссылки проверены** — адреса production, бот, репозиторий, файлы в README и гидах.
- [x] **Credentials для жюри проверены** — вход всех трёх ролей на production 28.09 (браузер и API).
- [x] **Нет секретов в git** — gitleaks: история с прошлого выпуска — 0 находок; рабочее дерево — только
  шаблоны `replace_with_…` и хэши разметки (исключение в `.gitleaks.toml`).
- [x] **Нет критических TODO/FIXME** — в `src/`, `miniapp/src/`, `scripts/` нет.
- [x] **Финальный regression пройден** — [`docs/TESTING.md`](docs/TESTING.md).

## Матрица критериев оценки

| Критерий (вес) | Чем закрыт | Где в продукте | Как проверить | Доказательство |
|---|---|---|---|---|
| Работоспособность (18 %) | путь «сообщение → заявка → работа → «Исправлено»» | бот, мини-приложение, кабинет | `JURY_GUIDE.md` сценарий 1 | `test_jury_path.py`, TC-035/057, живой MAX 19.09 и 24.09 |
| Масштабирование (14 %) | регион — пакет данных; УК подключается сама; процессы растут копиями | `regions/`, `/company/apply`, `compose` | `docs/SCALING.md`; сценарий 5 | прогоны А–Д: 1 000 чатов на железе production, 5 000 — расчёт |
| Интеграции (12 %) | вебхук MAX, посты с правкой, личные уведомления, проверка прав бота; модель с откатом на правила | `bot/`, `ai/` | сценарии 1–3, 6 | TC-057/062/068; `evaluation/reports/2026-09-29-llm-probes.md` |
| Архитектура (12 %) | модульный монолит, PostgreSQL как очередь, пулы изолированы | `docs/ARCHITECTURE.md` | схема и таблица компонентов | `test_worker_pools.py`, прогон перезапусков 28.09 |
| Пользовательская ценность (10 %) | житель пишет как привык; видит статус; закрывает сам | мини-приложение, личка | сценарии 1–4 | 2 реальных чата: 12,5 % окон — проблемы; `evaluation/reports/2026-09-27-d1-realdata.md` |
| UX/UI (8 %) | единый язык, подтверждения, понятные ошибки, мобильная ширина | все экраны | 390 и 1280 px | `ui-lint` (39 экранов × 5 ширин × 2 темы), браузерные сценарии |
| Обоснованность (6 %) | ИИ понимает, справочник решает, житель подтверждает | `docs/decisions.md` | слайды 5–8 | решения с датами |
| Стабильность (6 %) | повторы и двойные клики без дублей; отказ модели — правила; перезапуск без потерь | `Idempotency-Key`, `expected_version`, outbox | `docs/SCENARIOS.md` «Нестандартные ситуации» | прогон 28.09: повтор → тот же инцидент, другое тело → 409; рестарты 0–4 с |
| Безопасность (6 %) | TOTP, изоляция УК, витрина защищена, маскирование перед моделью, секреты вне git | `core/access.py`, `services/showcase.py` | `DATA-API.yaml` роли и 404 | gitleaks, `test_tenant_access.py`, `test_f1_showcase_guard.py` |
| Документация (6 %) | README 16 разделов, гид, API, сценарии, развёртывание, тестирование | корень и `docs/` | чистый клон по README | этот файл, `docs/TESTING.md` |
| Презентация (2 %) | PDF, первый слайд служебный | `docs/presentation/` | открыть PDF | 25 слайдов (закрытая версия — 26), статус «работает / фундамент / план» разделён |
| Бонус MAX (+0,15) | пост заявки ↔ мини-приложение ↔ личное уведомление ↔ правка того же поста | бот и мини-приложение | сценарий 1 | TC-061, живой MAX D1–D3 |
