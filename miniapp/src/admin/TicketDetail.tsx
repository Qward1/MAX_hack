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
import { categoryLabel } from "../features/incidents/presentation";
import { placeText } from "../features/incidents/IncidentCard";
import { countLabel, formatStaffTime } from "../shared/ui/format";
import { staffTicketNext, staffTicketStatus, statusOf } from "../shared/ui/status";
import {
  Pagination,
  TicketDeadlines,
  TicketState,
  TicketStatusBadge,
  TicketTimeline,
  WorkAttemptCard,
} from "../features/tickets/components";
import { actionLabel, ticketActions } from "../features/tickets/presentation";
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
/** Работа вперёд — основное действие шага, если оно доступно роли. */
const FORWARD = ["accept", "start", "work-attempts", "resume"];
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
  backHref = adminUrl(),
  inPanel = false,
}: {
  client: TicketClient;
  id: string;
  me: Me;
  revision: number;
  navigate: (url: string) => void;
  /** Очередь с теми же фильтрами, откуда открыли заявку. */
  backHref?: string;
  /** Заявка открыта рядом со списком. */
  inPanel?: boolean;
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
      href={backHref}
      onClick={(e) => {
        e.preventDefault();
        navigate(backHref);
      }}
    >
      {inPanel ? "← К заявкам (закрыть)" : "← К заявкам"}
    </a>
  );
  if (!data)
    return (
      <>
        <div className="detail-back">{back}</div>
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
  const entry = statusOf(staffTicketStatus, ticket.status);
  // Новая заявка с исполнителем ждёт, когда он её примет, а не назначения.
  const next = staffTicketNext(ticket.status, Boolean(ticket.assignee_id)) ?? entry.next;
  const label = (code: string) => actionLabel(code, ticket);
  const place = placeText(incident.location);
  // Одно основное действие для текущего этапа: движение работы вперёд, а
  // если его нет — назначение, пока исполнителя нет или его нужно заменить.
  // Указанный исполнитель меняется среди других действий, первым из них.
  // Отмена — отдельно, как опасная. Права и статусы решает сервер.
  const cancel = actions.find((a) => a.code === "cancel");
  const assignFirst = !ticket.assignee_id || ticket.requires_reassignment;
  const order = assignFirst ? [...FORWARD, "assign"] : FORWARD;
  const primary =
    order.map((code) => actions.find((a) => a.code === code && a.enabled)).find(Boolean) ??
    order.map((code) => actions.find((a) => a.code === code)).find(Boolean);
  const secondary = actions
    .filter((a) => a !== primary && a !== cancel)
    .sort((a, b) => Number(b.code === "assign") - Number(a.code === "assign"));
  // Функция разметки, а не компонент: кнопки не пересоздаются при обновлении данных и не теряют фокус.
  const actionButton = (
    a: (typeof actions)[number],
    variant: "primary" | "secondary" | "danger",
  ) => (
    <div className="ds-action" key={a.code}>
      <button
        className={`ds-btn ds-btn-${variant}`}
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
        {label(a.code)}
      </button>
      {a.reason && (
        <p id={`reason-${a.code}`} className="ds-reason">
          {a.reason}
        </p>
      )}
    </div>
  );
  return (
    <>
      <div className="detail-back">{back}</div>
      <header className="page-header">
        <p className="ds-meta">
          Заявка {ticket.internal_number} · {house?.address ?? "адрес не указан"}
        </p>
        <h1 id="page-title" tabIndex={-1}>
          {incident.title || categoryLabel(incident.category)}
        </h1>
        <div className="ds-status-line">
          <TicketStatusBadge status={ticket.status} />
          {next && <span className="ds-subtle">{next}</span>}
        </div>
        <p className="ticket-assignee">
          <span className="ds-subtle">Исполнитель: </span>
          {ticket.assignee_name ??
            (ticket.assignee_id ? "назначен" : "не назначен")}
          {ticket.requires_reassignment && (
            <span className="ds-subtle"> · нужно назначить доступного</span>
          )}
        </p>
      </header>
      {resource.loading && <p role="status">Обновляем заявку…</p>}
      {Boolean(resource.error) && (
        <TicketState error={resource.error} retry={resource.refresh} />
      )}
      {resource.stale && (
        <div className="refresh-notice" role="status">
          <span>Данные могли измениться. Обновите заявку перед действием.</span>
          <button
            className="ds-btn ds-btn-secondary ds-btn-small"
            onClick={resource.refresh}
            disabled={mutation.saving}
          >
            Обновить заявку
          </button>
        </div>
      )}
      <section
        className="ticket-panel decision-panel"
        aria-labelledby="ticket-actions-title"
        aria-busy={mutation.saving}
      >
        <h2 id="ticket-actions-title">Действия по заявке</h2>
        {primary && (
          <div className="ticket-primary">
            {actionButton(primary, "primary")}
          </div>
        )}
        {secondary.length > 0 && (
          <div className="ticket-more" role="group" aria-labelledby="ticket-more-title">
            <p className="ds-meta" id="ticket-more-title">
              {primary ? "Другие действия" : "Доступные действия"}
            </p>
            <div className="ticket-buttons">
              {secondary.map((a) => actionButton(a, "secondary"))}
            </div>
          </div>
        )}
        {cancel && (
          <div className="ticket-danger-zone">
            {actionButton(cancel, "danger")}
            <p className="ds-reason">
              Заявка получит статус «Отменена» — его увидят жители. Перед отменой нужна причина.
            </p>
          </div>
        )}
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
                className="ds-btn ds-btn-secondary"
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
            <p className="ds-prose">{incident.description}</p>
            <dl className="ds-kv">
              <Info label="Исполнитель">
                {ticket.assignee_name ??
                  (ticket.assignee_id ? "Исполнитель назначен" : "Не назначен")}
              </Info>
              {ticket.requires_reassignment && (
                <Info label="Назначение">
                  Требуется назначить доступного исполнителя
                </Info>
              )}
              <Info label="Категория">{categoryLabel(incident.category)}</Info>
              {place && <Info label="Место">{place}</Info>}
              <Info label="Сообщили">
                {incident.participant_count !== null
                  ? countLabel(incident.participant_count, ["житель", "жителя", "жителей"])
                  : "Нет данных"}
                {`, ${countLabel(incident.report_count, ["сообщение", "сообщения", "сообщений"])}`}
              </Info>
              <Info label="Создана">{formatStaffTime(ticket.created_at)}</Info>
              <Info label="Обновлена">{formatStaffTime(ticket.updated_at)}</Info>
            </dl>
            {incident.is_demo && (
              <span className="demo-badge">Пример данных</span>
            )}
          </section>
          <TicketDeadlines deadlines={ticket.deadlines} />
          {ticket.observation_conflict && (
            <p className="ds-notice ds-tone-warning">
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
        <h2 id="dialog-title">{actionLabel(action, ticket)}</h2>
        {action === "cancel" && (
          <p className="ds-notice ds-tone-danger">
            Заявка получит статус «Отменена» — его увидят жители.
          </p>
        )}
        {action === "assign" &&
          (!candidates.data ? (
            <TicketState
              loading={candidates.loading}
              error={candidates.error}
              retry={candidates.refresh}
            />
          ) : (
            <AssigneePicker
              candidates={candidates.data}
              current={ticket.assignee_id}
              currentName={ticket.assignee_name}
              value={assignee}
              disabled={busy}
              error={Boolean(assigneeError)}
              onChange={setAssignee}
            />
          ))}
        <label>
          {work ? "Что было сделано?" : "Причина"}
          <span className="ds-hint">
            {work
              ? "Обязательно, от 5 символов. Это описание увидят жители."
              : "Обязательно, от 3 символов. Попадёт в историю заявки."}
          </span>
          <textarea
            autoFocus={action !== "assign"}
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
            className={`ds-btn ${action === "cancel" ? "ds-btn-destructive" : "ds-btn-primary"}`}
            type="submit"
            disabled={
              blocked ||
              text.trim().length < (work ? 5 : 3) ||
              (action === "assign" && (!assignee || !candidates.data))
            }
          >
            {actionLabel(action, ticket)}
          </button>
          {retry && (
            <button
              className="ds-btn ds-btn-primary"
              type="button"
              disabled={busy}
              onClick={retry}
            >
              Повторить сохранение
            </button>
          )}
          <button
            className="ds-btn ds-btn-secondary"
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

/**
 * Выбор исполнителя: список переключателей, а не скрытый select. Текущее
 * назначение видно сразу; при длинном списке появляется поиск по имени.
 * «Без исполнителя» — явный вариант возврата в общую очередь.
 */
function AssigneePicker({
  candidates,
  current,
  currentName,
  value,
  disabled,
  error,
  onChange,
}: {
  candidates: components["schemas"]["AssigneeView"][];
  current: string | null;
  currentName?: string | null;
  value: string;
  disabled: boolean;
  error: boolean;
  onChange: (value: string) => void;
}) {
  const [query, setQuery] = useState("");
  const search = candidates.length > 6;
  const needle = query.trim().toLowerCase();
  const shown = candidates.filter(
    (c) => !needle || c.display_name.toLowerCase().includes(needle),
  );
  return (
    <fieldset
      className="assignee-picker"
      aria-invalid={error || undefined}
      aria-describedby={error ? "assignee-field-error" : "assignee-current"}
    >
      <legend>Исполнитель</legend>
      <p id="assignee-current" className="ds-hint">
        Сейчас: {currentName ?? (current ? "исполнитель назначен" : "без исполнителя")}
      </p>
      {search && (
        <label className="ds-field">
          Найти сотрудника
          <input
            type="search"
            value={query}
            disabled={disabled}
            data-sheet-focus
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
      )}
      <div className="ds-choice-list assignee-options">
        {shown.map((c) => (
          <label key={c.user_id} className="ds-choice-row">
            <input
              type="radio"
              name="assignee"
              value={c.user_id}
              checked={value === c.user_id}
              disabled={disabled}
              required
              onChange={() => onChange(c.user_id)}
            />
            <span className="ds-choice-text">
              <span>{c.display_name}</span>
              {c.user_id === current && (
                <span className="ds-hint">назначен сейчас</span>
              )}
            </span>
          </label>
        ))}
        {!shown.length && (
          <p className="ds-hint">Никого не нашли. Измените запрос.</p>
        )}
        <label className="ds-choice-row">
          <input
            type="radio"
            name="assignee"
            value="unassigned"
            checked={value === "unassigned"}
            disabled={disabled}
            onChange={() => onChange("unassigned")}
          />
          <span className="ds-choice-text">
            <span>Без исполнителя</span>
            <span className="ds-hint">Вернуть заявку в общую очередь дома</span>
          </span>
        </label>
      </div>
      {error && (
        <p id="assignee-field-error" role="alert" className="ds-error">
          Выберите сотрудника из доступного списка.
        </p>
      )}
    </fieldset>
  );
}
