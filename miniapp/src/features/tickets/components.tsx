import { formatDate } from "../incidents/presentation";
import type {
  Attempt,
  PageMeta,
  TicketEvent,
  WorkStatus,
} from "../../shared/api/tickets";
import { problemStatus, retryable } from "../../shared/api/client";
import { eventLabels, ticketStatus } from "./presentation";
import { safeError } from "./useTicketMutation";

export function TicketStatusBadge({
  status,
  resident = false,
}: {
  status: string | null;
  resident?: boolean;
}) {
  const tone =
    status === "closed"
      ? "calm"
      : status === "verification_pending"
        ? "attention"
        : ["new", "accepted", "in_progress"].includes(status ?? "")
          ? "active"
          : "neutral";
  return (
    <span className={`status-badge tone-${tone}`}>
      {ticketStatus(status, resident)}
    </span>
  );
}
export function ObservationSummary({
  resolved,
  unresolved,
  rework,
}: {
  resolved: number;
  unresolved: number;
  rework: boolean;
}) {
  return (
    <div className="observation-summary">
      <strong>
        {resolved && unresolved
          ? "Наблюдения расходятся. Результат требует повторной проверки."
          : rework || unresolved
            ? "Есть возражение. Требуется повторная работа."
            : resolved
              ? "Есть подтверждение результата."
              : "Ожидается ответ жителей."}
      </strong>
      {(resolved > 0 || unresolved > 0) && (
        <p className="muted">
          Подтверждений: {resolved}. Сообщений о сохранившейся проблеме:{" "}
          {unresolved}. Это наблюдения жителей; большинство не определяет
          результат.
        </p>
      )}
    </div>
  );
}
export function WorkAttemptCard({
  attempt,
  current,
}: {
  attempt: Attempt;
  current: boolean;
}) {
  return (
    <article
      className={`work-attempt ${current ? "current-attempt" : "historical-attempt"}`}
    >
      <div className="ticket-line">
        <h3>Попытка №{attempt.number}</h3>
        <span className="muted">
          {current ? "Последняя работа" : "История"}
        </span>
      </div>
      <time dateTime={attempt.created_at}>
        {formatDate(attempt.created_at)}
      </time>
      <p>Исполнитель: {attempt.performer_name ?? "Имя не указано"}</p>
      <p className="full-text">{attempt.public_description}</p>
      <ObservationSummary
        resolved={attempt.resolved_count ?? 0}
        unresolved={attempt.unresolved_count ?? 0}
        rework={attempt.rework_required}
      />
    </article>
  );
}
export function TicketTimeline({ events }: { events: TicketEvent[] }) {
  return (
    <ol className="timeline">
      {events.map((event) => (
        <li key={event.id}>
          <strong>{eventLabels[event.kind] ?? "Заявка обновлена"}</strong>
          <time dateTime={event.created_at}>
            {formatDate(event.created_at)}
          </time>
          <span>{ticketStatus(event.to_status)}</span>
          {event.reason && (
            <p className="full-text">
              {event.kind === "created"
                ? ((
                    {
                      single_responsible: "Назначен ответственный за дом",
                      multiple_responsibles: "Передано в общую очередь дома",
                      no_responsible: "Ответственный за дом не назначен",
                      unknown_category: "Требуется уточнить категорию",
                    } as Record<string, string>
                  )[event.reason] ?? "Заявка передана в обработку")
                : event.reason}
            </p>
          )}
        </li>
      ))}
    </ol>
  );
}
export function TicketDeadlines({
  deadlines,
}: {
  deadlines: WorkStatus["deadlines"];
}) {
  const kinds: Record<string, string> = {
    response: "Ответ",
    completion: "Выполнение работы",
    next_update: "Следующее обновление",
  };
  const bases: Record<string, string> = {
    internal: "Внутренняя оценка",
    agreed: "Согласованный срок",
    normative: "Нормативный срок",
  };
  if (!deadlines.length) return null;
  return (
    <section className="ticket-panel">
      <h2>Сроки и обновления</h2>
      <dl>
        {deadlines.map((d) => (
          <div className="info-row" key={`${d.kind}-${d.basis}`}>
            <dt>{kinds[d.kind] ?? "Срок"}</dt>
            <dd>
              {formatDate(d.due_at) ?? "Не определён"}
              <p className="muted">
                {bases[d.basis] ?? "Основание не указано"}
              </p>
              <p>
                Отсчёт: {formatDate(d.started_at)} · редакция {d.revision}
              </p>
              {d.rule_source && (
                <p>
                  {d.rule_source}
                  {d.rule_version ? ` · ${d.rule_version}` : ""}
                </p>
              )}
              {d.agreement_recorded && (
                <p>Согласование зафиксировано сотрудником.</p>
              )}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
export function TicketState({
  loading = false,
  error,
  retry,
}: {
  loading?: boolean;
  error?: unknown;
  retry?: () => void;
}) {
  return (
    <section className="state-panel" aria-busy={loading}>
      <p role={loading ? "status" : "alert"}>
        {loading ? "Загружаем актуальные данные…" : safeError(error)}
      </p>
      {!loading && retry && retryable(error) && (
        <button className="ticket-button secondary" onClick={retry}>
          Повторить загрузку
        </button>
      )}
      {!loading && problemStatus(error) === 401 && (
        <button
          className="ticket-button secondary"
          onClick={() => window.location.reload()}
        >
          Войти снова
        </button>
      )}
    </section>
  );
}
export function Pagination({
  page,
  count,
  change,
  busy = false,
  label,
}: {
  page: PageMeta;
  count: number;
  change: (offset: number) => void;
  busy?: boolean;
  label: string;
}) {
  if (page.total <= page.limit && page.offset === 0) return null;
  return (
    <nav className="pagination" aria-label={label}>
      <button
        className="ticket-button secondary"
        disabled={busy || page.offset === 0}
        onClick={() => change(Math.max(0, page.offset - page.limit))}
      >
        Предыдущие
      </button>
      <span>
        {count ? `${page.offset + 1}–${page.offset + count}` : 0} из{" "}
        {page.total}
      </span>
      <button
        className="ticket-button secondary"
        disabled={busy || page.offset + count >= page.total}
        onClick={() => change(page.offset + page.limit)}
      >
        Следующие
      </button>
    </nav>
  );
}
