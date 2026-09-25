import { useCallback, useEffect, useState } from "react";
import { signalClient, type SignalClient, type SignalList, type SignalSummary } from "../shared/api/signals";
import { useResource } from "../shared/api/useResource";
import { Pagination } from "../features/tickets/components";
import { dangerLabel } from "../features/routing/presentation";
import { countLabel, formatStaffWhen } from "../shared/ui/format";
import { StatusTag } from "../shared/ui/semantic";
import { signalStrength, statusOf } from "../shared/ui/status";
import { useWide } from "./AdminApp";
import { SignalDetail } from "./SignalDetail";
import { SignalState, placeLine, signalsUrl, usePolling } from "./SignalCommon";
import {
  countsLine,
  label,
  routeBadgeLabels,
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
  const status = statusFilters.some(([id]) => id === route.searchParams.get("status"))
    ? route.searchParams.get("status")!
    : "open";
  const strength = strengthFilters.some(([id]) => id === route.searchParams.get("strength"))
    ? route.searchParams.get("strength")!
    : "any";
  const wide = useWide();
  // Порядок очереди — чтобы после решения предложить следующий сигнал.
  const [order, setOrder] = useState<string[]>([]);
  const navigate = useCallback((href: string, keepScroll = false) => {
    window.history.pushState(null, "", href);
    setLocation(window.location.href);
    if (!keepScroll) window.scrollTo(0, 0);
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
        const scoped = await client.request<{ house_id: string }[]>(`/api/v1/companies/${companyId}/houses`, { signal });
        me.houses = me.houses.filter((h) => scoped.some((s) => s.house_id === h.id));
      }
      return me;
    },
    [client, companyId],
  );
  const session = useResource("signals-session", loadSession);
  useEffect(() => {
    document.getElementById("page-title")?.focus();
  }, [signalId, Boolean(session.data)]);
  const houses = session.data?.houses.filter((h) => h.role !== "resident") ?? [];
  const filters = { house: house === "all" ? undefined : house, status, strength };
  const queueParams = {
    house: filters.house,
    status: status === "open" ? undefined : status,
    strength: strength === "any" ? undefined : strength,
  };
  const backHref = signalsUrl(queueParams);
  const openSignal = (id: string) => navigate(signalsUrl({ ...queueParams, signal: id }), wide);
  const position = signalId ? order.indexOf(signalId) : -1;
  const nextId = signalId ? (order.slice(position + 1).find((id) => id !== signalId) ?? order.find((id) => id !== signalId)) : undefined;
  const nextHref = nextId ? signalsUrl({ ...queueParams, signal: nextId }) : null;
  // Деталь читается только после входа: в тестовой сессии токен выдаёт тот
  // же запрос сессии, а по ссылке из оповещения страница открывается сразу.
  if (signalId && !session.data)
    return <SignalState loading={session.loading} error={session.error} retry={session.refresh} />;
  const detail = signalId && (
    <SignalDetail
      key={signalId}
      id={signalId}
      client={client}
      backHref={backHref}
      nextHref={nextHref}
      inPanel={wide}
      navigate={(href) => navigate(href, false)}
      openTicket={openTicket}
    />
  );
  if (signalId && !wide) return detail;
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
  const queue = (
    <>
      {signalId ? (
        <h2 className="ds-visually-hidden">Очередь сигналов</h2>
      ) : (
        <header className="page-header">
          <h1 id="page-title" tabIndex={-1}>
            Сигналы
          </h1>
          <p className="ds-subtle">
            Проблемы, о которых жители пишут в домовых чатах. Сигнал не становится заявкой сам — решение принимает
            оператор.
          </p>
        </header>
      )}
      {!session.data ? (
        <SignalState loading={session.loading} error={session.error} retry={session.refresh} />
      ) : (
        <>
          <div className="signal-filters">
            <label className="house-select">
              Дом
              <select value={house} onChange={(e) => change({ house: e.target.value })}>
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
              <select value={strength} onChange={(e) => change({ strength: e.target.value })}>
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
                href={signalsUrl({ house: filters.house, status: id === "open" ? undefined : id })}
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
            <section className="ds-state">
              <h2>Нет доступной рабочей очереди</h2>
              <p>Назначения на дома нет или доступ отозван. Доступ выдаёт администратор управляющей компании.</p>
            </section>
          ) : (
            <SignalQueue
              key={`${house}:${status}:${strength}`}
              client={client}
              house={filters.house}
              statuses={statuses}
              strength={strength}
              showHouse={house === "all" && houses.length > 1 && !signalId}
              compact={Boolean(signalId)}
              current={signalId}
              open={openSignal}
              onOrder={setOrder}
            />
          )}
        </>
      )}
    </>
  );
  if (signalId)
    return (
      <div className="split">
        <section className="split-list" aria-label="Очередь сигналов">
          {queue}
        </section>
        <section className="split-detail" aria-label="Сигнал">
          {detail}
        </section>
      </div>
    );
  return queue;
}

function SignalQueue({
  client,
  house,
  statuses,
  strength,
  showHouse,
  compact,
  current,
  open,
  onOrder,
}: {
  client: SignalClient;
  house?: string;
  statuses: string[];
  strength: string;
  showHouse: boolean;
  compact: boolean;
  current: string | null;
  open: (id: string) => void;
  onOrder: (ids: string[]) => void;
}) {
  const [offset, setOffset] = useState(0);
  // Фильтры — строками: загрузчик стабилен, пока фильтры те же.
  const statusKey = statuses.join(",");
  const strengthKey = strength === "any" ? MAIN_STRENGTHS.join(",") : strength;
  const load = useCallback(
    (signal: AbortSignal) =>
      client.signals({ house, statuses: split(statusKey), strengths: split(strengthKey), limit: PAGE, offset }, signal),
    [client, house, statusKey, strengthKey, offset],
  );
  const resource = useResource(`${house}:${offset}`, load);
  usePolling(resource.refresh);
  const data = resource.data;
  const ids = data?.items.map((item) => item.id).join(",") ?? "";
  useEffect(() => {
    if (ids) onOrder(ids.split(","));
  }, [ids, onOrder]);
  if (!data) return <SignalState loading={resource.loading} error={resource.error} retry={resource.refresh} />;
  return (
    <>
      <AttentionBanner data={data} open={open} />
      {Boolean(resource.error) && <SignalState error={resource.error} retry={resource.refresh} />}
      <section className="signal-group" aria-labelledby="signals-main-title">
        <div className="ticket-line">
          <h2 id="signals-main-title">
            {strength === "any" ? "Требуют решения" : label(strengthLabels, strength, "strength")}
          </h2>
          <span className="ds-meta">{countLabel(data.page.total, ["сигнал", "сигнала", "сигналов"])}</span>
        </div>
        {data.items.length === 0 ? (
          <p className="ds-subtle">Сигналов в этом списке нет. Когда жители напишут о проблеме, она появится здесь.</p>
        ) : (
          <SignalRows items={data.items} showHouse={showHouse} compact={compact} current={current} open={open} />
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
          compact={compact}
          current={current}
          open={open}
        />
      )}
    </>
  );
}

function AttentionBanner({ data, open }: { data: SignalList; open: (id: string) => void }) {
  const { count, latest_signal_id: latest, latest_at: at } = data.attention;
  if (!count || !latest) return null;
  return (
    <section className="signal-banner" aria-labelledby="signal-banner-title">
      <h2 id="signal-banner-title">Критические сигналы: {count}</h2>
      <p>
        Жители пишут о признаках опасности. Последний — {formatStaffWhen(at)}. Проверьте его первым.
      </p>
      <a
        className="ds-btn ds-btn-primary"
        href={signalsUrl({ signal: latest })}
        onClick={(e) => {
          e.preventDefault();
          open(latest);
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
  compact,
  current,
  open,
}: {
  client: SignalClient;
  house?: string;
  statuses: string[];
  count: number;
  showHouse: boolean;
  compact: boolean;
  current: string | null;
  open: (id: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  return (
    <section className="signal-group weak-group" aria-labelledby="signals-weak-title">
      <h2 id="signals-weak-title">
        <button
          className="ds-btn ds-btn-secondary"
          aria-expanded={expanded}
          aria-controls="signals-weak-list"
          onClick={() => setExpanded(!expanded)}
        >
          Возможные ({count})
        </button>
      </h2>
      <p className="ds-subtle">
        Из переписки не ясно, что проблема есть сейчас и в этом доме. Их не больше лимита на дом в сутки.
      </p>
      <div id="signals-weak-list" hidden={!expanded}>
        {expanded && (
          <WeakList
            client={client}
            house={house}
            statuses={statuses}
            showHouse={showHouse}
            compact={compact}
            current={current}
            open={open}
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
  compact,
  current,
  open,
}: {
  client: SignalClient;
  house?: string;
  statuses: string[];
  showHouse: boolean;
  compact: boolean;
  current: string | null;
  open: (id: string) => void;
}) {
  const [offset, setOffset] = useState(0);
  const statusKey = statuses.join(",");
  const load = useCallback(
    (signal: AbortSignal) =>
      client.signals({ house, statuses: split(statusKey), strengths: ["weak"], limit: PAGE, offset }, signal),
    [client, house, statusKey, offset],
  );
  const resource = useResource(`weak:${house}:${offset}`, load);
  usePolling(resource.refresh);
  if (!resource.data) return <SignalState loading={resource.loading} error={resource.error} retry={resource.refresh} />;
  return (
    <>
      <SignalRows items={resource.data.items} showHouse={showHouse} compact={compact} current={current} open={open} />
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
  compact,
  current,
  open,
}: {
  items: SignalSummary[];
  showHouse: boolean;
  compact: boolean;
  current: string | null;
  open: (id: string) => void;
}) {
  return (
    <table className="queue-table signal-queue" aria-label="Сигналы">
      <thead>
        <tr>
          <th scope="col">Сила</th>
          <th scope="col">Что и где</th>
          <th scope="col" className="col-wide">
            Маршрут
          </th>
          <th scope="col" className="col-wide">
            Сколько и когда
          </th>
        </tr>
      </thead>
      <tbody>
        {items.map((item) => (
          <SignalRow key={item.id} item={item} showHouse={showHouse} compact={compact} current={item.id === current} open={open} />
        ))}
      </tbody>
    </table>
  );
}

function SignalRow({
  item,
  showHouse,
  compact,
  current,
  open,
}: {
  item: SignalSummary;
  showHouse: boolean;
  compact: boolean;
  current: boolean;
  open: (id: string) => void;
}) {
  const place = placeLine(item);
  const dangers = (item.danger_kinds ?? []).map((kind) => (dangerLabel(kind) ?? "другой признак").toLowerCase());
  return (
    <tr className={item.strength === "critical" ? "row-danger" : undefined} aria-current={current || undefined}>
      <td data-label="Сила">
        <div className="signal-badges">
          <StatusTag entry={statusOf(signalStrength, item.strength)} />
          {item.status !== "new" && (
            <StatusTag entry={{ label: label(statusLabels, item.status, "signal_status"), tone: "neutral" }} />
          )}
        </div>
      </td>
      <td className="cell-main">
        <a
          href={signalsUrl({ signal: item.id })}
          aria-label={`Открыть сигнал: ${item.subtype_label}`}
          onClick={(e) => {
            if (e.ctrlKey || e.metaKey || e.shiftKey || e.button !== 0) return;
            e.preventDefault();
            open(item.id);
          }}
        >
          {item.subtype_label}
        </a>
        {dangers.length > 0 && <p className="ds-error">Опасность: {dangers.join(", ")}</p>}
        {showHouse && <p className="ds-meta">{item.house_address}</p>}
        {place && <p>{place}</p>}
        {item.first_quote && !compact && (
          <blockquote className="signal-quote">
            «{item.first_quote.text}»
            <footer>
              {item.first_quote.author}, {formatStaffWhen(item.first_quote.sent_at)}
            </footer>
          </blockquote>
        )}
      </td>
      <td className="col-wide" data-label="Маршрут">
        <strong>{label(routeBadgeLabels, item.route_type, "route_type")}</strong>
        {item.route_source === "operator" && <p className="ds-meta">Выбран оператором</p>}
        {item.requires_operator_choice && <p className="ds-meta">Нужен выбор маршрута</p>}
      </td>
      <td className="col-wide cell-when" data-label="Сколько и когда">
        {countsLine(item.report_count, item.author_count, item.last_seen_at)}
      </td>
    </tr>
  );
}
