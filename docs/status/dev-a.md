# DEV-A — current handoff
Updated: 2026-09-20T18:00:00+03:00
Branch: `agent/a/a03-ai-core` (worktree, слит `dev/b-experience` через `--ff-only`)
Current task: A-08 / A-17/AI — провайдер polza.ai за готовым `AnalysisProvider` (P2)
State: IMPLEMENTED IN BRANCH / NOT MERGED

## Active/recent tasks

| ID | State | Result / blocker | PR or tested reference |
|---|---|---|---|
| BOOT-01 | BASELINE | Repository workflow was present on main before this task | `a70df01` |
| FND-01 | READY_FOR_REVIEW | C0 UI→API→PostgreSQL slice, auth boundary, jobs, generated contracts, Compose/Caddy and real checks implemented; live MAX remains not verified | local `dev/a-core`; PR pending owner action |
| A-03/AI + A-17/AI (P1) | MERGED в `dev/b-experience` | Детерминированное ядро разбора окна: таксономия v2, правила, fallback, fusion, сила сигнала, guard, интерфейс провайдера, датасеты и оценка | `31df491` |
| A-08 / P2 | IMPLEMENTED IN BRANCH | Адаптер `openai_compatible` для polza.ai, промпт окна v1, режимы схемы, устойчивость (breaker/семафор/бюджет), учёт токенов и стоимости, отбор моделей на синтетике, набор `single_messages.v2` | `agent/a/a03-ai-core`; `scripts/check.py --scope backend` PASS |
| P3b / P4 | NEXT (DEV-B) | Проводка провайдера: bootstrap, пулы воркеров, счётчик бюджета в PostgreSQL | см. раздел «For teammate» |

## Result

Реальная модель подключена **за уже существующим интерфейсом**: продукт
по-прежнему видит только `WindowAnalyzer.analyze(window) -> WindowAnalysis`.
Смена провайдера или модели — изменение конфигурации, а не кода.

- `ai/providers/openai_compatible.py` — адаптер OpenAI-совместимого
  `/chat/completions` (polza.ai): один вызов на окно, `temperature: 0`,
  ограниченный `max_tokens`, **никаких повторов**. Плагины агрегатора
  (`web`, `response-healing`, `file-parser`) не используются. Модуль не
  импортирует `domsignal.settings`: все параметры приходят в конструктор.
- `ai/prompts.py` + `ai/resources/prompts/window.v1.md` и
  `window.v1.examples.jsonl` — промпт окна v1: роль, таксономия из живого
  контракта, правило дословных цитат, опасность из нескольких реплик,
  опровержения, запреты и 6 синтетических few-shot примеров. Рендер
  детерминирован и провайдер-независим; расхождение промпта с контрактом
  ролей, территорий, видов опасности и причин опровержения делает импорт
  модуля невозможным.
- `ai/schema_modes.py` — одна схема в трёх формах: `json_schema_strict`
  (все свойства обязательны, необязательные — nullable, неподдерживаемые
  ключевые слова убраны), `json_schema` и `json_object` со схемой в тексте
  промпта. **Источник истины — наш валидатор**, а не гарантия провайдера.
- `ai/resilience.py` — `ResilientProvider` с предохранителем (3 отказа подряд
  → 60 с паузы → одна пробная попытка), семафором с ожиданием ≤ 1,5 с и
  протоколом `BudgetGuard` (дневной лимит вызовов + доля на чат) с
  реализацией в памяти.
- `ai/models.py` + `ai/resources/models.v1.yaml` — профиль выбранной модели и
  резервов: режим схемы, лимиты, параметры семейства и основание политики
  обработки данных с датой проверки.
- `ExecutionInfo` += `provider_model`, `tokens_in`, `tokens_out`, `cost_rub`;
  `Versions.prompt`/`model` заполняются, только когда модель действительно
  ответила. Новые состояния `fallback_budget`, `fallback_circuit_open`,
  `fallback_overloaded` уже были в контракте P1 и теперь используются.
- `evaluation/guard.py` — сторож данных: отказ на любом пути в `data/` и на
  первой строке без `synthetic: true` либо без проверенной человеком пометки
  `origin: real_derived_anonymized`. Через него читают наборы оба скрипта.
- `evaluation/select_models.py` + `candidates.v1.yaml` — отбор моделей на
  синтетических окнах с жёстким лимитом прогона (300 вызовов, 500 ₽).
- `datasets/synthetic/single_messages.v2.jsonl` — копия v1 с разметкой
  внешнего маршрута для `o03`; v1 не менялся. `run_eval.py` считает обе
  версии, полы v2 равны текущему результату правил.

## Что сверено в документации polza.ai (20.09.2026)

Открыты и прочитаны: `/docs/api-reference/chat/completions`,
`/docs/osobennosti/usage`, `/docs/gaidy/structured-output`,
`/docs/gaidy/models`, `/docs/osobennosti/privacy`, плюс живой каталог
`GET https://polza.ai/api/v1/models?type=chat` (317 chat-моделей).

| Что | Как в документации |
|---|---|
| Базовый адрес | `https://polza.ai/api/v1`, эндпойнт `POST /chat/completions` |
| Авторизация | заголовок `Authorization: Bearer <ключ>` |
| Формат запроса | стандарт OpenAI Chat Completion: `model`, `messages`, `temperature`, `max_tokens`, `response_format`, `reasoning`, `provider`, `plugins` |
| Структурированный вывод | `response_format` в формах `text`, `json_object`, `json_schema` (с `name`, `strict`, `schema`) и `grammar`; поддержка зависит от модели — в каталоге это поле `top_provider.supported_parameters` |
| Стоимость | `usage.prompt_tokens`, `usage.completion_tokens`, `usage.total_tokens`, `usage.cost_rub` (и дубль `usage.cost`) — **рубли, фактически списанная сумма** |
| Цены каталога | `top_provider.pricing.prompt_per_million` и `completion_per_million`, `currency: "RUB"` |
| Коды ошибок | 400, 401, 402, 403, 404, 408, 429, 500, 502, 503 |
| Приватность | «Пользовательские запросы к AI не сохраняются» у агрегатора, но передаются вышестоящему провайдеру; OpenAI, Anthropic, Google Vertex, Mistral, xAI, Meta, Cohere — до 30 дней; **DeepSeek — «возможно обучение на данных», OpenInference — «нет гарантий»** |
| Плагины | `web`, `response-healing`, `file-parser` существуют и **не используются** нами |

Документированных ограничений частоты запросов на открытых страницах не
найдено; отдельного лимита в отчёте нет.

## Checks

- `uv run python scripts/check.py --scope backend` — **PASS**: ruff, mypy
  strict, тесты `unit + contract + ai` без сети.
- Сценарии адаптера (200 валидный JSON, 200 в обёртке ```` ```json ````,
  200 невалидный JSON, 200 не по схеме, 400/401/402/403/404/429/500/502/503,
  таймаут, обрыв соединения, пустой ответ) — на `httpx.MockTransport`, каждый
  проверен и как исключение провайдера, и как итоговое `execution.state`.
- Устойчивость: предохранитель открывается после 3 отказов и пропускает одну
  пробную попытку после паузы; перегрузка → `fallback_overloaded`;
  исчерпанный бюджет → `fallback_budget` **без HTTP-вызова**.
- Приватность: тело HTTP-запроса содержит только замаскированные тексты,
  псевдонимы и номера `m1..mN`/`open:K`; `line_id`, `author_ref` и `ref`
  открытых элементов в тело не попадают; ключ присутствует только в
  заголовке, его нет в `repr` и в логах, а отказ 401/403 логируется один раз.
- `uv run python evaluation/run_eval.py --provider rules` — все полы PASS,
  включая новые полы набора v2.
- `uv build --wheel` во временный каталог вне репозитория — в wheel есть
  `domsignal/ai/resources/prompts/window.v1.md`,
  `prompts/window.v1.examples.jsonl` и `models.v1.yaml`.

## Отбор моделей (только синтетика)

Прогон 20.09.2026: **300 вызовов, 32,07 ₽** из лимита 300 вызовов и 500 ₽.
Прогон остановился ровно на границе вызовов, поэтому последний кандидат получил
58 окон из 60 — это записано в отчёте. Полный отчёт с таблицами по обоим
этапам: [`evaluation/reports/2026-09-20-p2-model-selection.md`](../../evaluation/reports/2026-09-20-p2-model-selection.md).

Этап 1 — 20 фиксированных окон (контекстная опасность `sw01–sw05`, отрицания,
внешние территории, окна потока E0c):

| Модель | Режим схемы | Валидный JSON | p50 / p95 | ₽ за окно | Выдуманные цитаты | Контекстная опасность |
|---|---|---|---|---|---|---|
| `openai/gpt-5-mini` | `json_schema_strict` | 20/20 | 8,7 / 12,8 с | 0,197 | 0/64 | 5/5 |
| `openai/gpt-4.1-nano` | `json_schema_strict` | 20/20 | 3,4 / 5,2 с | 0,040 | 27/45 (60 %) | 1/5 |
| `google/gemini-3.1-flash-lite` | `json_schema_strict` | 20/20 | 3,5 / 5,3 с | 0,171 | 3/76 (4 %) | 5/5 |
| `openai/gpt-5-nano` | `json_schema_strict` | 17/20 | 7,8 / 12,1 с | 0,053 | 9/65 (13,9 %) | 5/5 |
| `sber/gigachat-2` | `json_object` | 16/20 | 2,1 / 3,5 с | 0,250 | 8/53 (15,1 %) | 4/5 |
| `mistralai/mistral-small-2603` | понижен до `json_object` | 0/20 | 1,1 / 1,4 с | 0,000 | — | 0/5 |

Этап 2 — стратифицированная выборка (60 окон; у последнего кандидата 58):

| Модель | Валидный JSON | p50 / p95 | ₽ за окно | Выдуманные цитаты | Роль | Подтип | Территория | Пропущено / ложных | Опровержения | Согласие с правилами | `no_new_facts` | Качество |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `openai/gpt-5-mini` | 58/58 | 5,5 / 9,6 с | 0,158 | 0/190 | 52/57 | 5/5 | 4/5 | 0 / 3 | 6/7 | 52/57 | 0 | 0,90 |
| `google/gemini-3.1-flash-lite` | 60/60 | 3,3 / 4,3 с | 0,111 | 0/215 | 52/57 | 4/5 | 3/5 | 1 / 2 | 6/12 | 53/57 | 5 | 0,77 |
| `openai/gpt-4.1-nano` | 60/60 | 3,2 / 4,0 с | 0,035 | 79/139 (56,8 %) | 50/57 | 4/5 | 1/5 | 2 / 1 | 6/8 | 49/57 | 0 | 0,63 |

**Итог.** Модель по умолчанию — `openai/gpt-5-mini`, резерв —
`google/gemini-3.1-flash-lite`; оба в режиме `json_schema_strict`. Записаны в
`src/domsignal/ai/resources/models.v1.yaml` вместе с режимом схемы, лимитом
токенов, рекомендованным таймаутом (по измеренному p95 + 2 с, не ниже 10 с),
основанием политики обработки данных и датой проверки.

**Второго резерва нет.** `openai/gpt-4.1-nano` отсеян правилом: 56,8 %
выдуманных цитат и контекстная опасность 1 из 5. `sber/gigachat-2` (80 %) и
`openai/gpt-5-nano` (85 %) не прошли порог валидного JSON на этапе 1.
`mistralai/mistral-small-2603` не отработал ни одного окна ни в одном режиме
схемы: 20 из 20 вызовов вернули ошибку HTTP, понижение режима не помогло.
Третий резерв потребовал бы отдельного прогона с другим `max_tokens`.

**Что это подтвердило по существу.** Разница между моделями оказалась не в
«умеет ли JSON», а в **выдуманных цитатах**: `gpt-4.1-nano` при 100 %
формально валидных ответов придумал больше половины цитат, и их отбросил наш
валидатор (32 события `field_dropped`). Это ровно тот случай, ради которого
источником истины остаётся валидатор, а не гарантия провайдера.

## Not verified / blockers

- Числа отбора — **синтетика**. Это инженерный выбор модели и режима схемы,
  а не решение о включении LLM-слоя: оно принимается в P6 на данных D2/D3.
- Условия обработки данных вышестоящими провайдерами отдельно не
  открывались: основание допуска модели — страница polza.ai
  «Конфиденциальность» и поля каталога моделей. Для пилота нужен отдельный
  gate выбора провайдера (целевая архитектура v3 §12).
- Реальные выгрузки чатов из `data/` не открывались и не использовались.
- Продуктовой проводки нет намеренно: `bootstrap.py`, `compose*.yaml`,
  Docker, worker, API и БД не трогались — это P3b/P4 у DEV-B.
- Поведение на реальных сообщениях жителей по-прежнему неизвестно.

## For teammate (DEV-B) — проводка провайдера в P3b/P4

Продукт по-прежнему видит только `WindowAnalyzer.analyze(window) -> WindowAnalysis`.
Провайдер — деталь сборки; ни адаптер, ни устойчивость не импортируют
`domsignal.settings` и ничего не знают о БД.

Коды подтипов и значения `location_scope` для Responsibility Router (P3a)
переданы в P1 и в этом срезе **не менялись**: полный список —
`src/domsignal/ai/resources/taxonomy.v2.yaml` и
`domsignal.ai.contracts.LOCATION_SCOPES`. Точки входа те же:
`WindowAnalyzer.analyze`, `decide_explicit_report`,
`screen_message_for_danger`, `domsignal.ai.windowing.build_windows`.

**Сборка провайдера из настроек** (`bootstrap.py`, зона DEV-B):

```python
from domsignal.ai import (
    InMemoryBudgetGuard, OpenAICompatibleProvider, ResilientProvider,
    CircuitBreaker, ConcurrencyLimiter, WindowAnalyzer, load_models,
)

profile = load_models().default                      # модель, режим схемы, лимиты
provider = OpenAICompatibleProvider(
    base_url=settings.llm_base_url,
    api_key=settings.llm_api_key,
    model=settings.llm_model or profile.id,
    schema_mode=settings.llm_schema_mode.value,      # или profile.schema_mode
    timeout_seconds=settings.llm_timeout_seconds,
    max_tokens=settings.llm_max_tokens,
    temperature=profile.temperature,                 # None → поле не отправляется
    extra_body=profile.extra_body,                   # параметры семейства модели
)
analyzer = WindowAnalyzer(
    ResilientProvider(
        provider,
        breaker=CircuitBreaker(failure_threshold=3, reset_seconds=60),
        limiter=ConcurrencyLimiter(settings.llm_max_concurrency, wait_seconds=1.5),
        budget=budget_guard,                         # см. ниже
    ),
    timeout_s=settings.llm_timeout_seconds + 2,
)
```

`OpenAICompatibleProvider` владеет `httpx.AsyncClient`; на остановке процесса
нужен `await provider.aclose()` (или `async with`). Клиент можно передать
снаружи параметром `client=`.

**Семантика `BudgetGuard`** (протокол в `domsignal.ai.resilience`):

| Метод | Когда вызывается | Что обязан делать |
|---|---|---|
| `try_acquire(scope_key) -> bool` | **до** обращения к провайдеру | атомарно проверить и **списать** единицу дневного лимита. `False` — «вызова не будет»: лимит суток исчерпан или область выбрала свою долю. В PostgreSQL это один `UPDATE … RETURNING`, иначе параллельные реплики перебирают лимит |
| `record(outcome)` | **после** попытки, ровно один раз на каждое успешное `try_acquire` | уточнить учёт: фактическая стоимость (`cost_rub`) и токены. Единица при отказе **не возвращается** — запрос уже ушёл к провайдеру и мог быть оплачен |

Область бюджета (обычно привязка чата) в запрос окна не входит и входить не
может: во внешний вызов идентификаторы продукта не уходят. Она задаётся рядом
с вызовом:

```python
from domsignal.ai import budget_scope

with budget_scope(str(chat_connection_id)):
    analysis = await analyzer.analyze(window)
```

`InMemoryBudgetGuard(daily_calls, chat_share=...)` годится для одного процесса
и для оценки. Для нескольких реплик воркера нужен счётчик в PostgreSQL с той
же семантикой — это P4.

**Отображение отказов в состояния** (`WindowAnalysis.execution.state`). Фасад
не бросает исключений: при любом отказе продукт получает результат правил.

| Исключение провайдера | `execution.state` | Был ли HTTP-вызов |
|---|---|---|
| `ProviderTimeout`, `TimeoutError` | `fallback_timeout` | да |
| `ProviderUnavailable` (сеть, 400/401/402/403/404/429/5xx) | `fallback_provider_error` | да |
| `ProviderInvalidOutput`, ответ не по схеме | `fallback_invalid_output` | да |
| `ProviderBudgetExceeded` | `fallback_budget` | **нет** |
| `ProviderCircuitOpen` | `fallback_circuit_open` | **нет** |
| `ProviderOverloaded` | `fallback_overloaded` | **нет** |
| провайдер не задан | `disabled` | нет |
| упали сами правила | `error_rules`, режим `manual` | нет |

`execution.provider_called` отличает «вызов был и не удался» от «вызова не
было». Для мониторинга доли деградации достаточно этого поля и `state`.

**Учёт токенов и стоимости.** `execution.provider_model`, `tokens_in`,
`tokens_out`, `cost_rub` заполняются только тем, что сообщил провайдер;
`None` означает «не сообщил», а не ноль. polza.ai возвращает
`usage.prompt_tokens`, `usage.completion_tokens` и `usage.cost_rub` (рубли,
фактически списанная сумма). `versions.prompt` и `versions.model` заполняются
только когда модель действительно ответила.

**Настройки** (короткий diff `settings.py`, согласован за DEV-B):
`LLM_PROVIDER` (`rules` по умолчанию, `openai_compatible` включает внешний
вызов), `LLM_BASE_URL` (только HTTPS, по умолчанию `https://polza.ai/api/v1`),
`LLM_API_KEY` (`repr=False`), `LLM_MODEL`, `LLM_SCHEMA_MODE`,
`LLM_TIMEOUT_SECONDS` (10), `LLM_MAX_TOKENS`, `LLM_MAX_CONCURRENCY`,
`LLM_DAILY_CALL_BUDGET`, `LLM_CHAT_DAILY_SHARE`. При `openai_compatible` ключ
и модель обязательны — в production требования те же, плюс запрет
значения-заглушки. `bootstrap.py`, `compose*.yaml` и Docker не трогались:
проводка — P3b/P4.
