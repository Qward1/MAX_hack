import { Button, Flex, Panel, Textarea, Typography } from "@maxhub/max-ui";
import { type FormEvent, useCallback, useId, useRef, useState } from "react";
import {
  ApiProblem,
  type DomSignalApi,
  type DuplicateCandidate,
  type IncidentDetail,
  type ReportCreate,
  type ReportPreview,
  type ReportSubmitted,
  retryable,
} from "../../shared/api/client";
import { StatusBadge } from "../../shared/ui/semantic";
import { RouteCard } from "../routing/RouteCard";
import { knownCardActions } from "../routing/presentation";
import { dangerLabel, locationScopeLabel } from "../routing/presentation";
import { categoryLabel, categoryLabels, formatDate } from "./presentation";

export type FlowTarget = { incident?: string; card?: string; draft?: string };

const UNSURE_NOTE = "Мы не уверены, что поняли всё правильно.";
const DISPATCHER_NOTE =
  "Ответственный пока не определён — разберёт диспетчер управляющей компании.";
const ALSO_UK_NOTE =
  "Заявка управляющей компании создана. Это не отменяет внешний маршрут: официальное обращение вы по-прежнему отправляете сами.";
const DUPLICATES_TITLE = "Похоже, об этом уже сообщали";

function Recognized({ preview }: { preview: ReportPreview }) {
  const analysis = preview.analysis;
  const dangers = analysis.danger_kinds.map(dangerLabel).filter(Boolean);
  return (
    <dl>
      <div className="info-row">
        <dt>Категория</dt>
        <dd>{categoryLabel(analysis.category)}</dd>
      </div>
      <div className="info-row">
        <dt>Место</dt>
        <dd>{locationScopeLabel(analysis.location_scope)}</dd>
      </div>
      {analysis.entrance && (
        <div className="info-row">
          <dt>Подъезд</dt>
          <dd>{analysis.entrance}</dd>
        </div>
      )}
      {analysis.floor && (
        <div className="info-row">
          <dt>Этаж</dt>
          <dd>{analysis.floor}</dd>
        </div>
      )}
      {analysis.since && (
        <div className="info-row">
          <dt>Наблюдается с</dt>
          <dd>{analysis.since}</dd>
        </div>
      )}
      {dangers.length > 0 && (
        <div className="info-row">
          <dt>Признаки опасности</dt>
          <dd>{dangers.join(", ")}</dd>
        </div>
      )}
    </dl>
  );
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
  return (
    <Panel className="incident-card duplicate-card">
      <Flex gap={12} wrap="wrap" justify="space-between">
        <Typography.Text variant="label" color="secondary">
          {categoryLabel(candidate.category)}
        </Typography.Text>
        <StatusBadge status={candidate.status} />
      </Flex>
      <Typography.Title asChild>
        <h4>{candidate.title}</h4>
      </Typography.Title>
      <p className="muted">{candidate.match_reason}</p>
      <p className="muted">
        Создана: {formatDate(candidate.created_at) ?? "дата не указана"} · сообщений:{" "}
        {candidate.report_count} · участников: {candidate.participant_count}
      </p>
      <Button variant="secondary" disabled={busy} onClick={onJoin}>
        Это та же проблема
      </Button>
    </Panel>
  );
}

/**
 * Форма как разговор: свободный текст → «проверьте, что мы поняли» → результат.
 *
 * Ручной выбор категории никуда не делся — он ушёл в «Уточнить вручную» и
 * остаётся единственным способом поправить разбор. Найденный дубль ничего не
 * решает за жителя: пока он не выбрал сам, не отправляется ничего.
 */
export function ReportFlow({
  houseId,
  client,
  onOpen,
  onCreated,
}: {
  houseId: string;
  client: DomSignalApi;
  onOpen: (target: FlowTarget) => void;
  onCreated: () => void;
}) {
  const id = useId();
  const duplicatesRef = useRef<HTMLDivElement | null>(null);
  const [text, setText] = useState("");
  const [category, setCategory] = useState<ReportCreate["category"] | "">("");
  const [manual, setManual] = useState(false);
  const [preview, setPreview] = useState<ReportPreview | null>(null);
  const [result, setResult] = useState<ReportSubmitted | null>(null);
  const [joined, setJoined] = useState<IncidentDetail | null>(null);
  const [alsoUk, setAlsoUk] = useState<IncidentDetail | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const pending = useRef(false);
  const attempt = useRef<{ body: string; key: string } | null>(null);

  const key = useCallback((body: string) => {
    if (attempt.current?.body !== body)
      attempt.current = { body, key: crypto.randomUUID() };
    return attempt.current.key;
  }, []);

  const guard = useCallback(async (run: () => Promise<void>) => {
    if (pending.current) return;
    pending.current = true;
    setBusy(true);
    setError(null);
    try {
      await run();
    } catch (failure) {
      setError(failure);
    } finally {
      pending.current = false;
      setBusy(false);
    }
  }, []);

  const submit = useCallback(
    (then?: (submitted: ReportSubmitted) => Promise<void>) =>
      guard(async () => {
        const payload = { description: text, category: category || null };
        const submitted = await client.submitReport(
          houseId,
          payload,
          key(JSON.stringify(payload)),
        );
        setResult(submitted);
        onCreated();
        await then?.(submitted);
      }),
    [client, houseId, text, category, key, guard, onCreated],
  );

  function describe(event: FormEvent) {
    event.preventDefault();
    void guard(async () => {
      setPreview(await client.previewReport(houseId, text));
    });
  }

  const failure = Boolean(error) && (
    <p role="alert">
      Не удалось выполнить действие. Текст сохранён в форме.{" "}
      {error instanceof ApiProblem && error.problem.field_errors?.length
        ? "Проверьте поля формы."
        : retryable(error)
          ? "Попробуйте ещё раз."
          : "Обновите данные и проверьте доступ."}
    </p>
  );

  // ------------------------------------------------------------- результат
  if (result) {
    const card = result.action_card;
    const incidentId = result.report?.incident.id ?? null;
    return (
      <section className="report-flow" aria-labelledby={`${id}-result`}>
        <Typography.Title asChild>
          <h2 id={`${id}-result`}>Что дальше</h2>
        </Typography.Title>
        <RouteCard
          card={card}
          busy={busy}
          handlers={{
            prepare_appeal: () =>
              void guard(async () => {
                const draft = await client.createAppealDraft({
                  house_id: houseId,
                  route_outcome_id: result.route_outcome_id,
                });
                onOpen({ draft: draft.id });
              }),
            report_to_uk_anyway: () =>
              void guard(async () => {
                const payload: ReportCreate = {
                  house_id: houseId,
                  category: result.analysis.category,
                  description: text,
                  classification_mode: "manual",
                };
                const created = await client.createReport(
                  payload,
                  key(JSON.stringify(["also-uk", payload])),
                );
                setAlsoUk(created.incident);
                onCreated();
              }),
          }}
        />
        {alsoUk && (
          <Panel className="honesty-note" role="status">
            <p className="full-text">{ALSO_UK_NOTE}</p>
            <Button variant="secondary" onClick={() => onOpen({ incident: alsoUk.id })}>
              Открыть созданную проблему
            </Button>
          </Panel>
        )}
        {result.decision === "needs_clarification" && (
          <Panel className="honesty-note" role="note">
            {DISPATCHER_NOTE}
          </Panel>
        )}
        <Flex gap={12} wrap="wrap">
          {incidentId && (
            <Button variant="secondary" onClick={() => onOpen({ incident: incidentId })}>
              Открыть проблему
            </Button>
          )}
          <Button
            variant="secondary"
            onClick={() => onOpen({ card: result.route_outcome_id })}
          >
            Открыть карточку маршрута
          </Button>
        </Flex>
        {failure}
      </section>
    );
  }

  // ------------------------------------------------ присоединение к дублю
  if (joined)
    return (
      <section className="report-flow" aria-labelledby={`${id}-joined`}>
        <Typography.Title asChild>
          <h2 id={`${id}-joined`}>Вы присоединились к существующей проблеме</h2>
        </Typography.Title>
        <p className="full-text">{joined.title}</p>
        <p className="muted">
          Сообщений: {joined.report_count} · участников: {joined.participant_count}
        </p>
        <Button onClick={() => onOpen({ incident: joined.id })}>Открыть проблему</Button>
      </section>
    );

  // ------------------------------------------------------- шаг «проверьте»
  if (preview) {
    const duplicates = preview.duplicates ?? [];
    const cardActions = knownCardActions(preview.action_card.actions);
    const offersTicket =
      duplicates.length === 0 &&
      cardActions.some((action) => action.type === "create_ticket" && action.enabled);
    return (
      <section className="report-flow" aria-labelledby={`${id}-review`}>
        <Typography.Title asChild>
          <h2 id={`${id}-review`}>Проверьте, что мы поняли</h2>
        </Typography.Title>
        <Panel className="detail-section">
          <Recognized preview={preview} />
          {!preview.analysis.confident && (
            <p className="honesty-note" role="note">
              {UNSURE_NOTE}
            </p>
          )}
          <Flex gap={12} wrap="wrap">
            <Button
              variant="secondary"
              disabled={busy}
              onClick={() => {
                setManual(true);
                setPreview(null);
              }}
            >
              Это не так
            </Button>
          </Flex>
        </Panel>
        {duplicates.length > 0 && (
          <Panel className="detail-section duplicates" ref={duplicatesRef}>
            <Typography.Title asChild>
              <h3>{DUPLICATES_TITLE}</h3>
            </Typography.Title>
            <p className="muted">
              Выберите сами: продукт не объединяет обращения за вас.
            </p>
            <ul className="duplicate-grid">
              {duplicates.map((candidate) => (
                <li key={candidate.incident_id}>
                  <Candidate
                    candidate={candidate}
                    busy={busy}
                    onJoin={() =>
                      void guard(async () => {
                        setJoined(
                          await client.joinIncident(
                            candidate.incident_id,
                            key(JSON.stringify(["join", candidate.incident_id])),
                          ),
                        );
                        onCreated();
                      })
                    }
                  />
                </li>
              ))}
            </ul>
          </Panel>
        )}
        <RouteCard
          card={preview.action_card}
          busy={busy}
          handlers={{
            ...(offersTicket ? { create_ticket: () => void submit() } : {}),
            join_existing: () => duplicatesRef.current?.scrollIntoView(),
          }}
        />
        {!offersTicket && (
          <Button stretched disabled={busy} onClick={() => void submit()}>
            {duplicates.length > 0 ? "Нет, это другое" : "Всё верно, отправить"}
          </Button>
        )}
        {failure}
      </section>
    );
  }

  // --------------------------------------------------- шаг «что случилось»
  return (
    <form className="report-form report-flow" onSubmit={describe}>
      <Typography.Title asChild>
        <h2>Что случилось?</h2>
      </Typography.Title>
      <label>
        Описание
        <Textarea
          disabled={busy}
          value={text}
          onChange={(event) => {
            setText(event.target.value);
            setError(null);
          }}
          minLength={5}
          maxLength={2000}
          required
          placeholder="Например: лифт не реагирует на кнопку на первом этаже"
        />
      </label>
      <details open={manual} className="manual-category">
        <summary>Уточнить вручную</summary>
        <label>
          Категория
          <select
            disabled={busy}
            value={category}
            onChange={(event) =>
              setCategory(event.target.value as ReportCreate["category"] | "")
            }
          >
            <option value="">Определить по описанию</option>
            {Object.entries(categoryLabels).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
      </details>
      {failure}
      <Button
        type="submit"
        disabled={busy || text.trim().length < 5 || (Boolean(error) && !retryable(error))}
      >
        {busy ? "Разбираем…" : "Дальше"}
      </Button>
    </form>
  );
}
