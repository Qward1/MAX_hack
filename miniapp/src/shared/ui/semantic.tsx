import { Button, Flex, Panel, Typography } from "@maxhub/max-ui";
import { type ReactNode, useId } from "react";
import {
  type ActionCode,
  actionLabels,
  formatDate,
  knownActions,
  type Source,
  statusLabels,
  warnUnknown,
} from "../../features/incidents/presentation";
import { maxBridge, safeUrl } from "../max/bridge";

export function StatusBadge({ status }: { status: string }) {
  const known = Object.hasOwn(statusLabels, status);
  if (!known) warnUnknown("status");
  const tone = !known
    ? "neutral"
    : ["resolved", "dismissed"].includes(status)
      ? "calm"
      : ["overdue", "escalated"].includes(status)
        ? "attention"
        : "active";
  return (
    <span className={`status-badge tone-${tone}`}>
      <span aria-hidden="true">
        {tone === "calm" ? "✓" : tone === "attention" ? "!" : "●"}
      </span>{" "}
      {known ? statusLabels[status] : "Состояние обновилось"}
    </span>
  );
}

export function DemoBadge() {
  return (
    <span className="demo-badge">
      <span aria-hidden="true">◇</span> Демонстрационные данные
    </span>
  );
}

const sourceLabels: Record<string, string> = {
  official: "Официальный источник",
  product_derived: "Рассчитано ДомСигналом",
  user_reported: "Указано пользователем",
  demo: "Демонстрационные данные",
};
export function SourceChip({ source }: { source: Source | null | undefined }) {
  if (!source) return null;
  const known = Object.hasOwn(sourceLabels, source.origin ?? "");
  if (!known) warnUnknown("source");
  // Incomplete official records cannot earn an official badge.
  const verified = formatDate(source.verified_at);
  const valid =
    known &&
    (source.origin !== "official" || Boolean(source.source_title && verified));
  const title = valid
    ? sourceLabels[source.origin ?? ""]
    : "Происхождение не подтверждено";
  const url = safeUrl(source.source_url);
  return (
    <details
      className={`source-chip ${source.origin === "demo" ? "source-demo" : ""}`}
    >
      <summary>
        <span aria-hidden="true">
          {source.origin === "demo"
            ? "◇"
            : source.origin === "user_reported"
              ? "◌"
              : "ⓘ"}
        </span>{" "}
        {title}
      </summary>
      <div className="source-details">
        {source.source_title && (
          <Typography.Text variant="body-strong">
            {source.source_title}
          </Typography.Text>
        )}
        {source.note && <p className="full-text">{source.note}</p>}
        {source.origin === "user_reported" && (
          <p>Внешней системой не подтверждено.</p>
        )}
        {verified && <p>Проверено: {verified}</p>}
        {formatDate(source.recorded_at) && (
          <p>Зафиксировано: {formatDate(source.recorded_at)}</p>
        )}
        {url && (
          <a
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(event) => {
              if (maxBridge.openLink(url)) event.preventDefault();
            }}
          >
            Открыть источник ↗
          </a>
        )}
      </div>
    </details>
  );
}

export function PageHeader({
  title,
  subtitle,
  eyebrow = "ДомСигнал",
  children,
}: {
  title: string;
  subtitle?: string;
  eyebrow?: string;
  children?: ReactNode;
}) {
  return (
    <header className="page-header">
      <Typography.Text variant="label-strong" className="eyebrow">
        {eyebrow}
      </Typography.Text>
      <Typography.Headline asChild>
        <h1 tabIndex={-1} id="page-title">
          {title}
        </h1>
      </Typography.Headline>
      {subtitle && (
        <Typography.Text asChild color="secondary">
          <p>{subtitle}</p>
        </Typography.Text>
      )}
      {children}
    </header>
  );
}

export function StatePanel({
  title,
  detail,
  loading = false,
  action,
  onAction,
  back,
}: {
  title: string;
  detail?: string;
  loading?: boolean;
  action?: string;
  onAction?: () => void;
  back?: ReactNode;
}) {
  return (
    <Panel className="state-panel" aria-busy={loading}>
      <div role={loading ? "status" : "alert"} aria-live="polite">
        <div className="state-symbol" aria-hidden="true">
          {loading ? "…" : "↗"}
        </div>
        <Typography.Title asChild>
          <h2>{title}</h2>
        </Typography.Title>
        {detail && <p>{detail}</p>}
      </div>
      {loading && <div className="skeleton" aria-hidden="true" />}
      <Flex gap={12} wrap="wrap" justify="center">
        {action && onAction && <Button onClick={onAction}>{action}</Button>}
        {back}
      </Flex>
    </Panel>
  );
}

export function InfoRow({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="info-row">
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
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
  // A known label is not an implemented endpoint. Only supplied handlers may expose a CTA.
  const available = knownActions(actions).filter(
    (action) => handlers[action.code],
  );
  return (
    <Panel className="next-action" aria-labelledby={id}>
      <Typography.Text variant="label-strong" className="eyebrow">
        Следующий шаг
      </Typography.Text>
      <Typography.Title asChild>
        <h2 id={id}>Что делать сейчас</h2>
      </Typography.Title>
      {available.length ? (
        <Flex direction="column" gap={12}>
          {available.map((action) => (
            <div key={action.code}>
              <Button
                stretched
                disabled={busy || !action.enabled}
                aria-describedby={
                  action.reason ? `${id}-${action.code}` : undefined
                }
                onClick={() => {
                  if (action.enabled && !busy) handlers[action.code]?.();
                }}
              >
                {actionLabels[action.code]}
              </Button>
              {action.reason && (
                <p id={`${id}-${action.code}`} className="muted">
                  {action.reason}
                </p>
              )}
            </div>
          ))}
        </Flex>
      ) : (
        <p>
          Пока нет доступных действий. Здесь можно проверить описание и
          сообщения по проблеме.
        </p>
      )}
    </Panel>
  );
}

export function Timeline({
  events,
}: {
  events: {
    id: string;
    title: string;
    detail?: string | null;
    occurred_at: string;
  }[];
}) {
  if (!events.length) return null;
  return (
    <ol className="timeline">
      {events.map((event) => (
        <li key={event.id}>
          <Typography.Text variant="body-strong">{event.title}</Typography.Text>
          {formatDate(event.occurred_at) && (
            <time dateTime={event.occurred_at}>
              {formatDate(event.occurred_at)}
            </time>
          )}
          {event.detail && <p className="full-text">{event.detail}</p>}
        </li>
      ))}
    </ol>
  );
}
