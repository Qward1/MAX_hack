import { useCallback, useEffect, useState } from "react";
import { type Me } from "../shared/api/client";
import { TicketClient, ticketClient, type Ticket } from "../shared/api/tickets";
import { useResource } from "../shared/api/useResource";
import { categoryLabel, formatDate } from "../features/incidents/presentation";
import {
  Pagination,
  TicketState,
  TicketStatusBadge,
} from "../features/tickets/components";
import { actionLabels, ticketActions } from "../features/tickets/presentation";
import { TicketDetail } from "./TicketDetail";

export function adminUrl(values: Record<string, string | undefined> = {}) {
  const query = new URLSearchParams();
  const testActor = new URLSearchParams(window.location.search).get(
    "test_actor",
  );
  if (testActor) query.set("test_actor", testActor);
  for (const [key, value] of Object.entries(values))
    if (value) query.set(key, value);
  return `/admin/${query.size ? `?${query}` : ""}`;
}
const filters = [
  ["new", "Новые"],
  ["mine", "Мои"],
  ["in_progress", "В работе"],
  ["verification_pending", "На проверке"],
  ["closed", "Закрытые"],
  ["all", "Все"],
];
export function AdminApp({ client = ticketClient }: { client?: TicketClient }) {
  const [location, setLocation] = useState(window.location.href);
  const route = new URL(location);
  const ticket = route.searchParams.get("ticket");
  const house = route.searchParams.get("house") ?? "all";
  const filter = filters.some(([id]) => id === route.searchParams.get("filter"))
    ? route.searchParams.get("filter")!
    : "all";
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
  const load = useCallback(
    async (signal: AbortSignal) => {
      const capabilities = await client.capabilities(signal);
      await client.authenticate(capabilities, signal);
      const me = await client.me(signal);
      return { capabilities, me };
    },
    [client],
  );
  const session = useResource("employee-session", load);
  const [revision, setRevision] = useState(0);
  const refresh = () => {
    session.refresh();
    setRevision((v) => v + 1);
  };
  useEffect(() => {
    document.getElementById("page-title")?.focus();
  }, [ticket, Boolean(session.data)]);
  const me = session.data?.me;
  // Only navigation choices: every list/detail/command is authorized independently by the API.
  const houses = me?.houses.filter((h) => h.role !== "resident") ?? [];
  return (
    <div className="admin-shell">
      <aside className="admin-sidebar">
        <a
          className="admin-brand"
          href={adminUrl()}
          onClick={(e) => {
            e.preventDefault();
            navigate(adminUrl());
          }}
        >
          ДомСигнал<span>Кабинет сотрудника</span>
        </a>
        <nav aria-label="Разделы кабинета">
          <a
            className="admin-nav-link"
            aria-current="page"
            href={adminUrl()}
            onClick={(e) => {
              e.preventDefault();
              navigate(adminUrl());
            }}
          >
            Заявки
          </a>
        </nav>
        <p className="admin-sidebar-note">
          Работа с проблемами дома
          <br />и проверка результата
        </p>
      </aside>
      <main className="app-shell admin-main">
        <div className="toolbar ticket-line">
          <span>{me?.display_name ?? "Кабинет сотрудника"}</span>
          <button
            className="ticket-button secondary"
            disabled={session.loading}
            onClick={refresh}
          >
            Обновить
          </button>
        </div>
        {session.data?.capabilities.environment !== "production" &&
          session.data?.capabilities.features.test_auth && (
            <div className="demo-session">
              <span className="demo-badge">
                Демонстрационные данные · локальная тестовая сессия
              </span>
              <label>
                Участник проверки
                <select
                  aria-label="Участник проверки"
                  value={route.searchParams.get("test_actor") ?? "a16-admin"}
                  onChange={(e) => {
                    window.location.assign(
                      `/admin/?test_actor=${encodeURIComponent(e.target.value)}`,
                    );
                  }}
                >
                  {[
                    ["a16-admin", "Администратор УК"],
                    ["a16-responsible", "Ответственный"],
                    ["a16-operator", "Оператор"],
                    ["a16-revoked", "Отозванный сотрудник"],
                    ["a16-beta-admin", "Другая УК"],
                  ].map(([id, name]) => (
                    <option key={id} value={id}>
                      {name}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          )}
        {!me ? (
          <>
            <header className="page-header">
              <h1 id="page-title" tabIndex={-1}>
                Заявки
              </h1>
            </header>
            <TicketState
              loading={session.loading}
              error={session.error}
              retry={session.refresh}
            />
          </>
        ) : session.error ? (
          <TicketState error={session.error} retry={refresh} />
        ) : ticket ? (
          <TicketDetail
            key={`${me.id}:${ticket}`}
            id={ticket}
            me={me}
            client={client}
            revision={revision}
            navigate={navigate}
          />
        ) : (
          <>
            <header className="page-header">
              <span className="eyebrow">Рабочая очередь</span>
              <h1 id="page-title" tabIndex={-1}>
                Заявки
              </h1>
              <p className="muted">
                От первого сигнала до проверки результата жителями.
              </p>
            </header>
            <label className="house-select">
              Дом
              <select
                value={house}
                onChange={(e) =>
                  navigate(adminUrl({ house: e.target.value, filter }))
                }
              >
                <option value="all">Все доступные дома</option>
                {houses.map((h) => (
                  <option key={h.id} value={h.id}>
                    {h.address}
                  </option>
                ))}
              </select>
            </label>
            <nav className="queue-filters" aria-label="Фильтры заявок">
              {filters.map(([id, label]) => (
                <a
                  key={id}
                  aria-current={filter === id ? "page" : undefined}
                  href={adminUrl({ house, filter: id })}
                  onClick={(e) => {
                    e.preventDefault();
                    navigate(adminUrl({ house, filter: id }));
                  }}
                >
                  {label}
                </a>
              ))}
            </nav>
            {houses.length === 0 && (
              <section className="state-panel">
                <h2>Нет доступной рабочей очереди</h2>
                <p>Назначение отсутствует или доступ отозван.</p>
              </section>
            )}
            {house !== "all" && !houses.some((h) => h.id === house) && (
              <section className="state-panel">
                <p role="alert">Нет доступа к этому дому.</p>
              </section>
            )}
            {houses
              .filter((h) => house === "all" || h.id === house)
              .map((h) => (
                <HouseQueue
                  key={`${me.id}:${h.id}:${filter}`}
                  house={h}
                  me={me.id}
                  client={client}
                  filter={filter}
                  revision={revision}
                  navigate={navigate}
                />
              ))}
          </>
        )}
      </main>
    </div>
  );
}
function HouseQueue({
  client,
  house,
  me,
  filter,
  revision,
  navigate,
}: {
  client: TicketClient;
  house: Me["houses"][number];
  me: string;
  filter: string;
  revision: number;
  navigate: (url: string) => void;
}) {
  const [offset, setOffset] = useState(0);
  const load = useCallback(
    async (signal: AbortSignal) => {
      const tickets = await client.tickets(
        house.id,
        filter,
        me,
        offset,
        signal,
      );
      const incidents = await Promise.all(
        tickets.items.map((t) =>
          client.incident(t.incident_id, signal, house.id),
        ),
      );
      return { tickets, incidents };
    },
    [client, house.id, filter, me, offset],
  );
  const resource = useResource(
    `${house.id}:${filter}:${offset}:${revision}`,
    load,
  );
  const data = resource.data;
  return (
    <section className="house-queue" aria-label={house.address}>
      <div className="section-heading ticket-line">
        <h2>{house.address}</h2>
        {data && (
          <span className="muted">{data.tickets.page.total} заявок</span>
        )}
      </div>
      {!data ? (
        <TicketState
          loading={resource.loading}
          error={resource.error}
          retry={resource.refresh}
        />
      ) : (
        <>
          {Boolean(resource.error) && (
            <TicketState error={resource.error} retry={resource.refresh} />
          )}
          {resource.stale && (
            <p className="refresh-notice">
              Данные могли измениться.{" "}
              <button
                className="ticket-button secondary"
                onClick={resource.refresh}
              >
                Обновить очередь
              </button>
            </p>
          )}
          {data.tickets.items.length === 0 ? (
            <section className="state-panel">
              <h3>Заявок в этом списке пока нет</h3>
              <p>Выберите другой фильтр или обновите очередь.</p>
            </section>
          ) : (
            <ul className="ticket-queue" aria-label="Заявки дома">
              {data.tickets.items.map((t, i) => (
                <TicketRow
                  key={t.id}
                  ticket={t}
                  incident={data.incidents[i]}
                  navigate={navigate}
                />
              ))}
            </ul>
          )}
          <Pagination
            page={data.tickets.page}
            count={data.tickets.items.length}
            change={setOffset}
            busy={resource.loading}
            label={`Страницы заявок: ${house.address}`}
          />
        </>
      )}
    </section>
  );
}
function TicketRow({
  ticket,
  incident,
  navigate,
}: {
  ticket: Ticket;
  incident: Awaited<ReturnType<TicketClient["incident"]>>;
  navigate: (url: string) => void;
}) {
  const next = ticketActions(ticket.allowed_actions).find(
    (a) =>
      a.enabled &&
      ["accept", "start", "work-attempts", "resume"].includes(a.code),
  );
  return (
    <li>
      <article className="ticket-row">
        <div className="ticket-row-title">
          <span className="ticket-number">{ticket.internal_number}</span>
          <h3>{incident.title || categoryLabel(incident.category)}</h3>
          <p className="muted">{categoryLabel(incident.category)}</p>
          {incident.location && (
            <p>
              {[
                incident.location.entrance &&
                  `Подъезд ${incident.location.entrance}`,
                incident.location.floor && `Этаж ${incident.location.floor}`,
                incident.location.label,
              ]
                .filter(Boolean)
                .join(" · ")}
            </p>
          )}
          <p className="muted">
            Сообщений: {incident.report_count} · Участников:{" "}
            {incident.participant_count ?? "нет данных"}
          </p>
        </div>
        <div className="ticket-row-state">
          <TicketStatusBadge status={ticket.status} />
          <p>
            {ticket.assignee_name ??
              (ticket.assignee_id ? "Исполнитель назначен" : "Не назначена")}
          </p>
          <p className="muted">Создана: {formatDate(ticket.created_at)}</p>
          {next && (
            <p className="next-step">
              {next.code === "accept" && !ticket.assignee_id
                ? "Взять в работу"
                : actionLabels[next.code]}
            </p>
          )}
          {ticket.deadlines
            .filter((d) => d.kind === "next_update" && d.due_at)
            .map((d) => (
              <p key={d.id}>Следующее обновление: {formatDate(d.due_at)}</p>
            ))}
        </div>
        <a
          className="ticket-open"
          href={adminUrl({ ticket: ticket.id })}
          aria-label={`Открыть заявку ${ticket.internal_number}`}
          onClick={(e) => {
            e.preventDefault();
            navigate(adminUrl({ ticket: ticket.id }));
          }}
        >
          Открыть <span aria-hidden="true">↗</span>
        </a>
      </article>
    </li>
  );
}
