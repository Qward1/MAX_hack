import { type ReactNode, useCallback, useEffect, useId } from "react";
import type { Observation, ResidentTicketApi, WorkStatus } from "../../shared/api/tickets";
import { useResource } from "../../shared/api/useResource";
import { maxBridge } from "../../shared/max/bridge";
import { Button } from "../../shared/ui/Button";
import { countLabel, formatWhen } from "../../shared/ui/format";
import { Notice, type ProgressStep, ProgressSteps, StatusTag } from "../../shared/ui/semantic";
import { residentTicketStatus, statusOf } from "../../shared/ui/status";
import { TicketDeadlines, TicketState } from "./components";
import { ticketActions } from "./presentation";
import { safeError, useTicketMutation } from "./useTicketMutation";

export const staleAttemptMessage = "Работа по этой проблеме уже обновилась. Показываем актуальный результат.";
export const NO_TICKET_NOTE = "Заявки в управляющую компанию по этой проблеме пока нет.";

/** Этап работы по статусу заявки: какой шаг процесса сейчас. */
const WORK_STAGE: Record<string, 2 | 3 | 4 | 5> = {
  new: 2,
  accepted: 3,
  in_progress: 3,
  needs_clarification: 3,
  waiting_external: 3,
  verification_pending: 4,
  closed: 5,
};

/**
 * Шаги от сообщения к результату. «Готово» и «сейчас» — только по статусу
 * заявки из API; «впереди» — порядок работы продукта, а не случившееся событие.
 * Отменённая или незнакомая заявка — без будущих шагов.
 */
function progressSteps(
  number: string | null,
  status: string | null,
  current: ReactNode,
  reported?: { people: number | null; messages: number },
): ProgressStep[] {
  const stage = WORK_STAGE[status ?? ""];
  const state = (step: number): ProgressStep["state"] =>
    stage === undefined ? (step === 2 ? "current" : "done") : step < stage ? "done" : step === stage ? "current" : "upcoming";
  const board: ProgressStep = {
    title: "Проблема на доске дома",
    state: "done",
    detail: reported ? (
      <p className="ds-meta">
        {reported.people !== null
          ? `Сообщили: ${countLabel(reported.people, ["житель", "жителя", "жителей"])}, `
          : "Сообщений: "}
        {reported.people !== null
          ? countLabel(reported.messages, ["сообщение", "сообщения", "сообщений"])
          : reported.messages}
      </p>
    ) : undefined,
  };
  const ticket: ProgressStep = {
    title: number ? `Заявка ${number} в управляющей компании` : "Заявка в управляющей компании",
    state: state(2),
    detail: state(2) === "current" ? current : undefined,
  };
  if (stage === undefined) return [board, ticket];
  return [
    board,
    ticket,
    { title: "Работа исполнителя", state: state(3), detail: state(3) === "current" ? current : undefined },
    {
      title: "Проверка результата жителями",
      state: state(4),
      detail: stage >= 4 ? current : undefined,
    },
  ];
}

/**
 * «Что происходит» у проблемы дома: путь от сообщения до проверки результата,
 * статус заявки простыми словами у текущего шага, одна фраза «что дальше»,
 * последняя выполненная работа и проверка результата жителем. Отчёт
 * исполнителя не подтверждает результат — это делает житель.
 */
export function ResidentWorkProgress({
  client,
  incidentId,
  revision,
  parentBusy = false,
  launchAttempt = null,
  reported,
}: {
  client: ResidentTicketApi;
  incidentId: string;
  revision?: number;
  parentBusy?: boolean;
  launchAttempt?: string | null;
  /** Сколько жителей и сообщений у проблемы — для первого шага. */
  reported?: { people: number | null; messages: number };
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
  const now = (
    <>
      <div className="ds-status-line">
        <StatusTag entry={entry} />
      </div>
      {entry.next && <p className="ds-next">{entry.next}</p>}
    </>
  );
  return (
    <section className="ds-status-block resident-work" aria-labelledby={titleId} aria-busy={mutation.saving}>
      <h2 id={titleId}>Что происходит</h2>
      <ProgressSteps label="Путь от сообщения до результата" steps={progressSteps(data.internal_number, data.status, now, reported)} />
      {updated && <p className="ds-meta">Заявка обновлена {updated}</p>}
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
