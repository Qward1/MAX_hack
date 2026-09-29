# Фронтенд ДомСигнала (`miniapp`)

Один проект Vite собирает все веб-поверхности продукта; FastAPI отдаёт сборку
`miniapp/dist`. Интерфейс всегда работает с настоящим API; тестовые данные —
только в `src/test` и `tests/`, вне точек входа.

| Точка входа | Адрес | Что это |
|---|---|---|
| `index.html` | `/` | мини-приложение жителя в MAX |
| `admin/index.html` | `/admin/`, `/join/<код>` | кабинет УК |
| `platform-admin/index.html` | `/platform-admin/` | кабинет платформы |
| `login/index.html` | `/login` | вход сотрудника УК и администратора платформы |
| `company/index.html` | `/company/apply` | заявка на подключение УК и её статус |
| `site/index.html` | `/site` | сайт продукта (в обычном браузере его открывает и корень) |

Стек: React 19.2, MAX UI (`@maxhub/max-ui`) 0.5.0, Vite 8, TypeScript 5.9,
Vitest 5, Playwright 1.63; Node.js 24 (`engines` в `package.json`).

- `src/app` — мини-приложение жителя, `src/admin` — кабинеты и вход,
  `src/site` — сайт, `src/features` — разделы по предметной области,
  `src/shared` — клиент API, общие компоненты, стили, тема, MAX Bridge.
- Типы API генерируются из `docs/openapi.json`: `npm run api:generate` →
  `src/shared/api/schema.ts`; `scripts/check.py --scope contracts` сверяет их с
  закоммиченными.
- Единственный доступ к `window.WebApp` (MAX Bridge) —
  `src/shared/max/bridge.ts`.
- Тема: светлая и тёмная. Без выбора тема следует за MAX и системой
  (`prefers-color-scheme`); переключатель темы (`src/shared/ui/ThemeToggle.tsx`)
  запоминает выбор на устройстве (`src/shared/theme.ts`, до первой отрисовки —
  `public/theme-init.js`).

## Команды

Из каталога `miniapp` (из корня — `npm --prefix=miniapp …`):

```sh
npm ci                 # зависимости из package-lock.json
npm run typecheck      # tsc
npm test -- --run      # Vitest (jsdom)
npm run build          # tsc + vite build → dist/
npm run dev            # Vite на :5173, /api и /max проксируются на :8000
npm run test:browser   # Playwright — нужен стенд, см. ниже
```

Playwright по умолчанию идёт на `http://127.0.0.1:8017`; другой адрес —
`PLAYWRIGHT_BASE_URL`, установленный Chrome вместо скачанного Chromium —
`PLAYWRIGHT_CHANNEL=chrome` (иначе `npx playwright install chromium`). Сценарии
блокируют CDN MAX: внешние сервисы не нужны. Артефакты — `test-results/`
(Playwright очищает каталог при каждом запуске). Проектов два: `ui-lint`
(`tests/ui-lint.spec.ts`) и `browser` (`tests/browser/**`).

## Браузерный стенд

Стенд — отдельная PostgreSQL DB (не та, что у `pytest`-интеграции: она свою
очищает) и один процесс API **без воркеров**: фикстуры в `tests/browser/*.py`
сами прогоняют задачи, и фоновые пулы им только мешают. Фикстуры — CLI только
для тестовой БД, не эндпоинты приложения: вне `APP_ENV=test` и без своего флага
они отказываются работать.

| Переменная | Значение | Зачем |
|---|---|---|
| `APP_ENV` | `test` | тестовая сессия и фикстуры |
| `B14_BROWSER_FIXTURES` | `1` | фикстуры заявок, сигналов и доступа (`ticket_fixture.py`, `signal_fixture.py`, `d1_fixture.py`); без флага `access.spec.ts` пропускается, остальные их сценарии падают |
| `D2_BROWSER_FIXTURES` | `1` | фикстура подключения УК и входа сотрудников (`d2_fixture.py`); без флага пропускаются `d2.spec.ts`, `f1.spec.ts`, `ux-d3.spec.ts`, `ux-quality.spec.ts` и `ui-lint` |
| `D3_BROWSER_FIXTURES` | `1` | фикстура домового чата и рассылок (`d3_fixture.py`); без флага пропускаются `d3.spec.ts` и те же сценарии, что без `D2_BROWSER_FIXTURES` |
| `DATABASE_URL` | своя БД стенда | та же у API и у фикстур |
| `PUBLIC_BASE_URL` | ровно `PLAYWRIGHT_BASE_URL` (`http://127.0.0.1:8031`) | CSRF сверяет `Origin` кабинета именно с ним; иначе каждый POST — 403 |
| `AUTH_MFA_ENCRYPTION_KEY` | валидный ключ Fernet, общий у API и фикстур | иначе привязка второго фактора в `employee-auth.spec.ts` падает на шаге QR |
| `PASSIVE_CAPTURE_ENABLED` | `true` | переключатель чтения чата в кабинете (`signal_fixture.py` включает приём у себя сам) |
| `MAX_TRANSPORT` | `off` | никаких сетевых вызовов MAX |
| `MAX_BOT_USERNAME` | допустимое имя бота, например `t480_hakaton_max_bot` | ссылка «Открыть бота в MAX» на странице статуса заявки УК (`d2.spec.ts`) |
| `PYTHONPATH` | корень репозитория | `administration_fixture.py` импортирует `tests.fakes` |
| `PLAYWRIGHT_BASE_URL` | `http://127.0.0.1:8031` | адрес стенда для Playwright |
| `PLAYWRIGHT_CHANNEL` | `chrome` | по желанию: установленный Chrome вместо скачивания Chromium |

Запуск из корня репозитория (Node 24, Python 3.12, `uv`):

```sh
export DATABASE_URL=postgresql+asyncpg://…/domsignal_browser   # своя БД стенда
export APP_ENV=test MAX_TRANSPORT=off PASSIVE_CAPTURE_ENABLED=true
export B14_BROWSER_FIXTURES=1 D2_BROWSER_FIXTURES=1 D3_BROWSER_FIXTURES=1
export PUBLIC_BASE_URL=http://127.0.0.1:8031 PLAYWRIGHT_BASE_URL=http://127.0.0.1:8031
export AUTH_MFA_ENCRYPTION_KEY="$(uv run python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
export MAX_BOT_USERNAME=t480_hakaton_max_bot PYTHONPATH="$PWD"

uv run alembic upgrade head
uv run python -m domsignal.tools.seed_demo
uv run python -m domsignal.tools.seed_tickets
npm --prefix=miniapp run build
uv run uvicorn domsignal.main:create_app --factory --host 127.0.0.1 --port 8031
# во втором терминале, с теми же переменными:
npm --prefix=miniapp run test:browser
```

PowerShell: `$env:APP_ENV='test'` и так же для остальных переменных.

Перед каждым полным прогоном очистите **свой** `auth_rate_limits`
(`DELETE FROM auth_rate_limits`): все входы идут с `127.0.0.1`, и повторные
прогоны подряд упираются в ограничитель попыток (10 на идентификатор, 50 на IP
за 300 с).

Отдельные наборы:

- `tests/ui-lint.spec.ts` — вёрстка всех экранов на ширинах 320, 390, 768, 1280,
  1440 в светлой и тёмной теме (правила — [`docs/UX.md`](../docs/UX.md),
  «Проверка вёрстки»); полный проход — около 20 минут. Сузить:
  `UI_LINT_ONLY="^(site-|platform-)"`, `UI_LINT_WIDTHS=390,1280`,
  `UI_LINT_THEMES=light`.
- `signals.spec.ts` засевает сигналы через `tests/browser/signal_fixture.py` тем
  же путём, что и вебхук MAX: событие → окно → разбор правилами, без прямой записи
  в таблицу `signals`. Фикстура создаёт свои синтетические дом, оператора и чат и
  поднимает лимит слабых сигналов на дом в сутки: иначе после нескольких прогонов
  за день новые слабые сигналы уходят в Audit Pool.
- `ux-snapshots.spec.ts` — только снимки экранов, без проверок; запускается с
  `UX_SNAPSHOTS=1`, каталог снимков — `UX_SHOTS` (по умолчанию
  `test-results/ux/after`). Запускайте его последним или со своим `--output`:
  следующий прогон очистит `test-results/`.
- По умолчанию пропускаются `notifications.spec.ts` (нужны `ND_FIXTURES=1` и
  рантайм доставки) и `administration.spec.ts` (нужен `B09_BROWSER_FIXTURES=1`).
  `administration.spec.ts` на HTTP-стенде без MAX проходит разделы кабинета, но на
  шаге «Подтвердить подключение» API заново проверяет чат настоящим провайдером
  MAX, которого на таком стенде нет.
