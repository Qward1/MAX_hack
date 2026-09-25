import type { Attempt, PageMeta, TicketEvent, WorkStatus } from "../../shared/api/tickets";
import { problemStatus, retryable } from "../../shared/api/client";
import { Button } from "../../shared/ui/Button";
import { countLabel, formatStaffTime, formatWhen } from "../../shared/ui/format";
import { StatusTag } from "../../shared/ui/semantic";
import { residentTicketStatus, staffTicketStatus, statusOf } from "../../shared/ui/status";
import { eventLabels, ticketStatus } from "./presentation";
import { safeError } from "./useTicketMutation";

export function TicketStatusBadge({ status, resident = false }: { status: string | null; resident?: boolean }) {
  return <StatusTag entry={statusOf(resident ? residentTicketStatus : staffTicketStatus, status)} />;
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
        <p className="ds-subtle">
          Подтвердили: {countLabel(resolved, ["житель", "жителя", "жителей"])}. Сообщили, что проблема осталась:{" "}
          {countLabel(unresolved, ["житель", "жителя", "жителей"])}. Большинство не определяет результат.
        </p>
      )}
    </div>
  );
}

export function WorkAttemptCard({ attempt, current }: { attempt: Attempt; current: boolean }) {
  return (
    <article className={`work-attempt ${current ? "current-attempt" : "historical-attempt"}`}>
      <div className="ticket-line">
        <h3>Попытка №{attempt.number}</h3>
        <span className="ds-meta">{current ? "Последняя работа" : "История"}</span>
      </div>
      <time dateTime={attempt.created_at}>{formatStaffTime(attempt.created_at)}</time>
      <p>Исполнитель: {attempt.performer_name ?? "имя не указано"}</p>
      <p className="ds-prose">{attempt.public_description}</p>
      <ObservationSummary
        resolved={attempt.resolved_count ?? 0}
        unresolved={attempt.unresolved_count ?? 0}
        rework={attempt.rework_required}
      />
    </article>
  );
}

const creationReasons: Record<string, string> = {
  single_responsible: "Назначен ответственный за дом",
  multiple_responsibles: "В общей очереди дома",
  no_responsible: "Ответственный за дом не назначен",
  unknown_category: "Требуется уточнить категорию",
};

export function TicketTimeline({ events }: { events: TicketEvent[] }) {
  return (
    <ol className="ds-timeline">
      {events.map((event) => (
        <li key={event.id}>
          <p className="ds-strong">
            {event.kind === "assigned" && event.reason === "employee_revoked"
              ? "Исполнитель снят с заявки"
              : (eventLabels[event.kind] ?? "Заявка обновлена")}
          </p>
          <p className="ds-meta">
            <time dateTime={event.created_at}>{formatStaffTime(event.created_at)}</time>
            {event.to_status && ` · ${ticketStatus(event.to_status)}`}
          </p>
          {event.reason && (
            <p className="ds-prose">
              {event.kind === "created"
                ? (creationReasons[event.reason] ?? "Заявка создана")
                : event.reason === "employee_revoked"
                  ? "Доступ сотрудника к УК отозван. История работы сохранена."
                  : event.reason}
            </p>
          )}
        </li>
      ))}
    </ol>
  );
}

export function TicketDeadlines({ deadlines, resident = false }: { deadlines: WorkStatus["deadlines"]; resident?: boolean }) {
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
  const when = resident ? formatWhen : formatStaffTime;
  if (!deadlines.length) return null;
  return (
    <section className="ds-group" aria-label="Сроки">
      <h3>Сроки</h3>
      <dl className="ds-kv">
        {deadlines.map((d) => (
          <div className="ds-kv-row" key={`${d.kind}-${d.basis}`}>
            <dt>{kinds[d.kind] ?? "Срок"}</dt>
            <dd>
              <p>{when(d.due_at) ?? "Не определён"}</p>
              <p className="ds-meta">
                {bases[d.basis] ?? "Основание не указано"}
                {d.rule_source ? `: ${d.rule_source}${d.rule_version ? `, ${d.rule_version}` : ""}` : ""}
              </p>
              {!resident && (
                <p className="ds-meta">
                  Отсчёт: {formatStaffTime(d.started_at)} · редакция {d.revision}
                </p>
              )}
              {d.agreement_recorded && <p className="ds-meta">Согласование зафиксировано сотрудником.</p>}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

/** Загрузка, ошибка с «Повторить», истёкшая сессия — без технических деталей. */
export function TicketState({
  loading = false,
  error,
  retry,
  resident = false,
}: {
  loading?: boolean;
  error?: unknown;
  retry?: () => void;
  resident?: boolean;
}) {
  return (
    <div className={`ds-state ${loading ? "ds-state-loading" : "ds-state-error"}`} aria-busy={loading}>
      <p role={loading ? "status" : "alert"}>{loading ? "Загружаем актуальные данные…" : safeError(error, false, resident)}</p>
      {loading && (
        <div className="ds-skeleton" aria-hidden="true">
          <span />
        </div>
      )}
      {!loading && retry && retryable(error) && (
        <div className="ds-actions">
          <Button onClick={retry}>Повторить</Button>
        </div>
      )}
      {!loading && problemStatus(error) === 401 && !resident && (
        <div className="ds-actions">
          <Button variant="primary" onClick={() => window.location.reload()}>
            Войти снова
          </Button>
        </div>
      )}
    </div>
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
      <Button small disabled={busy || page.offset === 0} onClick={() => change(Math.max(0, page.offset - page.limit))}>
        Предыдущие
      </Button>
      <span className="ds-meta">
        {count ? `${page.offset + 1}–${page.offset + count}` : 0} из {page.total}
      </span>
      <Button small disabled={busy || page.offset + count >= page.total} onClick={() => change(page.offset + page.limit)}>
        Следующие
      </Button>
    </nav>
  );
}
