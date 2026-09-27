import { type ReactNode, useId } from "react";
import type { ActionCard, ActionCardAction, SafetyBlock } from "../../shared/api/client";
import { maxBridge, safeUrl } from "../../shared/max/bridge";
import { Button, LinkButton } from "../../shared/ui/Button";
import { countLabel, formatDay } from "../../shared/ui/format";
import { DemoBadge, Notice } from "../../shared/ui/semantic";
import { SourceDisclosure } from "../../shared/ui/SourceLink";
import { type CardActionType, cardActionLabel, knownCardActions, linkActions, verificationNotes } from "./presentation";

/**
 * «Требует сверки» с названием того, что именно не сверено: основание,
 * кто отвечает, или сведения об официальном сервисе. Не прячется в раскрытие.
 */
export function VerificationNote({ route }: { route: ActionCard["route"] }) {
  const notes = verificationNotes(route);
  if (!notes.length) return null;
  return (
    <Notice tone="warning" role="note">
      {notes.map((note) => (
        <p key={note}>{note}</p>
      ))}
    </Notice>
  );
}

/**
 * Памятка безопасности. При любом ответе она стоит первой на экране:
 * телефон — настоящая ссылка `tel:`, у каждой строки — источник. Одинаковый
 * источник нескольких строк показан один раз — одной строкой с раскрытием.
 */
export function SafetyPanel({ safety }: { safety: SafetyBlock }) {
  const verified = formatDay(safety.verified_at);
  const titleId = useId();
  const sources: { url?: string | null; title?: string | null }[] = [];
  for (const source of [
    ...(safety.steps ?? []).map((step) => ({ url: step.source_url, title: step.source_title })),
    { url: safety.source_url, title: safety.source_title },
  ])
    if ((source.title || source.url) && !sources.some((known) => known.title === source.title && known.url === source.url))
      sources.push(source);
  return (
    <section className="ds-safety" role="alert" aria-labelledby={titleId}>
      <h2 id={titleId}>{safety.title}</h2>
      {safety.phone && (
        <a className="ds-call" href={`tel:${safety.phone}`}>
          Позвонить {safety.phone}
        </a>
      )}
      {(safety.lines ?? []).map((line) => (
        <p key={line} className="ds-prose">
          {line}
        </p>
      ))}
      {(safety.steps ?? []).length > 0 && (
        <ul className="ds-bullets">
          {(safety.steps ?? []).map((step) => (
            <li key={step.text}>
              <span className="ds-prose">{step.text}</span>
            </li>
          ))}
        </ul>
      )}
      {sources.length > 0 && (
        <div>
          {sources.map((source) => (
            <SourceDisclosure
              key={`${source.title}-${source.url}`}
              url={source.url}
              title={source.title}
              verified={source.url === safety.source_url && source.title === safety.source_title ? verified : null}
            />
          ))}
        </div>
      )}
    </section>
  );
}

export function CardAction({
  action,
  primary,
  handler,
  busy,
}: {
  action: ActionCardAction;
  primary: boolean;
  handler?: () => void;
  busy: boolean;
}) {
  const label = cardActionLabel(action);
  const url = safeUrl(action.url);
  const variant = primary ? "primary" : "secondary";
  if (action.type === "open_official_channel") {
    // Непроверенная ссылка — выключенная кнопка с причиной, а не ссылка в никуда.
    if (!action.enabled || !url)
      return (
        <Button stretched disabled reason={action.reason ?? "Ссылки на официальный сервис пока нет."}>
          {label}
        </Button>
      );
    return (
      <div className="ds-action ds-action-stretched">
        <LinkButton
          variant={variant}
          stretched
          href={url}
          target="_blank"
          rel="noopener noreferrer"
          onClick={(event) => {
            if (maxBridge.openLink(url)) event.preventDefault();
          }}
        >
          {label} ↗<span className="ds-visually-hidden"> (откроется отдельно)</span>
        </LinkButton>
        {action.reason && <p className="ds-reason">{action.reason}</p>}
      </div>
    );
  }
  if (action.type === "call_phone" && action.phone)
    return (
      <div className="ds-action ds-action-stretched">
        <LinkButton variant={variant} stretched href={`tel:${action.phone}`}>
          {label}
        </LinkButton>
        {action.reason && <p className="ds-reason">{action.reason}</p>}
      </div>
    );
  return (
    <Button
      variant={variant}
      stretched
      disabled={busy || !action.enabled}
      reason={action.enabled ? action.reason : action.reason ?? "Сейчас недоступно."}
      onClick={() => handler?.()}
    >
      {label}
    </Button>
  );
}

/**
 * Карточка «куда обратиться». Порядок сверху вниз закреплён тестом:
 * безопасность → кто отвечает → основание → что известно о сервисе →
 * действия (в порядке backend) → пояснение и пометка демо-данных.
 *
 * Известная подпись — ещё не реализованный шаг: кнопка без обработчика экрана
 * не рисуется вовсе.
 */
export function RouteCard({
  card,
  handlers = {},
  busy = false,
  demo = false,
  extra,
  hideSafety = false,
  primaryActions = true,
  hideActions = false,
}: {
  card: ActionCard;
  handlers?: Partial<Record<CardActionType, () => void>>;
  busy?: boolean;
  demo?: boolean;
  /** Шаг, которого нет в карточке: например, уже созданная проблема дома. */
  extra?: ReactNode;
  /** Памятку безопасности экран уже показал выше. */
  hideSafety?: boolean;
  /** Первое доступное действие — основное; выключается, где выбор равноправный. */
  primaryActions?: boolean;
  /** Решение принимается кнопками экрана (например, выбор при дубле). */
  hideActions?: boolean;
}) {
  const group = useId();
  const basis = card.route.basis;
  const verified = formatDay(basis?.verified_at);
  const actions = knownCardActions(card.actions).filter(
    (action) => linkActions.includes(action.type as CardActionType) || handlers[action.type as CardActionType],
  );
  const primaryIndex = primaryActions ? actions.findIndex((action) => action.enabled) : -1;
  return (
    <>
      {card.safety && !hideSafety && <SafetyPanel safety={card.safety} />}
      <section className="ds-section route-card" aria-labelledby={`${group}-title`}>
        <h2 id={`${group}-title`}>{card.title}</h2>
        <p className="ds-prose">{card.explanation}</p>
        {card.route.organization_name && <p>Вероятный адресат: {card.route.organization_name}</p>}
      </section>
      {basis && (
        <section className="ds-section route-basis" aria-labelledby={`${group}-basis`}>
          <h2 id={`${group}-basis`}>Основание</h2>
          <p className="ds-prose">{basis.text}</p>
          <SourceDisclosure url={basis.source_url} title={basis.source_title} verified={verified} />
          <VerificationNote route={card.route} />
        </section>
      )}
      {(card.facts ?? []).length > 0 && (
        <details className="ds-disclosure route-facts">
          <summary>
            <h2 className="ds-summary-title">Что известно об официальном сервисе</h2>
            <span className="ds-meta">{countLabel((card.facts ?? []).length, ["факт", "факта", "фактов"])}</span>
          </summary>
          <ul className="ds-bullets ds-disclosure-body">
            {(card.facts ?? []).map((fact) => (
              <li key={fact.text}>
                <span className="ds-prose">{fact.text}</span>
                <SourceDisclosure url={fact.source_url} title={fact.source_title} />
              </li>
            ))}
          </ul>
        </details>
      )}
      {!hideActions && <section className="ds-section card-actions" aria-labelledby={`${group}-actions`}>
        <h2 id={`${group}-actions`}>Что можно сделать</h2>
        {actions.length || extra ? (
          <div className="ds-stack">
            {actions.map((action, index) => (
              <CardAction
                key={`${action.type}-${action.url ?? action.phone ?? ""}`}
                action={action}
                primary={index === primaryIndex}
                handler={handlers[action.type as CardActionType]}
                busy={busy}
              />
            ))}
            {extra}
          </div>
        ) : (
          <p>Доступных здесь шагов пока нет.</p>
        )}
      </section>}
      {(card.disclaimer || card.demo_notice || demo) && (
        <div className="ds-group route-disclaimer">
          {card.disclaimer && <p className="ds-prose ds-subtle">{card.disclaimer}</p>}
          {(card.demo_notice || demo) && <DemoBadge />}
        </div>
      )}
    </>
  );
}
