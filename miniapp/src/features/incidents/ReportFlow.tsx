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
import { countLabel, formatWhen } from "../../shared/ui/format";
import { CheckAnswers, Notice, PageHeader, StatusBadge, StatusTag } from "../../shared/ui/semantic";
import { residentTicketStatus, statusOf } from "../../shared/ui/status";
import { RouteCard, SafetyPanel } from "../routing/RouteCard";
import { dangerLabel, knownCardActions, locationScopeLabel } from "../routing/presentation";
import { categoryLabel, categoryLabels } from "./presentation";

export type FlowTarget = { incident?: string; card?: string; draft?: string };

/** Черновик формы живёт в памяти приложения: назад и обратно — текст на месте. */
export type ReportDraft = { text: string; category: ReportCreate["category"] | "" };

export const MIN_LENGTH = 5;
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
  const [text, setText] = useState(draft?.text ?? "");
  const [category, setCategory] = useState<ReportCreate["category"] | "">(draft?.category ?? "");
  const [manual, setManual] = useState(Boolean(draft?.category));
  const [tooShort, setTooShort] = useState(false);
  const [preview, setPreview] = useState<ReportPreview | null>(null);
  const [result, setResult] = useState<ReportSubmitted | null>(null);
  const [ticketNumber, setTicketNumber] = useState<{ number: string | null; status: string | null } | null>(null);
  const [joined, setJoined] = useState<IncidentDetail | null>(null);
  const [alsoUk, setAlsoUk] = useState<{ incident: IncidentDetail; number: string | null } | null>(null);
  const [error, setError] = useState<{ reason: unknown; action: string } | null>(null);
  const [busy, setBusy] = useState(false);
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
    if (step === "describe") field.current?.focus({ preventScroll: true });
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
            <Button variant="quiet" onClick={() => onOpen({ card: result.route_outcome_id })}>
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
                  onOpen({ draft: created.id });
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
    const duplicates = preview.duplicates ?? [];
    const cardActions = knownCardActions(preview.action_card.actions);
    const offersTicket =
      duplicates.length === 0 && cardActions.some((action) => action.type === "create_ticket" && action.enabled);
    const dangers = analysis.danger_kinds.map(dangerLabel).filter(Boolean);
    const change = (openManual: boolean) => () => {
      setManual(openManual || manual);
      setPreview(null);
    };
    const items = [
      ...(houseAddress ? [{ label: "Дом", value: houseAddress }] : []),
      { label: "Описание", value: <span className="ds-prose">{text}</span>, change: change(false) },
      { label: "Категория", value: categoryLabel(analysis.category), change: change(true) },
      { label: "Место", value: locationScopeLabel(analysis.location_scope) },
      ...(analysis.entrance ? [{ label: "Подъезд", value: analysis.entrance }] : []),
      ...(analysis.floor ? [{ label: "Этаж", value: analysis.floor }] : []),
      ...(analysis.since ? [{ label: "Наблюдается с", value: analysis.since }] : []),
      ...(dangers.length ? [{ label: "Признаки опасности", value: dangers.join(", ") }] : []),
    ];
    return (
      <section className="report-flow" aria-labelledby="page-title">
        <PageHeader title="Проверьте, что мы поняли" subtitle={<span className="ds-steps">Шаг 2 из 2</span>} />
        {preview.action_card.safety && <SafetyPanel safety={preview.action_card.safety} />}
        <section className="ds-section" aria-label="Что мы поняли">
          <CheckAnswers items={items} />
          {!analysis.confident && (
            <Notice tone="warning" role="note">
              <p>{UNSURE_NOTE} Поправьте описание или категорию, если нужно.</p>
            </Notice>
          )}
        </section>
        {duplicates.length > 0 && (
          <section className="ds-section duplicates" ref={duplicatesRef} aria-labelledby={`${id}-dup`}>
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
        )}
        <RouteCard
          card={preview.action_card}
          busy={busy}
          hideSafety
          hideActions={duplicates.length > 0}
          handlers={{
            ...(offersTicket ? { create_ticket: () => void submit() } : {}),
            join_existing: () => duplicatesRef.current?.scrollIntoView(),
          }}
        />
        {!offersTicket && duplicates.length === 0 && (
          <Button variant="primary" stretched loading={busy} loadingLabel="Отправляем…" onClick={() => void submit()}>
            Всё верно, отправить
          </Button>
        )}
        {failure}
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
      <details open={manual} className="ds-disclosure" onToggle={(event) => setManual(event.currentTarget.open)}>
        <summary>Уточнить категорию вручную</summary>
        <div className="ds-disclosure-body">
          <label className="ds-field">
            Категория
            <select
              disabled={busy}
              value={category}
              onChange={(event) => setCategory(event.target.value as ReportCreate["category"] | "")}
            >
              <option value="">Определить по описанию</option>
              {Object.entries(categoryLabels).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
        </div>
      </details>
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
