import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { ApiProblem, problemStatus } from "../shared/api/client";
import type {
  SignalActionCode,
  SignalClient,
  SignalCommand,
  SignalMutation,
  SignalView,
} from "../shared/api/signals";
import { useResource } from "../shared/api/useResource";
import { formatStaffTime } from "../shared/ui/format";
import { StatusTag } from "../shared/ui/semantic";
import { signalStatus, signalStrength, statusOf } from "../shared/ui/status";
import { useTicketMutation } from "../features/tickets/useTicketMutation";
import { verificationNotes } from "../features/routing/presentation";
import {
  SignalState,
  signalError,
  usePolling,
} from "./SignalCommon";
import {
  categoryOptions,
  countsLine,
  dismissReasons,
  formatDay,
  knownSignalActions,
  label,
  routeBadgeLabels,
  routeChoiceLabels,
  shortTime,
  signalActionLabels,
  statusLabels,
  strengthLabels,
} from "./signalPresentation";

type Action = ReturnType<typeof knownSignalActions>[number];

const SUCCESS: Record<SignalActionCode, (view: SignalView) => string> = {
  "create-ticket": (view) =>
    `Заявка ${view.linked?.ticket_number ?? ""} создана и уже в разделе «Заявки».`.replace(
      "  ",
      " ",
    ),
  join: () => "Сигнал присоединён к проблеме. Второй заявки не появилось.",
  "route-external": () =>
    "Отмечен внешний маршрут. ДомСигнал никуда ничего не отправлял.",
  "choose-route": () => "Маршрут выбран. Теперь примите решение по сигналу.",
  dismiss: () => "Сигнал закрыт. Причина сохранена.",
};

export function SignalDetail({
  client,
  id,
  backHref,
  nextHref = null,
  inPanel = false,
  navigate,
  openTicket,
  onDecided,
}: {
  client: SignalClient;
  id: string;
  backHref: string;
  /** Решение сохранено — очередь рядом перечитывается. */
  onDecided?: () => void;
  /** Следующий сигнал очереди — после решения к нему можно перейти сразу. */
  nextHref?: string | null;
  inPanel?: boolean;
  navigate: (href: string) => void;
  openTicket: (ticketId: string) => void;
}) {
  const load = useCallback((signal: AbortSignal) => client.signalDetail(id, signal), [client, id]);
  const resource = useResource(id, load);
  const mutation = useTicketMutation<SignalMutation, SignalView>();
  const [form, setForm] = useState<SignalActionCode | null>(null);
  const [decided, setDecided] = useState(false);
  // Пока открыта форма решения, карточка не перечитывается сама.
  usePolling(resource.refresh, form === null && !mutation.saving);
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
      {inPanel ? "← К сигналам (закрыть)" : "← К сигналам"}
    </a>
  );
  if (!data)
    return (
      <>
        <div className="detail-back">{back}</div>
        <SignalState loading={resource.loading} error={resource.error} retry={resource.refresh} />
      </>
    );
  const actions = knownSignalActions(data.allowed_actions);
  const blocked = resource.loading || Boolean(resource.error) || mutation.saving || mutation.uncertain;
  function submit(code: SignalActionCode, payload: SignalCommand) {
    if (blocked || !actions.some((a) => a.code === code && a.enabled)) return;
    mutation.run({
      write: (key) => client.decide(id, code, payload, key),
      read: () => resource.reload(),
      success: (_result, current) => {
        setForm(null);
        setDecided(true);
        onDecided?.();
        return SUCCESS[code](current);
      },
      conflict: (error) =>
        problemStatus(error) === 409
          ? "Сигнал уже изменился. Показаны актуальные данные — проверьте и примите решение снова."
          : signalError(error),
    });
  }
  const danger = data.danger;
  const safety = data.action_card.safety;
  const place = [
    data.place.entrance && `подъезд ${data.place.entrance.value}`,
    data.place.floor && `этаж ${data.place.floor.value}`,
  ]
    .filter(Boolean)
    .join(", ");
  return (
    <>
      <div className="detail-back">{back}</div>
      <header className="page-header">
        <div className="signal-badges">
          <StatusTag entry={statusOf(signalStrength, data.strength)} />
          <StatusTag entry={statusOf(signalStatus, data.status)} />
        </div>
        <h1 id="page-title" tabIndex={-1}>
          {data.subtype_label}
        </h1>
        <p className="ds-subtle">
          {data.house_address}
          {place && ` · ${place}`}
          {" · "}
          {countsLine(data.report_count, data.author_count, data.last_seen_at)}
        </p>
      </header>
      {resource.loading && (
        <p role="status" className="ds-meta">
          Обновляем сигнал…
        </p>
      )}
      {Boolean(resource.error) && <SignalState error={resource.error} retry={resource.refresh} />}

      {(danger || safety) && (
        <section className="ds-safety signal-danger" aria-labelledby="signal-danger-title">
          <h2 id="signal-danger-title">{danger ? `Опасность: ${danger.labels.join(", ")}` : "Памятка безопасности"}</h2>
          {danger && (
            <>
              <p>
                {danger.sources.includes("rules") && "Признак найден правилами ДомСигнала. "}
                {danger.sources.includes("semantic") && "Признак найден разбором переписки. "}
                {danger.preliminary && "Переписку ещё разбирают — сигнал предварительный."}
                {danger.displaced && " Жители пишут, что это не у нас или не сейчас: памятки в чат не было."}
                {danger.downgraded && " Опасность понижена: переписка её опровергла."}
              </p>
              {danger.evidence_unverified && <p>Цитаты разбора не прошли проверку — ниже сами сообщения жителей.</p>}
              {(danger.evidence ?? []).length > 0 && (
                <ul className="ds-bullets">
                  {(danger.evidence ?? []).map((item, index) => (
                    <li key={index}>
                      <span>«{item.text}»</span>
                      <span className="ds-meta">
                        {[item.label, item.author, shortTime(item.sent_at)].filter(Boolean).join(" · ")}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
          {safety && (
            <div className="signal-safety ds-stack">
              <h3>{safety.title}</h3>
              {(safety.lines ?? []).map((line) => (
                <p key={line}>{line}</p>
              ))}
              {safety.phone && (
                <a className="ds-call" href={`tel:${safety.phone}`}>
                  Позвонить {safety.phone}
                </a>
              )}
              {safety.source_title && (
                <p className="ds-meta">
                  Источник: {safety.source_title}
                  {safety.verified_at && `, проверено ${formatDay(safety.verified_at)}`}
                </p>
              )}
            </div>
          )}
        </section>
      )}

      <section
        className="ticket-panel decision-panel"
        aria-labelledby="signal-actions-title"
        aria-busy={mutation.saving}
      >
        <h2 id="signal-actions-title">Действия по сигналу</h2>
        <p className="ds-subtle">
          Маршрут: <strong>{label(routeBadgeLabels, data.action_card.route.route_type, "route_type")}</strong>
          {data.action_card.route.organization_name && ` — ${data.action_card.route.organization_name}`}. Основание —
          ниже.
        </p>
        {actions.length > 0 ? (
          <div className="ticket-buttons">
            {actions.map((action) => (
              <ActionButton
                key={action.code}
                action={action}
                blocked={blocked}
                primary={action === actions.find((a) => a.enabled)}
                onClick={() => {
                  mutation.clearFeedback();
                  setForm(action.code);
                }}
              />
            ))}
          </div>
        ) : (
          <p>Решение по сигналу уже принято. Ниже — кто и когда его принял.</p>
        )}
        <ContactActions data={data} />
        {form && (
          <DecisionForm
            key={form}
            code={form}
            data={data}
            blocked={blocked || !actions.some((a) => a.code === form && a.enabled)}
            busy={mutation.saving}
            error={mutation.error}
            close={() => setForm(null)}
            submit={(payload) => submit(form, payload)}
          />
        )}
        {mutation.saving && <p role="status">Сохраняем решение и проверяем актуальные данные…</p>}
        {mutation.message && (
          <div className="decision-done">
            <p role="status" className="ds-notice ds-tone-success">
              {mutation.message}
            </p>
            {decided && nextHref && (
              <div>
                <a
                  className="ds-btn ds-btn-primary"
                  href={nextHref}
                  onClick={(e) => {
                    e.preventDefault();
                    navigate(nextHref);
                  }}
                >
                  Открыть следующий сигнал
                </a>
              </div>
            )}
          </div>
        )}
        {Boolean(mutation.error) && !form && (
          <div role="alert" className="ds-notice ds-tone-danger">
            <p>{signalError(mutation.error)}</p>
            {mutation.canRetry && (
              <div>
                <button className="ds-btn ds-btn-secondary" onClick={mutation.retry}>
                  Повторить сохранение
                </button>
              </div>
            )}
          </div>
        )}
      </section>

      <section className="ticket-panel" aria-labelledby="signal-what-title">
        <h2 id="signal-what-title">Что, где и когда</h2>
        <dl className="ds-kv">
          <Info label="Что">
            {data.subtype_label}
            {data.object_label &&
              data.object_label.toLowerCase() !== data.subtype_label.toLowerCase() &&
              ` — ${data.object_label}`}
          </Info>
          <Info label="Территория">
            {data.territory.label}
            {data.territory.quote && <Quoted text={data.territory.quote} />}
          </Info>
          {data.place.entrance && (
            <Info label="Подъезд">
              {data.place.entrance.value}
              <Quoted text={data.place.entrance.quote} />
            </Info>
          )}
          {data.place.floor && (
            <Info label="Этаж">
              {data.place.floor.value}
              <Quoted text={data.place.floor.quote} />
            </Info>
          )}
          {data.place.since && (
            <Info label="С какого времени">
              {data.place.since.value}
              <Quoted text={data.place.since.quote} />
            </Info>
          )}
          <Info label="Сколько">{countsLine(data.report_count, data.author_count, data.last_seen_at)}</Info>
          <Info label="Первое сообщение">{formatStaffTime(data.first_seen_at)}</Info>
        </dl>
      </section>

      <section className="ticket-panel" aria-labelledby="signal-quotes-title">
        <h2 id="signal-quotes-title">Слова жителей</h2>
        {(data.quotes ?? []).length === 0 ? (
          <p className="ds-subtle">Цитат нет.</p>
        ) : (
          (data.quotes ?? []).map((quote, index) => (
            <blockquote className="signal-quote" key={index}>
              «{quote.text}»
              <footer>
                {quote.author}, {shortTime(quote.sent_at)}
              </footer>
            </blockquote>
          ))
        )}
      </section>

      <section className="ticket-panel" aria-labelledby="signal-strength-title">
        <h2 id="signal-strength-title">Почему {label(strengthLabels, data.strength, "strength").toLowerCase()}</h2>
        <p>{data.strength_reason}</p>
      </section>

      <RouteBlock data={data} />

      <DecisionHistory data={data} openTicket={openTicket} />
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

function Quoted({ text }: { text: string }) {
  return <span className="muted signal-evidence"> — «{text}»</span>;
}

function RouteBlock({ data }: { data: SignalView }) {
  const card = data.action_card;
  const route = card.route;
  const basis = route.basis;
  const unverified = verificationNotes(route);
  return (
    <section
      className="ticket-panel route-card"
      aria-labelledby="signal-route-title"
    >
      <p className="ds-meta">
        Маршрут: {label(routeBadgeLabels, route.route_type, "route_type")}
      </p>
      <h2 id="signal-route-title">{card.title}</h2>
      <p>{card.explanation}</p>
      {data.route_source === "operator" && data.route_chosen_by && (
        <p>
          Маршрут выбран оператором {data.route_chosen_by}
          {data.route_chosen_at && ` в ${shortTime(data.route_chosen_at)}`}.
        </p>
      )}
      {route.organization_name && (
        <p>Вероятно, отвечает: {route.organization_name}</p>
      )}
      {(route.channels ?? []).length > 0 && (
        <p>
          Канал:{" "}
          {(route.channels ?? []).map((channel) => channel.label).join(", ")}
        </p>
      )}
      <div className="route-basis">
        <h3>Основание</h3>
        {basis ? (
          <>
            <p>{basis.text}</p>
            <p className="muted">
              Источник: {basis.source_title}
              {basis.verified_at &&
                `, проверено ${formatDay(basis.verified_at)}`}
            </p>
          </>
        ) : (
          <p className="muted">
            Правила в справочнике нет — продукт не угадывает ответственного.
          </p>
        )}
        {unverified.map((note) => (
          <p key={note} className="ds-notice ds-tone-warning">{note}</p>
        ))}
        {route.hidden_unverified_channels > 0 && (
          <p className="muted">
            Непроверенных каналов скрыто: {route.hidden_unverified_channels}.
          </p>
        )}
        <p className="muted">Версия справочника: {route.directory_version}</p>
      </div>
      {card.disclaimer && <p className="muted">{card.disclaimer}</p>}
      {card.demo_notice && (
        <span className="demo-badge">{card.demo_notice}</span>
      )}
    </section>
  );
}

function ActionButton({
  action,
  blocked,
  primary,
  onClick,
}: {
  action: Action;
  blocked: boolean;
  primary: boolean;
  onClick: () => void;
}) {
  const reasonId = `signal-reason-${action.code}`;
  return (
    <div>
      <button
        className={`ds-btn ${primary ? "ds-btn-primary" : action.code === "dismiss" ? "ds-btn-danger" : "ds-btn-secondary"}`}
        disabled={blocked || !action.enabled}
        aria-describedby={
          !action.enabled && action.reason ? reasonId : undefined
        }
        onClick={() => {
          if (!action.enabled || blocked) return;
          onClick();
        }}
      >
        {signalActionLabels[action.code]}
      </button>
      {!action.enabled && action.reason && (
        <p id={reasonId} className="muted action-reason">
          {action.reason}
        </p>
      )}
    </div>
  );
}

/** Звонок и официальный канал из карточки маршрута — ссылки, а не решения. */
function ContactActions({ data }: { data: SignalView }) {
  // Телефон памятки уже стоит первым в блоке безопасности — второй раз не нужен.
  const safetyPhone = data.action_card.safety?.phone;
  const contacts = (data.action_card.actions ?? []).filter(
    (action) =>
      (action.type === "call_phone" && action.phone !== safetyPhone) ||
      action.type === "open_official_channel",
  );
  if (!contacts.length) return null;
  return (
    <div className="ticket-buttons signal-contacts">
      {contacts.map((action, index) =>
        action.type === "call_phone" && action.phone ? (
          <a
            key={index}
            className="ds-btn ds-btn-secondary"
            href={`tel:${action.phone}`}
          >
            {action.label}
          </a>
        ) : action.enabled && action.url ? (
          <a
            key={index}
            className="ds-btn ds-btn-secondary"
            href={action.url}
            rel="noreferrer"
          >
            {action.label}
          </a>
        ) : (
          <div key={index}>
            <button
              className="ds-btn ds-btn-secondary"
              disabled
              aria-describedby={
                action.reason ? `contact-reason-${index}` : undefined
              }
            >
              {action.label}
            </button>
            {action.reason && (
              <p id={`contact-reason-${index}`} className="muted action-reason">
                {action.reason}
              </p>
            )}
          </div>
        ),
      )}
    </div>
  );
}

function DecisionForm({
  code,
  data,
  blocked,
  busy,
  error,
  close,
  submit,
}: {
  code: SignalActionCode;
  data: SignalView;
  blocked: boolean;
  busy: boolean;
  error: unknown;
  close: () => void;
  submit: (payload: SignalCommand) => void;
}) {
  const heading = useRef<HTMLHeadingElement>(null);
  const [category, setCategory] = useState<string>(data.ticket_draft.category);
  const [description, setDescription] = useState(data.ticket_draft.description);
  const [incident, setIncident] = useState(
    data.join_candidates?.[0]?.incident_id ?? "",
  );
  const [routeType, setRouteType] = useState("");
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");
  useEffect(() => {
    heading.current?.focus();
  }, []);
  const fieldError = (field: string) =>
    error instanceof ApiProblem &&
    error.problem.field_errors?.some(
      (e) => e.field === field || e.field.endsWith(`.${field}`),
    );
  const version = { expected_version: data.version };
  const hasChannel = (data.action_card.route.channels ?? []).length > 0;
  let body: ReactNode = null;
  let valid = true;
  let payload: SignalCommand = version;
  if (code === "create-ticket") {
    valid = description.trim().length >= 5;
    payload = {
      ...version,
      category: category as
        "elevator" | "water" | "lighting" | "waste" | "other",
      description: description.trim(),
    };
    body = (
      <>
        <p>
          Проверьте, что уйдёт в заявку. Описание собрано из слов жителей — его
          можно поправить.
        </p>
        <label>
          Категория
          <select
            value={category}
            disabled={busy}
            onChange={(e) => setCategory(e.target.value)}
          >
            {categoryOptions.map(([value, text]) => (
              <option key={value} value={value}>
                {text}
              </option>
            ))}
          </select>
        </label>
        <label>
          Описание заявки
          <textarea
            rows={8}
            minLength={5}
            maxLength={2000}
            required
            value={description}
            disabled={busy}
            aria-invalid={Boolean(fieldError("description"))}
            onChange={(e) => setDescription(e.target.value)}
          />
        </label>
        <p className="muted">
          Описание увидят жители дома в карточке проблемы. Дальше — обычная
          работа с заявкой в разделе «Заявки».
        </p>
      </>
    );
  } else if (code === "join") {
    valid = Boolean(incident);
    payload = { ...version, incident_id: incident };
    body = (
      <fieldset className="signal-choices">
        <legend>К какой открытой проблеме присоединить</legend>
        {(data.join_candidates ?? []).map((item) => (
          <label key={item.incident_id} className="signal-choice">
            <input
              type="radio"
              name="join-incident"
              value={item.incident_id}
              checked={incident === item.incident_id}
              disabled={busy}
              onChange={() => setIncident(item.incident_id)}
            />
            <span>
              {item.title} · {item.match_reason}
              <span className="muted">
                {" "}
                · сообщений {item.report_count}, участников{" "}
                {item.participant_count}, с {formatStaffTime(item.created_at)}
              </span>
            </span>
          </label>
        ))}
        <p className="muted">
          Второй заявки не появится: у проблемы станет больше участников.
        </p>
      </fieldset>
    );
  } else if (code === "route-external") {
    body = (
      <>
        <p>
          Сигнал закроется как внешний маршрут:{" "}
          {label(
            routeBadgeLabels,
            data.action_card.route.route_type,
            "route_type",
          )}
          .
        </p>
        <p>
          ДомСигнал никуда ничего не отправляет.{" "}
          {hasChannel
            ? "Жители могут обратиться сами по карточке маршрута."
            : "Проверенного канала в справочнике нет — продукт не называет его за вас."}
        </p>
      </>
    );
  } else if (code === "choose-route") {
    valid = (data.route_choices ?? []).includes(routeType as never);
    payload = { ...version, route_type: routeType as SignalView["route_type"] };
    body = (
      <>
        <label>
          Маршрут
          <select
            required
            value={routeType}
            disabled={busy}
            aria-invalid={Boolean(fieldError("route_type"))}
            onChange={(e) => setRouteType(e.target.value)}
          >
            <option value="" disabled>
              Выберите маршрут
            </option>
            {(data.route_choices ?? []).map((value) => (
              <option key={value} value={value}>
                {label(routeChoiceLabels, value, "route_type")}
              </option>
            ))}
          </select>
        </label>
        <p className="muted">
          Организацию и канал подставит справочник, если знает их для этого
          маршрута.
        </p>
      </>
    );
  } else if (code === "dismiss") {
    valid = Boolean(reason) && note.length <= 500;
    payload = {
      ...version,
      reason: reason as
        "not_a_problem" | "duplicate" | "resolved" | "out_of_scope" | "spam",
      ...(note.trim() ? { note: note.trim() } : {}),
    };
    body = (
      <>
        <label>
          Причина
          <select
            required
            value={reason}
            disabled={busy}
            aria-invalid={Boolean(fieldError("reason"))}
            onChange={(e) => setReason(e.target.value)}
          >
            <option value="" disabled>
              Выберите причину
            </option>
            {dismissReasons.map(([value, text]) => (
              <option key={value} value={value}>
                {text}
              </option>
            ))}
          </select>
        </label>
        <label>
          Комментарий (необязательно)
          <textarea
            rows={3}
            maxLength={500}
            value={note}
            disabled={busy}
            onChange={(e) => setNote(e.target.value)}
          />
        </label>
        <p className="muted">Причина нужна для оценки качества сигналов.</p>
      </>
    );
  }
  return (
    <form
      className="ticket-form signal-form"
      aria-labelledby="signal-form-title"
      onSubmit={(e) => {
        e.preventDefault();
        if (blocked || !valid) return;
        submit(payload);
      }}
    >
      <h3 id="signal-form-title" tabIndex={-1} ref={heading}>
        {signalActionLabels[code]}
      </h3>
      {body}
      {Boolean(error) && <p role="alert">{signalError(error)}</p>}
      <div className="ticket-buttons">
        <button
          className="ds-btn ds-btn-primary"
          type="submit"
          disabled={blocked || !valid}
        >
          {code === "dismiss" ? "Закрыть сигнал" : signalActionLabels[code]}
        </button>
        <button
          className="ds-btn ds-btn-secondary"
          type="button"
          disabled={busy}
          onClick={close}
        >
          Отмена
        </button>
      </div>
    </form>
  );
}

function DecisionHistory({
  data,
  openTicket,
}: {
  data: SignalView;
  openTicket: (ticketId: string) => void;
}) {
  const decision = data.decision;
  const linked = data.linked;
  return (
    <section className="ticket-panel" aria-labelledby="signal-history-title">
      <h2 id="signal-history-title">История решения</h2>
      {decision ? (
        <dl>
          <Info label="Решение">
            {label(statusLabels, decision.status, "signal_status")}
          </Info>
          {decision.decided_by && (
            <Info label="Кто">{decision.decided_by}</Info>
          )}
          {decision.decided_at && (
            <Info label="Когда">{formatStaffTime(decision.decided_at)}</Info>
          )}
          {decision.reason_label && (
            <Info label="Причина">{decision.reason_label}</Info>
          )}
          {decision.note && <Info label="Комментарий">{decision.note}</Info>}
          {decision.route && (
            <Info label="Маршрут в момент решения">
              {label(routeBadgeLabels, decision.route.route_type, "route_type")}
              {decision.route.organization_name &&
                ` · ${decision.route.organization_name}`}
              {decision.route.channel_label &&
                ` · ${decision.route.channel_label}`}
              {decision.route.basis_text && (
                <span className="muted signal-evidence">
                  {" "}
                  — {decision.route.basis_text} (
                  {decision.route.basis_source_title}
                  {decision.route.basis_verified_at &&
                    `, проверено ${formatDay(decision.route.basis_verified_at)}`}
                  )
                </span>
              )}
            </Info>
          )}
        </dl>
      ) : (
        <p className="muted">Решение ещё не принято.</p>
      )}
      {linked && (
        <p>
          Связанная проблема: {linked.title}
          {linked.ticket_id && linked.ticket_number && (
            <>
              {" · "}
              <a
                href={`/admin/?ticket=${linked.ticket_id}`}
                onClick={(e) => {
                  e.preventDefault();
                  openTicket(linked.ticket_id!);
                }}
              >
                Открыть заявку {linked.ticket_number}
              </a>
            </>
          )}
        </p>
      )}
      {(data.events ?? []).length > 0 && (
        <ol className="timeline signal-events">
          {(data.events ?? []).map((event, index) => (
            <li key={index}>
              <time dateTime={event.at}>{shortTime(event.at)}</time> ·{" "}
              {event.label}
              {event.actor && ` · ${event.actor}`}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
