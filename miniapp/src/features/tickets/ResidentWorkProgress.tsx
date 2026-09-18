import { useCallback } from "react";
import type {
  Observation,
  ResidentTicketApi,
  WorkStatus,
} from "../../shared/api/tickets";
import { useResource } from "../../shared/api/useResource";
import { formatDate } from "../incidents/presentation";
import { TicketDeadlines, TicketState, TicketStatusBadge } from "./components";
import { ticketActions } from "./presentation";
import { safeError, useTicketMutation } from "./useTicketMutation";

export const staleAttemptMessage =
  "Работа по этой проблеме уже обновилась. Показываем актуальный результат.";
export function ResidentWorkProgress({
  client,
  incidentId,
  revision,
  parentBusy = false,
}: {
  client: ResidentTicketApi;
  incidentId: string;
  revision?: number;
  parentBusy?: boolean;
}) {
  const load = useCallback(
    (signal: AbortSignal) => client.workStatus(incidentId, signal),
    [client, incidentId],
  );
  const resource = useResource(`${incidentId}:${revision}`, load);
  const mutation = useTicketMutation<Observation, WorkStatus>();
  const data = resource.data;
  if (!data)
    return (
      <section className="ticket-panel">
        <h2>Ход решения</h2>
        <TicketState
          loading={resource.loading}
          error={resource.error}
          retry={resource.refresh}
        />
      </section>
    );
  if (!data.ticket_id) return null;
  const attempt = data.latest_attempt;
  const action = ticketActions(data.allowed_actions).find(
    (a) => a.code === "observe_result",
  );
  const blocked =
    parentBusy ||
    resource.loading ||
    resource.stale ||
    Boolean(resource.error) ||
    mutation.saving ||
    mutation.uncertain;
  function observe(outcome: "resolved" | "unresolved") {
    if (!attempt || !action?.enabled || blocked) return;
    mutation.run({
      write: (key) => client.observe(attempt.id, { outcome }, key),
      read: resource.reload,
      success: (result, current) => {
        if (
          !result.applied_to_current ||
          current.latest_attempt?.id !== result.target_attempt_id
        )
          return staleAttemptMessage;
        if (current.my_latest_observation?.id !== result.observation.id)
          return "Ответ сохранён. Показаны актуальные данные.";
        return outcome === "resolved"
          ? "Вы подтвердили, что после последней работы проблема устранена."
          : current.status === "in_progress"
            ? "Проблема возвращена в работу."
            : "Ваше наблюдение сохранено.";
      },
      conflict: () => staleAttemptMessage,
    });
  }
  return (
    <section
      className="ticket-panel resident-work"
      aria-labelledby="work-progress-title"
      aria-busy={mutation.saving}
    >
      <div className="ticket-line">
        <h2 id="work-progress-title">Ход решения</h2>
        <span className="muted">{data.internal_number}</span>
      </div>
      <TicketStatusBadge status={data.status} resident />
      {(resource.stale || Boolean(resource.error)) && (
        <div className="refresh-notice" role="status">
          {resource.error
            ? "Не удалось обновить ход решения."
            : "Данные могли измениться."}
          <button
            className="ticket-button secondary"
            onClick={resource.refresh}
            disabled={mutation.saving}
          >
            Обновить ход решения
          </button>
        </div>
      )}
      {resource.loading && <p role="status">Обновляем ход решения…</p>}
      {data.observation_conflict && (
        <p className="observation-summary">
          Результат требует повторной проверки. Наблюдения жителей расходятся.
        </p>
      )}
      {attempt && (
        <article className="work-attempt current-attempt">
          <h3>Исполнитель сообщил о выполнении</h3>
          <p className="muted">
            Попытка №{attempt.number} ·{" "}
            <time dateTime={attempt.created_at}>
              {formatDate(attempt.created_at)}
            </time>
          </p>
          <strong>Что сделано</strong>
          <p className="full-text">{attempt.public_description}</p>
          {attempt.rework_required && (
            <p>
              После этой работы поступило сообщение, что проблема осталась.
              Ожидается новый результат.
            </p>
          )}
          {data.my_latest_observation && (
            <p className="own-observation">
              Ваш последний ответ:{" "}
              {data.my_latest_observation.outcome === "resolved"
                ? "исправлено"
                : "проблема осталась"}
              .
            </p>
          )}
          {action && (
            <div className="ticket-form">
              <strong>Проверьте результат</strong>
              <div className="ticket-buttons">
                <button
                  className="ticket-button"
                  disabled={blocked || !action.enabled}
                  onClick={() => observe("resolved")}
                >
                  Исправлено
                </button>
                <button
                  className="ticket-button secondary"
                  disabled={blocked || !action.enabled}
                  onClick={() => observe("unresolved")}
                >
                  Проблема осталась
                </button>
              </div>
              {action.reason && <p>{action.reason}</p>}
              <p className="muted">Это ваше наблюдение о результате работ.</p>
            </div>
          )}
        </article>
      )}
      {mutation.saving && (
        <p role="status">Сохраняем ответ и проверяем актуальные данные…</p>
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
      <TicketDeadlines deadlines={data.deadlines} />
      <p className="muted">
        Обновлено: {formatDate(data.updated_at) ?? "Нет данных"}
      </p>
    </section>
  );
}
