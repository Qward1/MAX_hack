import { type FormEvent, useCallback, useEffect, useId, useRef, useState } from "react";
import {
  ApiProblem,
  type DomSignalApi,
  type DuplicateCandidate,
  type IncidentDetail,
  problemStatus,
  type ReportCreate,
  type ReportPreview,
  type ReportSubmitted,
  retryable,
} from "../../shared/api/client";
import { maxBridge } from "../../shared/max/bridge";
import { Button } from "../../shared/ui/Button";
import { ChoicePicker } from "../../shared/ui/ChoicePicker";
import { countLabel, formatDay, formatWhen } from "../../shared/ui/format";
import { DemoBadge, Notice, PageHeader, StatusBadge, StatusTag } from "../../shared/ui/semantic";
import { SourceDisclosure } from "../../shared/ui/SourceLink";
import { residentTicketStatus, statusOf } from "../../shared/ui/status";
import { CardAction, RouteCard, SafetyPanel, UNVERIFIED_NOTE } from "../routing/RouteCard";
import { type CardActionType, dangerLabel, knownCardActions, linkActions, locationScopeLabel } from "../routing/presentation";
import { categoryLabel, categoryLabels } from "./presentation";

export type FlowTarget = { incident?: string; card?: string; draft?: string };

/** Черновик формы живёт в памяти приложения: назад и обратно — текст на месте. */
export type ReportDraft = { text: string; category: ReportCreate["category"] | "" };

export const MIN_LENGTH = 5;
/** С какой длины описание на шаге проверки свёрнуто. */
const LONG_TEXT = 280;
export const MAX_LENGTH = 2000;
const UNSURE_NOTE = "Мы не уверены, что поняли всё правильно.";
const DISPATCHER_NOTE = "Ответственный пока не определён — разберёт диспетчер управляющей компании.";
const ALSO_UK_NOTE =
  "Это не отменяет официальное обращение: его вы по-прежнему отправляете сами.";
export const DUPLICATES_TITLE = "Похоже, об этом уже сообщали";
const NEIGHBOURS = ["сосед", "соседа", "соседей"] as const;

function failureText(error: unknown, action: string): string {
  const status = problemStatus(error);
  if (status === 401) return `Не удалось ${action}: сессия MAX истекла. Закройте мини-приложение и откройте его снова. Текст сохранён.`;
  if (status === 403) return `Не удалось ${action}: нет доступа к этому дому. Текст сохранён.`;
  if (status === 429) return `Не удалось ${action}: слишком много попыток. Подождите минуту и попробуйте ещё раз. Текст сохранён.`;
  if (error instanceof ApiProblem && error.problem.field_errors?.length)
    return `Не удалось ${action}. Проверьте описание проблемы. Текст сохранён.`;
  return `Не удалось ${action}. Проверьте интернет и попробуйте ещё раз. Текст сохранён.`;
}

function Candidate({
  candidate,
  onJoin,
  busy,
}: {
  candidate: DuplicateCandidate;
  onJoin: () => void;
  busy: boolean;
}) {
  const created = formatWhen(candidate.created_at);
  return (
    <li className="ds-row">
      <div className="ds-row-head">
        <h3 className="ds-row-title">{candidate.title}</h3>
        <StatusBadge status={candidate.status} />
      </div>
      <p className="ds-subtle">{candidate.match_reason}</p>
      <p className="ds-meta">
        {categoryLabel(candidate.category)}
        {created && `, сообщили ${created}`}
        {`, ${countLabel(candidate.participant_count, NEIGHBOURS)}`}
      </p>
      <Button stretched disabled={busy} onClick={onJoin} aria-label={`Это та же проблема: ${candidate.title}`}>
        Это та же проблема
      </Button>
    </li>
  );
}

/**
 * «Сообщить о проблеме»: описание → «Проверьте, что мы поняли» → результат.
 *
 * Описание и выбранная категория сохраняются при возврате, ошибке и смене
 * шага. Найденный дубль ничего не решает за жителя: пока он не выбрал сам,
 * не отправляется ничего, и автоматического слияния нет.
 */
export function ReportFlow({
  houseId,
  houseAddress,
  client,
  draft,
  onDraft,
  onOpen,
  onCreated,
  onBoard,
}: {
  houseId: string;
  houseAddress?: string;
  client: DomSignalApi;
  draft?: ReportDraft;
  onDraft?: (draft: ReportDraft | null) => void;
  onOpen: (target: FlowTarget) => void;
  onCreated: () => void;
  onBoard?: () => void;
}) {
  const id = useId();
  const field = useRef<HTMLTextAreaElement | null>(null);
  const duplicatesRef = useRef<HTMLElement | null>(null);
  const categoryRef = useRef<HTMLDivElement | null>(null);
  const [text, setText] = useState(draft?.text ?? "");
  const [category, setCategory] = useState<ReportCreate["category"] | "">(draft?.category ?? "");
  // «Изменить категорию» с шага проверки: на первом шаге фокус — на выборе категории.
  const [manual, setManual] = useState(false);
  const [tooShort, setTooShort] = useState(false);
  const [preview, setPreview] = useState<ReportPreview | null>(null);
  const [result, setResult] = useState<ReportSubmitted | null>(null);
  const [ticketNumber, setTicketNumber] = useState<{ number: string | null; status: string | null } | null>(null);
  const [joined, setJoined] = useState<IncidentDetail | null>(null);
  const [alsoUk, setAlsoUk] = useState<{ incident: IncidentDetail; number: string | null } | null>(null);
  const [error, setError] = useState<{ reason: unknown; action: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [fullText, setFullText] = useState(false);
  const pending = useRef(false);
  const attempt = useRef<{ body: string; key: string } | null>(null);

  const step = result ? "result" : joined ? "joined" : preview ? "review" : "describe";

  // Текст хранится в памяти приложения, пока его не отправили.
  useEffect(() => {
    if (step === "result" || step === "joined") onDraft?.(null);
    else onDraft?.({ text, category });
  }, [text, category, step, onDraft]);
  // Несохранённый текст — предупреждение MAX при закрытии мини-приложения.
  useEffect(() => {
    const unsaved = text.trim().length > 0 && (step === "describe" || step === "review");
    maxBridge.closingConfirmation(unsaved);
    return () => maxBridge.closingConfirmation(false);
  }, [text, step]);
  // Новый шаг — новый заголовок: фокус переносится на него (на первом — в поле).
  useEffect(() => {
    if (step === "describe" && manual) categoryRef.current?.querySelector("button")?.focus({ preventScroll: true });
    else if (step === "describe") field.current?.focus({ preventScroll: true });
    else document.getElementById("page-title")?.focus({ preventScroll: true });
    window.scrollTo?.(0, 0);
  }, [step]);

  const key = useCallback((body: string) => {
    if (attempt.current?.body !== body) attempt.current = { body, key: crypto.randomUUID() };
    return attempt.current.key;
  }, []);

  const guard = useCallback(async (action: string, run: () => Promise<void>) => {
    if (pending.current) return;
    pending.current = true;
    setBusy(true);
    setError(null);
    try {
      await run();
    } catch (failure) {
      setError({ reason: failure, action });
      maxBridge.haptic("error");
    } finally {
      pending.current = false;
      setBusy(false);
    }
  }, []);

  const submit = useCallback(
    () =>
      guard("отправить сообщение", async () => {
        const payload = { description: text, category: category || null };
        const submitted = await client.submitReport(houseId, payload, key(JSON.stringify(payload)));
        const incident = submitted.report?.incident.id;
        // Номер заявки — только если система его знает.
        if (incident && submitted.decision === "ticket") {
          try {
            const work = await client.workStatus(incident);
            if (work.ticket_id) setTicketNumber({ number: work.internal_number, status: work.status });
          } catch {
            /* Номер покажет карточка проблемы. */
          }
        }
        setResult(submitted);
        maxBridge.haptic("success");
        onCreated();
      }),
    [client, houseId, text, category, key, guard, onCreated],
  );

  function describe(event: FormEvent) {
    event.preventDefault();
    if (text.trim().length < MIN_LENGTH) {
      setTooShort(true);
      field.current?.focus();
      return;
    }
    void guard("проверить описание", async () => {
      setPreview(await client.previewReport(houseId, text));
    });
  }

  const failure = error && (
    <Notice tone="danger" role="alert">
      <p>{failureText(error.reason, error.action)}</p>
    </Notice>
  );

  // ------------------------------------------------------------- результат
  if (result) {
    const card = result.action_card;
    const incidentId = result.report?.incident.id ?? null;
    const external = result.decision === "external";
    const ticketEntry = ticketNumber ? statusOf(residentTicketStatus, ticketNumber.status) : null;
    return (
      <section className="report-flow" aria-labelledby="page-title">
        <PageHeader title="Сообщение сохранено" subtitle={houseAddress} />
        {card.safety && <SafetyPanel safety={card.safety} />}
        <div className="ds-status-block" role="status">
          {ticketEntry && ticketNumber?.number ? (
            <>
              <div className="ds-status-line">
                <StatusTag entry={ticketEntry} />
                <span className="ds-strong">Заявка в управляющую компанию {ticketNumber.number}</span>
              </div>
              {ticketEntry.next && <p className="ds-next">{ticketEntry.next}</p>}
            </>
          ) : external ? (
            <p className="ds-next">
              Проблема, вероятно, вне зоны вашей управляющей компании. Обратиться нужно самостоятельно — ниже
              сказано куда.
            </p>
          ) : result.decision === "needs_clarification" ? (
            <p className="ds-next">{DISPATCHER_NOTE}</p>
          ) : (
            <p className="ds-next">Проблема появилась на доске дома.</p>
          )}
          <p className="ds-subtle">Статус видно в карточке проблемы и в разделе «Мои обращения».</p>
        </div>
        {!external && (
          <div className="ds-stack">
            {incidentId && (
              <Button variant="primary" stretched onClick={() => onOpen({ incident: incidentId })}>
                Открыть проблему
              </Button>
            )}
            {onBoard && (
              <Button stretched onClick={onBoard}>
                К проблемам дома
              </Button>
            )}
            <Button variant="tertiary" onClick={() => onOpen({ card: result.route_outcome_id })}>
              Кто отвечает и почему
            </Button>
          </div>
        )}
        {external && (
          <RouteCard
            card={card}
            busy={busy}
            hideSafety
            handlers={{
              prepare_appeal: () =>
                void guard("подготовить текст обращения", async () => {
                  const created = await client.createAppealDraft({
                    house_id: houseId,
                    route_outcome_id: result.route_outcome_id,
                  });
                  onOpen({ draft: created.id, card: result.route_outcome_id });
                }),
              report_to_uk_anyway: () =>
                void guard("сообщить в управляющую компанию", async () => {
                  const payload: ReportCreate = {
                    house_id: houseId,
                    category: result.analysis.category,
                    description: text,
                    classification_mode: "manual",
                  };
                  const created = await client.createReport(payload, key(JSON.stringify(["also-uk", payload])));
                  let number: string | null = null;
                  try {
                    const work = await client.workStatus(created.incident.id);
                    number = work.ticket_id ? work.internal_number : null;
                  } catch {
                    /* Номер покажет карточка проблемы. */
                  }
                  setAlsoUk({ incident: created.incident, number });
                  onCreated();
                }),
            }}
            extra={
              incidentId ? (
                <Button stretched onClick={() => onOpen({ incident: incidentId })}>
                  Открыть проблему
                </Button>
              ) : undefined
            }
          />
        )}
        {alsoUk && (
          <Notice tone="success" role="status">
            <p className="ds-strong">
              {alsoUk.number
                ? `Заявка в управляющую компанию ${alsoUk.number} создана.`
                : "Сообщение для управляющей компании сохранено."}
            </p>
            <p className="ds-prose">{ALSO_UK_NOTE}</p>
            <Button onClick={() => onOpen({ incident: alsoUk.incident.id })}>Открыть проблему</Button>
          </Notice>
        )}
        {failure}
      </section>
    );
  }

  // ------------------------------------------------ присоединение к дублю
  if (joined)
    return (
      <section className="report-flow" aria-labelledby="page-title">
        <PageHeader title="Вы присоединились к проблеме" subtitle={houseAddress} />
        <div className="ds-status-block" role="status">
          <p className="ds-strong">{joined.title}</p>
          <p className="ds-next">
            Ваше сообщение добавлено к ней: теперь {countLabel(joined.participant_count ?? 0, NEIGHBOURS)} отметили
            эту проблему. Новая заявка не создаётся.
          </p>
          <p className="ds-subtle">Проблема есть в разделе «Мои обращения».</p>
        </div>
        <Button variant="primary" stretched onClick={() => onOpen({ incident: joined.id })}>
          Открыть проблему
        </Button>
      </section>
    );

  // ------------------------------------------------------- шаг «проверьте»
  if (preview) {
    const analysis = preview.analysis;
    const card = preview.action_card;
    const duplicates = preview.duplicates ?? [];
    const safety = card.safety;
    // Телефон памятки уже стоит первой кнопкой экрана — второй раз его не повторяем.
    const cardActions = knownCardActions(card.actions).filter(
      (action) => !(safety?.phone && action.type === "call_phone" && action.phone === safety.phone),
    );
    const offersTicket =
      duplicates.length === 0 && cardActions.some((action) => action.type === "create_ticket" && action.enabled);
    const handlers: Partial<Record<CardActionType, () => void>> = offersTicket ? { create_ticket: () => void submit() } : {};
    // Основное действие шага — сохранить сообщение (заявкой в УК, если её предлагают);
    // ссылки на официальные сервисы и звонок — рядом, вторыми.
    const primaryAction = cardActions.find((action) => action.type === "create_ticket" && offersTicket);
    const otherActions = cardActions.filter(
      (action) => action !== primaryAction && (linkActions.includes(action.type as CardActionType) || handlers[action.type as CardActionType]),
    );
    const dangers = analysis.danger_kinds.map(dangerLabel).filter(Boolean);
    const place = [
      locationScopeLabel(analysis.location_scope),
      analysis.entrance && `подъезд ${analysis.entrance}`,
      analysis.floor && `этаж ${analysis.floor}`,
    ]
      .filter(Boolean)
      .join(", ");
    const change = (openManual: boolean) => () => {
      setManual(openManual);
      setPreview(null);
    };
    const basis = card.route.basis;
    const needsCheck =
      card.route.stale ||
      (basis ? basis.verification_status !== "verified" : false) ||
      (card.route.channels ?? []).some((channel) => channel.stale || channel.verification_status !== "verified");
    const facts = card.facts ?? [];
    return (
      <section className="report-flow" aria-labelledby="page-title">
        <PageHeader
          title="Проверьте, что мы поняли"
          subtitle={
            <>
              <span className="ds-steps">Шаг 2 из 2</span>
              {houseAddress && (
                <>
                  {" · "}
                  <span className="ds-subtle">{houseAddress}</span>
                </>
              )}
            </>
          }
        />
        {safety && <SafetyPanel safety={safety} />}
        <div className="ds-split ds-review">
          <div className="ds-main">
            <dl className="ds-summary" aria-label="Что мы поняли">
              <div className="ds-summary-row ds-summary-main">
                <dt>Проблема</dt>
                <dd>
                  {/* Длинное описание свёрнуто до нескольких строк: следующий шаг остаётся рядом. */}
                  <p className={text.length > LONG_TEXT && !fullText ? "ds-prose ds-clamp" : "ds-prose"}>{text}</p>
                  {text.length > LONG_TEXT && (
                    <button type="button" className="ds-link-button ds-more" aria-expanded={fullText} onClick={() => setFullText(!fullText)}>
                      {fullText ? "Свернуть" : "Показать полностью"}
                    </button>
                  )}
                </dd>
                <dd className="ds-summary-change">
                  <button type="button" className="ds-edit" onClick={change(false)}>
                    Изменить{" "}
                    <span className="ds-visually-hidden">описание</span>
                  </button>
                </dd>
              </div>
              <div className="ds-summary-row">
                <dt>Где</dt>
                <dd>{place}</dd>
              </div>
              {analysis.since && (
                <div className="ds-summary-row">
                  <dt>Наблюдается с</dt>
                  <dd>{analysis.since}</dd>
                </div>
              )}
              <div className="ds-summary-row">
                <dt>Категория</dt>
                <dd>{categoryLabel(analysis.category)}</dd>
                <dd className="ds-summary-change">
                  <button type="button" className="ds-edit" onClick={change(true)}>
                    Изменить{" "}
                    <span className="ds-visually-hidden">категорию</span>
                  </button>
                </dd>
              </div>
              {dangers.length > 0 && (
                <div className="ds-summary-row ds-summary-danger">
                  <dt>Признаки опасности</dt>
                  <dd>{dangers.join(", ")}</dd>
                </div>
              )}
            </dl>
            {!analysis.confident && (
              <Notice tone="warning" role="note">
                <p>{UNSURE_NOTE} Поправьте описание или категорию, если нужно.</p>
              </Notice>
            )}
          </div>
          <div className="ds-aside">
            {duplicates.length > 0 ? (
              <section className="ds-next-step duplicates" ref={duplicatesRef} aria-labelledby={`${id}-dup`}>
                <h2 id={`${id}-dup`}>{DUPLICATES_TITLE}</h2>
                <p>
                  Если это та же проблема, ваше сообщение добавится к ней — отдельная заявка не появится. Выберите сами:
                  мы не объединяем сообщения без вас.
                </p>
                <ul className="ds-list">
                  {duplicates.map((candidate) => (
                    <Candidate
                      key={candidate.incident_id}
                      candidate={candidate}
                      busy={busy}
                      onJoin={() =>
                        void guard("добавить сообщение к проблеме", async () => {
                          setJoined(
                            await client.joinIncident(
                              candidate.incident_id,
                              key(JSON.stringify(["join", candidate.incident_id])),
                            ),
                          );
                          maxBridge.haptic("success");
                          onCreated();
                        })
                      }
                    />
                  ))}
                </ul>
                <Button stretched loading={busy} loadingLabel="Отправляем…" onClick={() => void submit()}>
                  Нет, это другое
                </Button>
              </section>
            ) : (
              <section className="ds-next-step" aria-labelledby={`${id}-next`}>
                <h2 id={`${id}-next`}>Что дальше</h2>
                <div className="ds-stack">
                  <p className="ds-strong">{card.title}</p>
                  <p className="ds-prose">{card.explanation}</p>
                  {card.route.organization_name && (
                    <p className="ds-meta">Вероятный адресат: {card.route.organization_name}</p>
                  )}
                  {needsCheck && (
                    <Notice tone="warning" role="note">
                      <p>{UNVERIFIED_NOTE}</p>
                    </Notice>
                  )}
                </div>
                <div className="ds-stack">
                  {primaryAction ? (
                    <CardAction action={primaryAction} primary handler={handlers.create_ticket} busy={busy} />
                  ) : (
                    <Button variant="primary" stretched loading={busy} loadingLabel="Отправляем…" onClick={() => void submit()}>
                      Всё верно, отправить
                    </Button>
                  )}
                  {otherActions.map((action) => (
                    <CardAction
                      key={`${action.type}-${action.url ?? action.phone ?? ""}`}
                      action={action}
                      primary={false}
                      handler={handlers[action.type as CardActionType]}
                      busy={busy}
                    />
                  ))}
                </div>
                {failure}
              </section>
            )}
          </div>
          <div className="ds-main-more">
            {duplicates.length > 0 && (
              // При выборе «та же или другая» кто отвечает — рядом, а не только в «Что дальше».
              <section className="ds-section" aria-labelledby={`${id}-route`}>
                <h2 id={`${id}-route`}>{card.title}</h2>
                <p className="ds-prose">{card.explanation}</p>
                {card.route.organization_name && <p className="ds-meta">Вероятный адресат: {card.route.organization_name}</p>}
                {needsCheck && (
                  <Notice tone="warning" role="note">
                    <p>{UNVERIFIED_NOTE}</p>
                  </Notice>
                )}
              </section>
            )}
            <div className="ds-details-list">
              {basis && (
                <details className="ds-disclosure">
                  <summary>
                    <h2 className="ds-summary-title">Кто отвечает и почему</h2>
                  </summary>
                  <div className="ds-disclosure-body">
                    <p className="ds-prose">{basis.text}</p>
                    <SourceDisclosure
                      url={basis.source_url}
                      title={basis.source_title}
                      verified={formatDay(basis.verified_at)}
                    />
                  </div>
                </details>
              )}
              {facts.length > 0 && (
                <details className="ds-disclosure">
                  <summary>
                    <h2 className="ds-summary-title">Что известно об официальном сервисе</h2>
                    <span className="ds-meta">{countLabel(facts.length, ["факт", "факта", "фактов"])}</span>
                  </summary>
                  <ul className="ds-bullets ds-disclosure-body">
                    {facts.map((fact) => (
                      <li key={fact.text}>
                        <span className="ds-prose">{fact.text}</span>
                        <SourceDisclosure url={fact.source_url} title={fact.source_title} />
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </div>
            {(card.disclaimer || card.demo_notice) && (
              <div className="ds-stack route-disclaimer">
                {card.disclaimer && <p className="ds-prose ds-subtle">{card.disclaimer}</p>}
                {card.demo_notice && <DemoBadge />}
              </div>
            )}
          </div>
        </div>
        {duplicates.length > 0 && failure}
      </section>
    );
  }

  // --------------------------------------------------- шаг «что случилось»
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  const counterId = `${id}-counter`;
  return (
    <form className="report-flow ds-form" onSubmit={describe} noValidate>
      <PageHeader
        title="Что случилось?"
        subtitle={
          <>
            <span className="ds-steps">Шаг 1 из 2</span>
            {houseAddress && <span className="ds-subtle"> · {houseAddress}</span>}
          </>
        }
      />
      <div className="ds-field">
        <label htmlFor={`${id}-text`}>Опишите проблему</label>
        <p id={hintId} className="ds-hint">
          Что сломалось и где: подъезд, этаж, с какого времени. Например: «Лифт во втором подъезде не едет с утра».
        </p>
        {tooShort && (
          <p id={errorId} className="ds-error">
            Опишите проблему хотя бы в нескольких словах — от {MIN_LENGTH} символов.
          </p>
        )}
        <textarea
          id={`${id}-text`}
          ref={field}
          data-autofocus
          rows={6}
          value={text}
          maxLength={MAX_LENGTH}
          aria-describedby={[hintId, tooShort ? errorId : "", counterId].filter(Boolean).join(" ")}
          aria-invalid={tooShort || undefined}
          readOnly={busy}
          onChange={(event) => {
            setText(event.target.value);
            if (event.target.value.trim().length >= MIN_LENGTH) setTooShort(false);
            setError(null);
          }}
        />
        <p id={counterId} className="ds-counter">
          {text.length} из {MAX_LENGTH}
        </p>
      </div>
      <div ref={categoryRef}>
        <ChoicePicker
          label="Категория"
          hint="Необязательно: без выбора определим по описанию."
          value={category}
          disabled={busy}
          choices={[
            { value: "", label: "Определить по описанию" },
            ...Object.entries(categoryLabels).map(([value, label]) => ({ value, label })),
          ]}
          onChange={(value) => setCategory(value as ReportCreate["category"] | "")}
        />
      </div>
      {failure}
      <Button
        type="submit"
        variant="primary"
        stretched
        loading={busy}
        loadingLabel="Проверяем…"
        disabled={Boolean(error) && !retryable(error?.reason)}
      >
        Проверить описание
      </Button>
    </form>
  );
}
