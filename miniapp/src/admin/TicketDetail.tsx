import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { ApiProblem, type IncidentDetail, type Me } from "../shared/api/client";
import type { components } from "../shared/api/schema";
import {
  type Ticket,
  TicketClient,
  type TicketAction,
  type TicketCommand,
} from "../shared/api/tickets";
import { useResource } from "../shared/api/useResource";
import { categoryLabel, formatDate } from "../features/incidents/presentation";
import {
  Pagination,
  TicketDeadlines,
  TicketState,
  TicketStatusBadge,
  TicketTimeline,
  WorkAttemptCard,
} from "../features/tickets/components";
import { actionLabels, ticketActions } from "../features/tickets/presentation";
import {
  safeError,
  useTicketMutation,
} from "../features/tickets/useTicketMutation";
import { adminUrl } from "./AdminApp";

type DetailData = { ticket: Ticket; incident: IncidentDetail };
type Mutation = components["schemas"]["TicketMutation"];
type FormAction =
  | "assign"
  | "work-attempts"
  | "clarify"
  | "wait-external"
  | "resume"
  | "cancel";
const implemented = [
  "assign",
  "accept",
  "start",
  "work-attempts",
  "clarify",
  "wait-external",
  "resume",
  "cancel",
];

export function TicketDetail({
  client,
  id,
  me,
  revision,
  navigate,
}: {
  client: TicketClient;
  id: string;
  me: Me;
  revision: number;
  navigate: (url: string) => void;
}) {
  const load = useCallback(
    async (signal: AbortSignal) => {
      const ticket = await client.ticket(id, signal);
      const incident = await client.incident(
        ticket.incident_id,
        signal,
        ticket.house_id,
      );
      return { ticket, incident };
    },
    [client, id],
  );
  const resource = useResource(`${id}:${revision}`, load);
  const mutation = useTicketMutation<Mutation, DetailData>();
  const [form, setForm] = useState<FormAction | null>(null);
  const [historyRevision, setHistoryRevision] = useState(0);
  const data = resource.data;
  useEffect(() => {
    if (data) document.getElementById("page-title")?.focus();
  }, [Boolean(data)]);
  const back = (
    <a
      href={adminUrl()}
      onClick={(e) => {
        e.preventDefault();
        navigate(adminUrl());
      }}
    >
      ← К заявкам
    </a>
  );
  if (!data)
    return (
      <>
        {back}
        <TicketState
          loading={resource.loading}
          error={resource.error}
          retry={resource.refresh}
        />
      </>
    );
  const { ticket, incident } = data;
  const actions = ticketActions(ticket.allowed_actions).filter((a) =>
    implemented.includes(a.code),
  );
  const blocked =
    resource.loading ||
    resource.stale ||
    Boolean(resource.error) ||
    mutation.saving ||
    mutation.uncertain;
  function submit(action: TicketAction, payload: TicketCommand) {
    if (blocked || !actions.some((a) => a.code === action && a.enabled)) return;
    mutation.run({
      write: (key) => client.command(id, action, payload, key),
      read: async () => {
        const current = await resource.reload();
        setHistoryRevision((v) => v + 1);
        return current;
      },
      success: (_result, current) => {
        setForm(null);
        if (
          action === "work-attempts" &&
          current.ticket.status === "verification_pending"
        )
          return "Результат сохранён. Ожидается проверка жителей.";
        return "Действие сохранено. Показаны актуальные данные заявки.";
      },
      // A-16 may return 403 after another actor claims, because authorization precedes version checking.
      conflict: (_error, current) =>
        action === "accept" &&
        current.ticket.assignee_id !== null &&
        current.ticket.assignee_id !== me.id
          ? "Заявку уже принял другой сотрудник. Данные обновлены."
          : undefined,
    });
  }
  const house = me.houses.find((h) => h.id === ticket.house_id);
  return (
    <>
      <div className="detail-back">{back}</div>
      <header className="page-header">
        <span className="ticket-number">Заявка {ticket.internal_number}</span>
        <h1 id="page-title" tabIndex={-1}>
          {incident.title || categoryLabel(incident.category)}
        </h1>
        <TicketStatusBadge status={ticket.status} />
      </header>
      {resource.loading && <p role="status">Обновляем заявку…</p>}
      {Boolean(resource.error) && (
        <TicketState error={resource.error} retry={resource.refresh} />
      )}
      {resource.stale && (
        <div className="refresh-notice">
          Данные могли измениться.{" "}
          <button
            className="ticket-button secondary"
            onClick={resource.refresh}
            disabled={mutation.saving}
          >
            Обновить заявку
          </button>
        </div>
      )}
      <section
        className="ticket-panel next-action"
        aria-labelledby="ticket-actions-title"
        aria-busy={mutation.saving}
      >
        <span className="eyebrow">Следующий шаг</span>
        <h2 id="ticket-actions-title">Действия по заявке</h2>
        <div className="ticket-buttons">
          {actions.map((a) => (
            <div key={a.code}>
              <button
                className={`ticket-button ${["assign", "clarify", "wait-external", "cancel"].includes(a.code) ? "secondary" : ""}`}
                disabled={blocked || !a.enabled}
                aria-describedby={a.reason ? `reason-${a.code}` : undefined}
                onClick={() => {
                  if (!a.enabled || blocked) return;
                  if (a.code === "accept" || a.code === "start")
                    submit(a.code, { expected_version: ticket.version });
                  else {
                    mutation.clearFeedback();
                    setForm(a.code as FormAction);
                  }
                }}
              >
                {a.code === "accept" && !ticket.assignee_id
                  ? "Взять в работу"
                  : actionLabels[a.code]}
              </button>
              {a.reason && <p id={`reason-${a.code}`}>{a.reason}</p>}
            </div>
          ))}
        </div>
        {!actions.length && (
          <p>Сейчас нет доступных действий. Доступна история заявки.</p>
        )}
        {mutation.saving && (
          <p role="status">Сохраняем действие и проверяем актуальные данные…</p>
        )}
        {mutation.message && (
          <p role="status" className="refresh-notice">
            {mutation.message}
          </p>
        )}
        {Boolean(mutation.error) && (
          <div role="alert">
            <p>{safeError(mutation.error, true)}</p>
            {mutation.canRetry && (
              <button
                className="ticket-button secondary"
                onClick={mutation.retry}
              >
                Повторить сохранение
              </button>
            )}
          </div>
        )}
      </section>
      <div className="ticket-detail-grid">
        <div>
          <section className="ticket-panel">
            <h2>О заявке</h2>
            <dl>
              <Info label="Исполнитель">
                {ticket.assignee_name ??
                  (ticket.assignee_id ? "Исполнитель назначен" : "Не назначен")}
              </Info>
              {ticket.requires_reassignment && (
                <Info label="Назначение">
                  Требуется назначить доступного исполнителя
                </Info>
              )}
              <Info label="Дом">{house?.address ?? "Адрес не указан"}</Info>
              <Info label="Категория">{categoryLabel(incident.category)}</Info>
              {incident.location && (
                <Info label="Место">
                  {[
                    incident.location.entrance &&
                      `Подъезд ${incident.location.entrance}`,
                    incident.location.floor &&
                      `Этаж ${incident.location.floor}`,
                    incident.location.label,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </Info>
              )}
              <Info label="Сообщений">{incident.report_count}</Info>
              <Info label="Участников">
                {incident.participant_count ?? "Нет данных"}
              </Info>
              <Info label="Создана">{formatDate(ticket.created_at)}</Info>
              <Info label="Обновлена">{formatDate(ticket.updated_at)}</Info>
            </dl>
            <p className="full-text">{incident.description}</p>
            {incident.is_demo && (
              <span className="demo-badge">Демонстрационные данные</span>
            )}
          </section>
          <TicketDeadlines deadlines={ticket.deadlines} />
          {ticket.observation_conflict && (
            <p className="refresh-notice">
              Наблюдения расходятся. Результат требует повторной проверки;
              большинство не определяет решение.
            </p>
          )}
          <AttemptHistory
            key={`attempts:${ticket.version}:${revision}:${historyRevision}`}
            client={client}
            ticket={ticket}
          />
        </div>
        <section className="ticket-panel">
          <h2>История заявки</h2>
          <EventHistory
            key={`events:${ticket.version}:${revision}:${historyRevision}`}
            client={client}
            id={id}
          />
        </section>
      </div>
      {form && (
        <ActionDialog
          key={form}
          action={form}
          client={client}
          ticket={ticket}
          busy={mutation.saving}
          blocked={
            blocked || !actions.some((a) => a.code === form && a.enabled)
          }
          error={mutation.error}
          message={mutation.message}
          retry={mutation.canRetry ? mutation.retry : undefined}
          close={() => setForm(null)}
          submit={(payload) => submit(form, payload)}
        />
      )}
    </>
  );
}
function Info({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="info-row">
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}
function AttemptHistory({
  client,
  ticket,
}: {
  client: TicketClient;
  ticket: Ticket;
}) {
  const [offset, setOffset] = useState(0);
  const load = useCallback(
    (signal: AbortSignal) => client.attempts(ticket.id, offset, signal),
    [client, ticket.id, offset],
  );
  const resource = useResource(`${ticket.id}:${offset}`, load);
  return (
    <section className="ticket-panel">
      <h2>Выполненные работы</h2>
      {!resource.data ? (
        <TicketState
          loading={resource.loading}
          error={resource.error}
          retry={resource.refresh}
        />
      ) : (
        <>
          {Boolean(resource.error) && (
            <TicketState error={resource.error} retry={resource.refresh} />
          )}
          {!resource.data.items.length && (
            <p className="muted">Исполнитель ещё не сообщил о выполнении.</p>
          )}
          {resource.data.items.map((a) => (
            <WorkAttemptCard
              key={a.id}
              attempt={a}
              current={a.id === ticket.latest_attempt?.id}
            />
          ))}
          <Pagination
            page={resource.data.page}
            count={resource.data.items.length}
            change={setOffset}
            busy={resource.loading}
            label="Страницы выполненных работ"
          />
        </>
      )}
    </section>
  );
}
function EventHistory({ client, id }: { client: TicketClient; id: string }) {
  const [offset, setOffset] = useState(0);
  const load = useCallback(
    (signal: AbortSignal) => client.events(id, offset, signal),
    [client, id, offset],
  );
  const resource = useResource(`${id}:${offset}`, load);
  return !resource.data ? (
    <TicketState
      loading={resource.loading}
      error={resource.error}
      retry={resource.refresh}
    />
  ) : (
    <>
      {Boolean(resource.error) && (
        <TicketState error={resource.error} retry={resource.refresh} />
      )}
      <TicketTimeline events={resource.data.items} />
      <Pagination
        page={resource.data.page}
        count={resource.data.items.length}
        change={setOffset}
        busy={resource.loading}
        label="Страницы истории"
      />
    </>
  );
}
function ActionDialog({
  action,
  client,
  ticket,
  busy,
  blocked,
  error,
  message,
  retry,
  close,
  submit,
}: {
  action: FormAction;
  client: TicketClient;
  ticket: Ticket;
  busy: boolean;
  blocked: boolean;
  error: unknown;
  message: string;
  retry?: () => void;
  close: () => void;
  submit: (payload: TicketCommand) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [text, setText] = useState("");
  const [assignee, setAssignee] = useState("");
  const load = useCallback(
    async (signal: AbortSignal) => {
      if (action !== "assign") return [];
      const items: components["schemas"]["AssigneeView"][] = [];
      let offset = 0;
      for (;;) {
        const result = await client.assignees(ticket.id, offset, signal);
        items.push(...result.items);
        offset += result.items.length;
        if (offset >= result.page.total || !result.items.length) break;
      }
      return items;
    },
    [action, client, ticket.id],
  );
  const candidates = useResource(`${ticket.id}:${action}`, load);
  useEffect(() => {
    const trigger = document.activeElement as HTMLElement | null;
    const element = dialog.current;
    element?.showModal();
    return () => {
      element?.close();
      trigger?.focus();
    };
  }, []);
  const work = action === "work-attempts";
  const field = work ? "public_description" : "reason";
  const fieldError =
    error instanceof ApiProblem &&
    error.problem.field_errors?.some(
      (e) => e.field === field || e.field.endsWith(`.${field}`),
    );
  const assigneeError =
    error instanceof ApiProblem &&
    error.problem.field_errors?.some(
      (e) => e.field === "assignee_id" || e.field.endsWith(".assignee_id"),
    );
  return (
    <dialog
      ref={dialog}
      className="ticket-dialog"
      aria-labelledby="dialog-title"
      onCancel={(e) => {
        e.preventDefault();
        if (!busy) close();
      }}
      onKeyDown={(event) => {
        if (event.key !== "Tab") return;
        const controls = [
          ...event.currentTarget.querySelectorAll<HTMLElement>(
            "button:not(:disabled), select:not(:disabled), textarea:not(:disabled), input:not(:disabled), a[href]",
          ),
        ];
        const first = controls[0];
        const last = controls.at(-1);
        if (!first) {
          event.preventDefault();
          return;
        }
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        }
        if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }}
    >
      <form
        className="ticket-form"
        onSubmit={(e) => {
          e.preventDefault();
          if (blocked) return;
          const payload = { expected_version: ticket.version };
          if (work) submit({ ...payload, public_description: text });
          else if (action === "assign") {
            if (
              assignee !== "unassigned" &&
              !candidates.data?.some((c) => c.user_id === assignee)
            )
              return;
            submit({
              ...payload,
              assignee_id: assignee === "unassigned" ? null : assignee,
              reason: text,
            });
          } else submit({ ...payload, reason: text });
        }}
      >
        <h2 id="dialog-title">{actionLabels[action]}</h2>
        {action === "assign" &&
          (!candidates.data ? (
            <TicketState
              loading={candidates.loading}
              error={candidates.error}
              retry={candidates.refresh}
            />
          ) : (
            <label>
              Исполнитель
              <select
                required
                value={assignee}
                disabled={busy}
                aria-invalid={Boolean(assigneeError)}
                aria-describedby={
                  assigneeError ? "assignee-field-error" : undefined
                }
                onChange={(e) => setAssignee(e.target.value)}
              >
                <option value="" disabled>
                  Выберите сотрудника
                </option>
                <option value="unassigned">
                  Вернуть в очередь без исполнителя
                </option>
                {candidates.data.map((c) => (
                  <option key={c.user_id} value={c.user_id}>
                    {c.display_name}
                  </option>
                ))}
              </select>
              {assigneeError && (
                <span id="assignee-field-error" role="alert">
                  Выберите сотрудника из доступного списка.
                </span>
              )}
            </label>
          ))}
        <label>
          {work ? "Что было сделано?" : "Причина"}
          <textarea
            autoFocus
            required
            minLength={work ? 5 : 3}
            maxLength={2000}
            rows={5}
            value={text}
            disabled={busy}
            aria-invalid={Boolean(fieldError)}
            aria-describedby={fieldError ? "command-field-error" : undefined}
            onChange={(e) => setText(e.target.value)}
          />
        </label>
        {fieldError && (
          <p id="command-field-error" role="alert">
            Введите {work ? "описание выполненной работы от 5" : "причину от 3"}{" "}
            до 2000 символов.
          </p>
        )}
        {work && (
          <p>
            После отправки жители смогут проверить результат. Это описание будет
            видно жителям.
          </p>
        )}
        {Boolean(error) && <p role="alert">{safeError(error, true)}</p>}
        {message && <p role="status">{message}</p>}
        {busy && <p role="status">Сохраняем и обновляем данные…</p>}
        <div className="ticket-buttons">
          <button
            className="ticket-button"
            type="submit"
            disabled={
              blocked ||
              text.trim().length < (work ? 5 : 3) ||
              (action === "assign" && (!assignee || !candidates.data))
            }
          >
            {actionLabels[action]}
          </button>
          {retry && (
            <button
              className="ticket-button"
              type="button"
              disabled={busy}
              onClick={retry}
            >
              Повторить сохранение
            </button>
          )}
          <button
            className="ticket-button secondary"
            type="button"
            disabled={busy}
            onClick={close}
          >
            Закрыть
          </button>
        </div>
      </form>
    </dialog>
  );
}
