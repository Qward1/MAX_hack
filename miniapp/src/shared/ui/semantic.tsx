import { type ReactNode, useEffect, useId, useRef, useState } from "react";
import {
  type ActionCode,
  actionLabels,
  knownActions,
  type Source,
  warnUnknown,
} from "../../features/incidents/presentation";
import { maxBridge, safeUrl } from "../max/bridge";
import { Button } from "./Button";
import { formatDay, formatWhen } from "./format";
import { residentIncidentStatus, type StatusEntry, statusOf, TONE_MARK, type Tone } from "./status";

/** Тег статуса: текст, знак и тон. Не кликабелен — это состояние, а не действие. */
export function StatusTag({ entry }: { entry: StatusEntry }) {
  return (
    // Знак — из CSS (::before): он виден, но не входит ни в текст, ни в имя для экранного диктора.
    <span className={`ds-tag ds-tone-${entry.tone}`} data-mark={TONE_MARK[entry.tone]}>
      {entry.label}
    </span>
  );
}

/** Статус проблемы дома по словарю жителя. */
export function StatusBadge({ status }: { status: string }) {
  return <StatusTag entry={statusOf(residentIncidentStatus, status)} />;
}

export function DemoBadge() {
  return <span className="ds-tag ds-tone-neutral ds-tag-demo">Пример данных</span>;
}

/**
 * Блок-уведомление рядом с тем, к чему относится. Тон — только по смыслу:
 * danger — безопасность и ошибки, warning — «требует сверки», info — пояснение.
 */
export function Notice({
  tone = "info",
  title,
  children,
  role,
  id,
  className,
}: {
  tone?: Exclude<Tone, "neutral"> | "neutral";
  title?: ReactNode;
  children?: ReactNode;
  role?: "alert" | "status" | "note";
  id?: string;
  className?: string;
}) {
  return (
    <div className={`ds-notice ds-tone-${tone}${className ? ` ${className}` : ""}`} role={role} id={id}>
      {title && <p className="ds-notice-title">{title}</p>}
      {children}
    </div>
  );
}

const sourceLabels: Record<string, string> = {
  official: "Официальный источник",
  product_derived: "Рассчитано ДомСигналом",
  user_reported: "Со слов жителей",
  demo: "Пример данных ДомСигнала",
};

/** Происхождение сведений: видно сразу, подробности — по нажатию. */
export function SourceChip({ source, label = "Источник" }: { source: Source | null | undefined; label?: string }) {
  if (!source) return null;
  const known = Object.hasOwn(sourceLabels, source.origin ?? "");
  if (!known) warnUnknown("source");
  // Неполная официальная запись не получает «официальный» знак.
  const verified = formatDay(source.verified_at);
  const valid = known && (source.origin !== "official" || Boolean(source.source_title && verified));
  const title = valid ? sourceLabels[source.origin ?? ""] : "Происхождение не подтверждено";
  const url = safeUrl(source.source_url);
  const recorded = formatWhen(source.recorded_at);
  return (
    <details className={`ds-disclosure ds-source${source.origin === "demo" ? " is-demo" : ""}`}>
      <summary>
        {label}: {title}
      </summary>
      <div className="ds-disclosure-body">
        {source.source_title && <p className="ds-strong">{source.source_title}</p>}
        {source.note && <p className="ds-prose">{source.note}</p>}
        {source.origin === "user_reported" && <p>Внешней системой не подтверждено.</p>}
        {verified && <p>Проверено: {verified}</p>}
        {recorded && <p>Записано: {recorded}</p>}
        {url && (
          <a
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(event) => {
              if (maxBridge.openLink(url)) event.preventDefault();
            }}
          >
            Открыть источник<span className="ds-visually-hidden"> (в новом окне)</span>
          </a>
        )}
      </div>
    </details>
  );
}

/** Заголовок экрана: говорит, что здесь можно сделать или узнать. Один h1. */
export function PageHeader({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <header className="ds-page-header">
      <h1 tabIndex={-1} id="page-title">
        {title}
      </h1>
      {subtitle && <p className="ds-subtle">{subtitle}</p>}
      {children}
    </header>
  );
}

/** «Назад» — всегда правда: возвращает туда, откуда человек пришёл. */
export function BackLink({ onBack, label = "Назад" }: { onBack: () => void; label?: string }) {
  return (
    <button type="button" className="ds-back" onClick={onBack}>
      <span aria-hidden="true">←</span> {label}
    </button>
  );
}

/**
 * Состояния экрана: загрузка (каркас без скачков), пусто (что здесь появится
 * и что сделать), ошибка (что случилось и «Повторить»).
 */
export function StatePanel({
  title,
  detail,
  loading = false,
  kind,
  action,
  onAction,
  back,
}: {
  title: string;
  detail?: string;
  loading?: boolean;
  kind?: "loading" | "empty" | "error";
  action?: string;
  onAction?: () => void;
  back?: ReactNode;
}) {
  const state = kind ?? (loading ? "loading" : "empty");
  return (
    <section className={`ds-state ds-state-${state}`} aria-busy={state === "loading"}>
      <div role={state === "loading" ? "status" : state === "error" ? "alert" : undefined}>
        <h2 className="ds-state-title">{title}</h2>
        {detail && <p>{detail}</p>}
      </div>
      {state === "loading" && (
        <div className="ds-skeleton" aria-hidden="true">
          <span />
          <span />
          <span />
        </div>
      )}
      {(action && onAction) || back ? (
        <div className="ds-actions">
          {action && onAction && (
            <Button variant={state === "error" ? "primary" : "secondary"} onClick={onAction}>
              {action}
            </Button>
          )}
          {back}
        </div>
      ) : null}
    </section>
  );
}

export function InfoRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="ds-kv-row">
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

/**
 * Список «ключ — значение» с «Изменить» у пункта — как check answers:
 * правка возвращает к нужному полю, а после неё — обратно к проверке.
 */
export function CheckAnswers({
  items,
}: {
  items: { label: string; value: ReactNode; change?: () => void; changeLabel?: string }[];
}) {
  return (
    <dl className="ds-kv ds-check">
      {items.map((item) => (
        <div className="ds-kv-row" key={item.label}>
          <dt>{item.label}</dt>
          <dd>{item.value}</dd>
          {item.change && (
            <dd className="ds-kv-change">
              <button type="button" className="ds-edit" onClick={item.change}>
                Изменить{" "}
                <span className="ds-visually-hidden">{item.changeLabel ?? item.label.toLowerCase()}</span>
              </button>
            </dd>
          )}
        </div>
      ))}
    </dl>
  );
}

export function NextAction({
  actions,
  handlers = {},
  busy = false,
}: {
  actions: unknown;
  handlers?: Partial<Record<ActionCode, () => void>>;
  busy?: boolean;
}) {
  const id = useId();
  // Известная подпись — ещё не реализованный шаг: без обработчика кнопки нет.
  const available = knownActions(actions).filter((action) => handlers[action.code]);
  if (!available.length) return null;
  return (
    <section className="ds-section" aria-labelledby={id}>
      <h2 id={id}>Что можно сделать</h2>
      <div className="ds-stack">
        {available.map((action, index) => (
          <Button
            key={action.code}
            variant={index === 0 ? "primary" : "secondary"}
            stretched
            disabled={busy || !action.enabled}
            reason={action.enabled ? null : action.reason}
            onClick={() => handlers[action.code]?.()}
          >
            {actionLabels[action.code]}
          </Button>
        ))}
      </div>
    </section>
  );
}

export type ProgressStep = {
  title: ReactNode;
  state: "done" | "current" | "upcoming";
  detail?: ReactNode;
};
const STEP_STATE = { done: "готово", current: "сейчас", upcoming: "впереди" } as const;

/**
 * Ход решения по шагам процесса продукта. Шаг «готово» или «сейчас» — только
 * по фактическому статусу из API; «впереди» — порядок работы, а не событие.
 */
export function ProgressSteps({ steps, label }: { steps: ProgressStep[]; label: string }) {
  return (
    <ol className="ds-progress" aria-label={label}>
      {steps.map((step, index) => (
        <li key={index} data-state={step.state} aria-current={step.state === "current" ? "step" : undefined}>
          <span className="ds-progress-mark" aria-hidden="true" />
          <div className="ds-progress-body">
            <p className="ds-progress-title">
              {step.title}
              <span className="ds-visually-hidden">, {STEP_STATE[step.state]}</span>
            </p>
            {step.detail}
          </div>
        </li>
      ))}
    </ol>
  );
}

/** Хронология: после нескольких записей свёрнута, раскрывается по кнопке. */
export function Timeline({
  events,
  collapseAfter = 3,
  label = "записи",
}: {
  events: { id: string; title: string; detail?: string | null; occurred_at: string }[];
  collapseAfter?: number;
  label?: string;
}) {
  const [open, setOpen] = useState(false);
  const listId = useId();
  if (!events.length) return null;
  const hidden = events.length - collapseAfter;
  const shown = open || hidden <= 0 ? events : events.slice(0, collapseAfter);
  return (
    <>
      <ol className="ds-timeline" id={listId}>
        {shown.map((event) => (
          <li key={event.id}>
            <p className="ds-strong">{event.title}</p>
            {formatWhen(event.occurred_at) && (
              <time dateTime={event.occurred_at} className="ds-meta">
                {formatWhen(event.occurred_at)}
              </time>
            )}
            {event.detail && <p className="ds-prose">{event.detail}</p>}
          </li>
        ))}
      </ol>
      {hidden > 0 && (
        <button
          type="button"
          className="ds-link-button"
          aria-expanded={open}
          aria-controls={listId}
          onClick={() => setOpen(!open)}
        >
          {open ? "Свернуть" : `Показать все ${label} (${events.length})`}
        </button>
      )}
    </>
  );
}

/**
 * Диалог подтверждения — только для необратимых и значимых действий.
 * Esc и «Отмена» закрывают его, фокус возвращается к кнопке, которая его открыла.
 */
export function ConfirmDialog({
  title,
  children,
  confirmLabel,
  cancelLabel = "Отмена",
  busy = false,
  busyLabel,
  tone = "primary",
  onConfirm,
  onCancel,
}: {
  title: string;
  children?: ReactNode;
  confirmLabel: string;
  cancelLabel?: string;
  busy?: boolean;
  busyLabel?: string;
  tone?: "primary" | "danger";
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const trigger = document.activeElement as HTMLElement | null;
    const dialog = ref.current;
    if (dialog && !dialog.open) {
      if (typeof dialog.showModal === "function") dialog.showModal();
      else dialog.setAttribute("open", "");
    }
    return () => {
      if (dialog?.open) dialog.close?.();
      trigger?.focus?.();
    };
  }, []);
  return (
    <dialog
      ref={ref}
      className="ds-dialog"
      aria-labelledby={titleId}
      onCancel={(event) => {
        event.preventDefault();
        if (!busy) onCancel();
      }}
    >
      <h2 id={titleId}>{title}</h2>
      {children}
      <div className="ds-actions">
        <Button variant={tone} loading={busy} loadingLabel={busyLabel} onClick={onConfirm}>
          {confirmLabel}
        </Button>
        <Button variant="secondary" disabled={busy} onClick={onCancel}>
          {cancelLabel}
        </Button>
      </div>
    </dialog>
  );
}
