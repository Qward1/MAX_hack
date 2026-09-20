import { Button, Flex, Panel, Typography } from "@maxhub/max-ui";
import { type ReactNode, useId } from "react";
import type {
  ActionCard,
  ActionCardAction,
  SafetyBlock,
} from "../../shared/api/client";
import { maxBridge, safeUrl } from "../../shared/max/bridge";
import { DemoBadge } from "../../shared/ui/semantic";
import { formatDay } from "../incidents/presentation";
import {
  type CardActionType,
  cardActionLabel,
  knownCardActions,
  linkActions,
} from "./presentation";

const UNVERIFIED_NOTE = "Сведения требуют сверки.";

/** Ссылка на проверенный источник. Непроверенный адрес ссылкой не становится. */
function SourceLink({ url, title }: { url?: string | null; title?: string | null }) {
  const safe = safeUrl(url);
  if (!safe) return title ? <span className="muted">Источник: {title}</span> : null;
  return (
    <a
      href={safe}
      target="_blank"
      rel="noopener noreferrer"
      onClick={(event) => {
        if (maxBridge.openLink(safe)) event.preventDefault();
      }}
    >
      Источник: {title || "официальная страница"} ↗
    </a>
  );
}

/** Памятка безопасности. При любом маршруте она стоит первой на экране. */
function SafetyPanel({ safety }: { safety: SafetyBlock }) {
  const verified = formatDay(safety.verified_at);
  return (
    <Panel className="safety-panel" role="alert">
      <Typography.Text variant="label-strong" className="eyebrow">
        Безопасность прежде всего
      </Typography.Text>
      <Typography.Title asChild>
        <h2>{safety.title}</h2>
      </Typography.Title>
      {safety.phone && (
        <p className="safety-phone">
          <a href={`tel:${safety.phone}`}>Позвонить {safety.phone}</a>
        </p>
      )}
      {(safety.lines ?? []).map((line) => (
        <p key={line} className="full-text">
          {line}
        </p>
      ))}
      {(safety.steps ?? []).length > 0 && (
        <ul className="safety-steps">
          {(safety.steps ?? []).map((step) => (
            <li key={step.text}>
              <span className="full-text">{step.text}</span>
              <SourceLink url={step.source_url} title={step.source_title} />
            </li>
          ))}
        </ul>
      )}
      <SourceLink url={safety.source_url} title={safety.source_title} />
      {verified && <p className="muted">Проверено: {verified}</p>}
    </Panel>
  );
}

function CardAction({
  action,
  group,
  handler,
  busy,
}: {
  action: ActionCardAction;
  group: string;
  handler?: () => void;
  busy: boolean;
}) {
  const key = `${group}-${action.type}-${action.url ?? action.phone ?? ""}`;
  const reasonId = action.reason ? `${key}-reason` : undefined;
  const label = cardActionLabel(action);
  const url = safeUrl(action.url);
  const reason = action.reason && (
    <p id={reasonId} className="muted action-reason">
      {action.reason}
    </p>
  );
  if (action.type === "open_official_channel") {
    // Непроверенная ссылка — выключенная кнопка с причиной, а не ссылка в никуда.
    if (!action.enabled || !url)
      return (
        <div>
          <Button stretched disabled aria-describedby={reasonId}>
            {label}
          </Button>
          {reason}
        </div>
      );
    return (
      <div>
        <Button asChild stretched>
          <a
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(event) => {
              if (maxBridge.openLink(url)) event.preventDefault();
            }}
          >
            {label} ↗
          </a>
        </Button>
        {reason}
      </div>
    );
  }
  if (action.type === "call_phone" && action.phone)
    return (
      <div>
        <Button asChild stretched>
          <a href={`tel:${action.phone}`}>{label}</a>
        </Button>
        {reason}
      </div>
    );
  return (
    <div>
      <Button
        stretched
        disabled={busy || !action.enabled}
        aria-describedby={reasonId}
        onClick={() => {
          if (action.enabled && !busy) handler?.();
        }}
      >
        {label}
      </Button>
      {reason}
    </div>
  );
}

/**
 * Экран карточки маршрута. Порядок блоков закреплён сверху вниз: безопасность,
 * маршрут, основание, факты канала, действия, дисклеймер.
 *
 * Известная подпись — ещё не реализованный шаг: кнопка без обработчика экрана
 * не рисуется вовсе, как и в блоке следующего шага у проблемы дома.
 */
export function RouteCard({
  card,
  handlers = {},
  busy = false,
  demo = false,
  extra,
}: {
  card: ActionCard;
  handlers?: Partial<Record<CardActionType, () => void>>;
  busy?: boolean;
  demo?: boolean;
  /** Шаг, которого нет в карточке: например, уже созданная проблема дома. */
  extra?: ReactNode;
}) {
  const group = useId();
  const basis = card.route.basis;
  const verified = formatDay(basis?.verified_at);
  const needsCheck =
    card.route.stale ||
    (basis ? basis.verification_status !== "verified" : false) ||
    (card.route.channels ?? []).some(
      (channel) => channel.stale || channel.verification_status !== "verified",
    );
  const actions = knownCardActions(card.actions).filter(
    (action) =>
      linkActions.includes(action.type as CardActionType) ||
      handlers[action.type as CardActionType],
  );
  return (
    <>
      {card.safety && <SafetyPanel safety={card.safety} />}
      <Panel className="detail-section route-card">
        <Typography.Text variant="label-strong" className="eyebrow">
          Маршрут
        </Typography.Text>
        <Typography.Title asChild>
          <h2>{card.title}</h2>
        </Typography.Title>
        <p className="full-text">{card.explanation}</p>
        {card.route.organization_name && (
          <p className="muted">Вероятный адресат: {card.route.organization_name}</p>
        )}
      </Panel>
      {basis && (
        <Panel className="detail-section route-basis">
          <Typography.Title asChild>
            <h2>Основание</h2>
          </Typography.Title>
          <p className="full-text">{basis.text}</p>
          <SourceLink url={basis.source_url} title={basis.source_title} />
          {verified && <p className="muted">Проверено: {verified}</p>}
          {needsCheck && (
            <p className="honesty-note" role="note">
              {UNVERIFIED_NOTE}
            </p>
          )}
        </Panel>
      )}
      {(card.facts ?? []).length > 0 && (
        <Panel className="detail-section route-facts">
          <Typography.Title asChild>
            <h2>Что известно о канале</h2>
          </Typography.Title>
          <ul>
            {(card.facts ?? []).map((fact) => (
              <li key={fact.text}>
                <span className="full-text">{fact.text}</span>
                <SourceLink url={fact.source_url} title={fact.source_title} />
              </li>
            ))}
          </ul>
        </Panel>
      )}
      <Panel className="next-action card-actions" aria-labelledby={`${group}-actions`}>
        <Typography.Text variant="label-strong" className="eyebrow">
          Следующий шаг
        </Typography.Text>
        <Typography.Title asChild>
          <h2 id={`${group}-actions`}>Что делать сейчас</h2>
        </Typography.Title>
        {actions.length || extra ? (
          <Flex direction="column" gap={12}>
            {extra}
            {actions.map((action) => (
              <CardAction
                key={`${action.type}-${action.url ?? action.phone ?? ""}`}
                action={action}
                group={group}
                handler={handlers[action.type as CardActionType]}
                busy={busy}
              />
            ))}
          </Flex>
        ) : (
          <p>Доступных здесь шагов пока нет.</p>
        )}
      </Panel>
      {(card.disclaimer || card.demo_notice || demo) && (
        <Panel className="honesty-note route-disclaimer">
          {card.disclaimer && <p className="full-text">{card.disclaimer}</p>}
          <Flex gap={12} wrap="wrap" align="center">
            {(card.demo_notice || demo) && <DemoBadge />}
          </Flex>
        </Panel>
      )}
    </>
  );
}
