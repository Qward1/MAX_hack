import { useCallback, useEffect, useState } from "react";
import {
  signalClient,
  type SignalClient,
  type SignalList,
  type SignalSummary,
} from "../shared/api/signals";
import { useResource } from "../shared/api/useResource";
import { Pagination } from "../features/tickets/components";
import { SignalDetail } from "./SignalDetail";
import {
  SignalState,
  placeLine,
  signalsUrl,
  strengthTone,
  usePolling,
} from "./SignalCommon";
import {
  countsLine,
  label,
  plural,
  routeBadgeLabels,
  shortTime,
  statusFilters,
  statusLabels,
  strengthFilters,
  strengthLabels,
} from "./signalPresentation";

const MAIN_STRENGTHS = ["critical", "strong", "medium"];
const PAGE = 20;

function split(value: string): string[] {
  return value ? value.split(",") : [];
}

export function SignalsApp({
  client = signalClient,
  companyId,
  openTicket,
}: {
  client?: SignalClient;
  companyId?: string;
  openTicket: (ticketId: string) => void;
}) {
  const [location, setLocation] = useState(window.location.href);
  const route = new URL(location);
  const signalId = route.searchParams.get("signal");
  const house = route.searchParams.get("house") ?? "all";
  const status = statusFilters.some(
    ([id]) => id === route.searchParams.get("status"),
  )
    ? route.searchParams.get("status")!
    : "open";
  const strength = strengthFilters.some(
    ([id]) => id === route.searchParams.get("strength"),
  )
    ? route.searchParams.get("strength")!
    : "any";
  const navigate = useCallback((href: string) => {
    window.history.pushState(null, "", href);
    setLocation(window.location.href);
    window.scrollTo(0, 0);
  }, []);
  useEffect(() => {
    const back = () => setLocation(window.location.href);
    window.addEventListener("popstate", back);
    return () => window.removeEventListener("popstate", back);
  }, []);
  const loadSession = useCallback(
    async (signal: AbortSignal) => {
      const capabilities = await client.capabilities(signal);
      await client.authenticate(capabilities, signal);
      const me = await client.me(signal);
      if (companyId) {
        const scoped = await client.request<{ house_id: string }[]>(
          `/api/v1/companies/${companyId}/houses`,
          { signal },
        );
        me.houses = me.houses.filter((h) =>
          scoped.some((s) => s.house_id === h.id),
        );
      }
      return me;
    },
    [client, companyId],
  );
  const session = useResource("signals-session", loadSession);
  useEffect(() => {
    document.getElementById("page-title")?.focus();
  }, [signalId, Boolean(session.data)]);
  const houses =
    session.data?.houses.filter((h) => h.role !== "resident") ?? [];
  const filters = {
    house: house === "all" ? undefined : house,
    status,
    strength,
  };
  if (signalId)
    return (
      <SignalDetail
        key={signalId}
        id={signalId}
        client={client}
        backHref={signalsUrl({
          house: filters.house,
          status: status === "open" ? undefined : status,
          strength: strength === "any" ? undefined : strength,
        })}
        navigate={navigate}
        openTicket={openTicket}
      />
    );
  const statuses = statusFilters.find(([id]) => id === status)?.[2] ?? [];
  const change = (values: Record<string, string>) => {
    const next = { house, status, strength, ...values };
    navigate(
      signalsUrl({
        house: next.house === "all" ? undefined : next.house,
        status: next.status === "open" ? undefined : next.status,
        strength: next.strength === "any" ? undefined : next.strength,
      }),
    );
  };
  return (
    <>
      <header className="page-header">
        <span className="eyebrow">Домовые чаты</span>
        <h1 id="page-title" tabIndex={-1}>
          Сигналы
        </h1>
        <p className="muted">
          Проблемы, о которых пишут жители. Сигнал не становится заявкой сам —
          решение принимает оператор.
        </p>
      </header>
      {!session.data ? (
        <SignalState
          loading={session.loading}
          error={session.error}
          retry={session.refresh}
        />
      ) : (
        <>
          <div className="signal-filters">
            <label className="house-select">
              Дом
              <select
                value={house}
                onChange={(e) => change({ house: e.target.value })}
              >
                <option value="all">Все доступные дома</option>
                {houses.map((h) => (
                  <option key={h.id} value={h.id}>
                    {h.address}
                  </option>
                ))}
              </select>
            </label>
            <label className="house-select">
              Сила
              <select
                value={strength}
                onChange={(e) => change({ strength: e.target.value })}
              >
                {strengthFilters.map(([id, text]) => (
                  <option key={id} value={id}>
                    {text}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <nav className="queue-filters" aria-label="Статус сигналов">
            {statusFilters.map(([id, text]) => (
              <a
                key={id}
                aria-current={status === id ? "page" : undefined}
                href={signalsUrl({
                  house: filters.house,
                  status: id === "open" ? undefined : id,
                })}
                onClick={(e) => {
                  e.preventDefault();
                  change({ status: id });
                }}
              >
                {text}
              </a>
            ))}
          </nav>
          {houses.length === 0 ? (
            <section className="state-panel">
              <h2>Нет доступной рабочей очереди</h2>
              <p>Назначение отсутствует или доступ отозван.</p>
            </section>
          ) : (
            <SignalQueue
              key={`${house}:${status}:${strength}`}
              client={client}
              house={filters.house}
              statuses={statuses}
              strength={strength}
              showHouse={house === "all" && houses.length > 1}
              navigate={navigate}
            />
          )}
        </>
      )}
    </>
  );
}

function SignalQueue({
  client,
  house,
  statuses,
  strength,
  showHouse,
  navigate,
}: {
  client: SignalClient;
  house?: string;
  statuses: string[];
  strength: string;
  showHouse: boolean;
  navigate: (href: string) => void;
}) {
  const [offset, setOffset] = useState(0);
  // Фильтры — строками: загрузчик стабилен, пока фильтры те же.
  const statusKey = statuses.join(",");
  const strengthKey = strength === "any" ? MAIN_STRENGTHS.join(",") : strength;
  const load = useCallback(
    (signal: AbortSignal) =>
      client.signals(
        {
          house,
          statuses: split(statusKey),
          strengths: split(strengthKey),
          limit: PAGE,
          offset,
        },
        signal,
      ),
    [client, house, statusKey, strengthKey, offset],
  );
  const resource = useResource(`${house}:${offset}`, load);
  usePolling(resource.refresh);
  const data = resource.data;
  if (!data)
    return (
      <SignalState
        loading={resource.loading}
        error={resource.error}
        retry={resource.refresh}
      />
    );
  return (
    <>
      <AttentionBanner data={data} house={house} navigate={navigate} />
      {Boolean(resource.error) && (
        <SignalState error={resource.error} retry={resource.refresh} />
      )}
      <section className="signal-group" aria-labelledby="signals-main-title">
        <div className="section-heading ticket-line">
          <h2 id="signals-main-title">
            {strength === "any"
              ? "Требуют решения"
              : label(strengthLabels, strength, "strength")}
          </h2>
          <span className="muted">
            {data.page.total}{" "}
            {plural(data.page.total, "сигнал", "сигнала", "сигналов")}
          </span>
        </div>
        {data.items.length === 0 ? (
          <section className="state-panel">
            <h3>Сигналов в этом списке нет</h3>
            <p>Когда жители напишут о проблеме, она появится здесь.</p>
          </section>
        ) : (
          <SignalRows
            items={data.items}
            showHouse={showHouse}
            navigate={navigate}
          />
        )}
        <Pagination
          page={data.page}
          count={data.items.length}
          change={setOffset}
          busy={resource.loading}
          label="Страницы сигналов"
        />
      </section>
      {strength === "any" && data.counts.weak > 0 && (
        <WeakGroup
          client={client}
          house={house}
          statuses={statuses}
          count={data.counts.weak}
          showHouse={showHouse}
          navigate={navigate}
        />
      )}
    </>
  );
}

function AttentionBanner({
  data,
  house,
  navigate,
}: {
  data: SignalList;
  house?: string;
  navigate: (href: string) => void;
}) {
  const { count, latest_signal_id: latest, latest_at: at } = data.attention;
  if (!count || !latest) return null;
  const href = signalsUrl({ house, signal: latest });
  return (
    <section className="signal-banner" aria-labelledby="signal-banner-title">
      <h2 id="signal-banner-title">Критические сигналы: {count}</h2>
      <p>
        Жители пишут о признаках опасности. Последний — в {shortTime(at)}.
        Проверьте сигнал первым.
      </p>
      <a
        className="ticket-button"
        href={href}
        onClick={(e) => {
          e.preventDefault();
          navigate(href);
        }}
      >
        Открыть последний критический сигнал
      </a>
    </section>
  );
}

function WeakGroup({
  client,
  house,
  statuses,
  count,
  showHouse,
  navigate,
}: {
  client: SignalClient;
  house?: string;
  statuses: string[];
  count: number;
  showHouse: boolean;
  navigate: (href: string) => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <section
      className="signal-group weak-group"
      aria-labelledby="signals-weak-title"
    >
      <h2 id="signals-weak-title">
        <button
          className="ticket-button secondary"
          aria-expanded={open}
          aria-controls="signals-weak-list"
          onClick={() => setOpen(!open)}
        >
          Возможные ({count})
        </button>
      </h2>
      <p className="muted">
        Из переписки не ясно, что проблема есть сейчас и в этом доме. Их не
        больше лимита на дом в сутки.
      </p>
      <div id="signals-weak-list" hidden={!open}>
        {open && (
          <WeakList
            client={client}
            house={house}
            statuses={statuses}
            showHouse={showHouse}
            navigate={navigate}
          />
        )}
      </div>
    </section>
  );
}

function WeakList({
  client,
  house,
  statuses,
  showHouse,
  navigate,
}: {
  client: SignalClient;
  house?: string;
  statuses: string[];
  showHouse: boolean;
  navigate: (href: string) => void;
}) {
  const [offset, setOffset] = useState(0);
  const statusKey = statuses.join(",");
  const load = useCallback(
    (signal: AbortSignal) =>
      client.signals(
        {
          house,
          statuses: split(statusKey),
          strengths: ["weak"],
          limit: PAGE,
          offset,
        },
        signal,
      ),
    [client, house, statusKey, offset],
  );
  const resource = useResource(`weak:${house}:${offset}`, load);
  usePolling(resource.refresh);
  if (!resource.data)
    return (
      <SignalState
        loading={resource.loading}
        error={resource.error}
        retry={resource.refresh}
      />
    );
  return (
    <>
      <SignalRows
        items={resource.data.items}
        showHouse={showHouse}
        navigate={navigate}
      />
      <Pagination
        page={resource.data.page}
        count={resource.data.items.length}
        change={setOffset}
        busy={resource.loading}
        label="Страницы возможных сигналов"
      />
    </>
  );
}

function SignalRows({
  items,
  showHouse,
  navigate,
}: {
  items: SignalSummary[];
  showHouse: boolean;
  navigate: (href: string) => void;
}) {
  return (
    <ul className="ticket-queue signal-queue" aria-label="Сигналы">
      {items.map((item) => (
        <SignalRow
          key={item.id}
          item={item}
          showHouse={showHouse}
          navigate={navigate}
        />
      ))}
    </ul>
  );
}

function SignalRow({
  item,
  showHouse,
  navigate,
}: {
  item: SignalSummary;
  showHouse: boolean;
  navigate: (href: string) => void;
}) {
  const href = signalsUrl({ signal: item.id });
  const place = placeLine(item);
  const danger = (item.danger_kinds ?? []).length > 0;
  return (
    <li>
      <article
        className={`ticket-row signal-row ${item.strength === "critical" ? "critical" : ""}`}
      >
        <div className="ticket-row-title">
          <div className="signal-badges">
            <span className={`status-badge ${strengthTone(item.strength)}`}>
              {label(strengthLabels, item.strength, "strength")}
            </span>
            {danger && (
              <span className="status-badge tone-attention">Опасность</span>
            )}
            {item.status !== "new" && (
              <span className="status-badge tone-neutral">
                {label(statusLabels, item.status, "signal_status")}
              </span>
            )}
          </div>
          <h3>{item.subtype_label}</h3>
          {showHouse && <p className="muted">{item.house_address}</p>}
          {place && <p>{place}</p>}
          <p className="muted">
            {countsLine(
              item.report_count,
              item.author_count,
              item.last_seen_at,
            )}
          </p>
          {item.first_quote && (
            <blockquote className="signal-quote">
              «{item.first_quote.text}»
              <footer className="muted">
                {item.first_quote.author}, {shortTime(item.first_quote.sent_at)}
              </footer>
            </blockquote>
          )}
        </div>
        <div className="ticket-row-state">
          <p>
            Маршрут:{" "}
            <strong>
              {label(routeBadgeLabels, item.route_type, "route_type")}
            </strong>
          </p>
          {item.route_source === "operator" && (
            <p className="muted">Выбран оператором</p>
          )}
          {item.requires_operator_choice && (
            <p className="muted">Нужен выбор маршрута</p>
          )}
        </div>
        <a
          className="ticket-open"
          href={href}
          aria-label={`Открыть сигнал: ${item.subtype_label}`}
          onClick={(e) => {
            e.preventDefault();
            navigate(href);
          }}
        >
          Открыть <span aria-hidden="true">↗</span>
        </a>
      </article>
    </li>
  );
}
