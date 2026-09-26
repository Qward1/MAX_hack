import { useCallback, useEffect, useId } from "react";
import type { Observation, ResidentTicketApi, WorkStatus } from "../../shared/api/tickets";
import { useResource } from "../../shared/api/useResource";
import { maxBridge } from "../../shared/max/bridge";
import { Button } from "../../shared/ui/Button";
import { formatWhen } from "../../shared/ui/format";
import { Notice, StatusTag } from "../../shared/ui/semantic";
import { residentTicketStatus, statusOf } from "../../shared/ui/status";
import { TicketDeadlines, TicketState } from "./components";
import { ticketActions } from "./presentation";
import { safeError, useTicketMutation } from "./useTicketMutation";

export const staleAttemptMessage = "Работа по этой проблеме уже обновилась. Показываем актуальный результат.";
export const NO_TICKET_NOTE = "Заявки в управляющую компанию по этой проблеме пока нет.";

/**
 * «Что происходит» у проблемы дома: статус заявки простыми словами, одна
 * фраза «что дальше», последняя выполненная работа и проверка результата
 * жителем. Отчёт исполнителя не подтверждает результат — это делает житель.
 */
export function ResidentWorkProgress({
  client,
  incidentId,
  revision,
  parentBusy = false,
  launchAttempt = null,
}: {
  client: ResidentTicketApi;
  incidentId: string;
  revision?: number;
  parentBusy?: boolean;
  launchAttempt?: string | null;
}) {
  const titleId = useId();
  const load = useCallback((signal: AbortSignal) => client.workStatus(incidentId, signal), [client, incidentId]);
  const resource = useResource(`${incidentId}:${revision}`, load);
  const mutation = useTicketMutation<Observation, WorkStatus>();
  const data = resource.data;
  useEffect(() => {
    if (launchAttempt && data?.latest_attempt)
      document.getElementById("notification-work-attempt")?.focus({ preventScroll: false });
  }, [launchAttempt, data?.latest_attempt?.id]);
  if (!data)
    return (
      <section className="ds-status-block" aria-labelledby={titleId}>
        <h2 id={titleId}>Что происходит</h2>
        <TicketState loading={resource.loading} error={resource.error} retry={resource.refresh} resident />
      </section>
    );
  if (!data.ticket_id)
    return (
      <section className="ds-status-block" aria-labelledby={titleId}>
        <h2 id={titleId}>Что происходит</h2>
        <p className="ds-next">{NO_TICKET_NOTE}</p>
      </section>
    );
  const entry = statusOf(residentTicketStatus, data.status);
  const attempt = data.latest_attempt;
  const action = ticketActions(data.allowed_actions).find((a) => a.code === "observe_result");
  const blocked =
    parentBusy || resource.loading || resource.stale || Boolean(resource.error) || mutation.saving || mutation.uncertain;
  function observe(outcome: "resolved" | "unresolved") {
    if (!attempt || !action?.enabled || blocked) return;
    mutation.run({
      write: (key) => client.observe(attempt.id, { outcome }, key),
      read: resource.reload,
      success: (result, current) => {
        maxBridge.haptic("success");
        if (!result.applied_to_current || current.latest_attempt?.id !== result.target_attempt_id)
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
  const updated = formatWhen(data.updated_at);
  return (
    <section className="ds-status-block resident-work" aria-labelledby={titleId} aria-busy={mutation.saving}>
      <h2 id={titleId}>Что происходит</h2>
      <div className="ds-status-line">
        <StatusTag entry={entry} />
        {data.internal_number && <span className="ds-strong">Заявка {data.internal_number}</span>}
      </div>
      {entry.next && <p className="ds-next">{entry.next}</p>}
      {updated && <p className="ds-meta">Обновлено {updated}</p>}
      {(resource.stale || Boolean(resource.error)) && (
        <div className="refresh-notice" role="status">
          <span>{resource.error ? "Не удалось обновить ход работ." : "Данные могли измениться."}</span>
          <Button small onClick={resource.refresh} disabled={mutation.saving}>
            Обновить
          </Button>
        </div>
      )}
      {resource.loading && (
        <p role="status" className="ds-meta">
          Обновляем…
        </p>
      )}
      {data.observation_conflict && (
        <Notice tone="warning" role="note">
          <p>Результат требует повторной проверки: ответы жителей расходятся.</p>
        </Notice>
      )}
      {attempt && (
        <article className="work-attempt current-attempt" id="notification-work-attempt" tabIndex={-1}>
          {launchAttempt && (
            <p className="ds-meta">{launchAttempt === attempt.id ? "Результат из уведомления" : staleAttemptMessage}</p>
          )}
          <h3>Исполнитель сообщил о выполнении</h3>
          <p className="ds-meta">
            <time dateTime={attempt.created_at}>{formatWhen(attempt.created_at)}</time>
            {attempt.number > 1 && ` · попытка ${attempt.number}`}
          </p>
          <p className="ds-prose">{attempt.public_description}</p>
          {attempt.rework_required && (
            <p>После этой работы жители сообщили, что проблема осталась. Ожидается новый результат.</p>
          )}
          {data.my_latest_observation && (
            <p className="ds-strong">
              Ваш ответ: {data.my_latest_observation.outcome === "resolved" ? "исправлено" : "проблема осталась"}.
            </p>
          )}
          {action && (
            <fieldset className="ds-form">
              <legend>Проблема исправлена?</legend>
              <p className="ds-hint">
                Ответьте по тому, что видите сами. Ваш ответ увидит управляющая компания.
              </p>
              <div className="ds-actions">
                <Button
                  disabled={blocked || !action.enabled}
                  loading={mutation.saving}
                  loadingLabel="Сохраняем…"
                  onClick={() => observe("resolved")}
                >
                  Исправлено
                </Button>
                <Button disabled={blocked || !action.enabled} onClick={() => observe("unresolved")}>
                  Проблема осталась
                </Button>
              </div>
              {!action.enabled && action.reason && <p className="ds-reason">{action.reason}</p>}
            </fieldset>
          )}
        </article>
      )}
      {mutation.message && (
        <Notice tone="success" role="status">
          <p>{mutation.message}</p>
        </Notice>
      )}
      {Boolean(mutation.error) && (
        <Notice tone="danger" role="alert">
          <p>{safeError(mutation.error, true, true)}</p>
          {mutation.canRetry && <Button onClick={mutation.retry}>Повторить</Button>}
        </Notice>
      )}
      <TicketDeadlines deadlines={data.deadlines} resident />
    </section>
  );
}
