import { useCallback, useEffect, useState } from "react";
import { type Me } from "../shared/api/client";
import { TicketClient, ticketClient, type Ticket } from "../shared/api/tickets";
import { useResource } from "../shared/api/useResource";
import { categoryLabel } from "../features/incidents/presentation";
import { placeText } from "../features/incidents/IncidentCard";
import { Pagination, TicketState, TicketStatusBadge } from "../features/tickets/components";
import { actionLabels, ticketActions } from "../features/tickets/presentation";
import { countLabel, formatStaffWhen } from "../shared/ui/format";
import { TicketDetail } from "./TicketDetail";

export function adminUrl(values: Record<string, string | undefined> = {}) {
  const query = new URLSearchParams();
  const company = new URLSearchParams(window.location.search).get("company");
  if (company) query.set("company", company);
  const testActor = new URLSearchParams(window.location.search).get("test_actor");
  if (testActor) query.set("test_actor", testActor);
  for (const [key, value] of Object.entries(values)) if (value) query.set(key, value);
  return `/admin/${query.size ? `?${query}` : ""}`;
}

/** Широкий экран: список и деталь стоят рядом, очередь не теряется. */
export function useWide(query = "(min-width: 1200px)") {
  const read = () => typeof window.matchMedia === "function" && window.matchMedia(query).matches;
  const [wide, setWide] = useState(read);
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const media = window.matchMedia(query);
    const change = () => setWide(media.matches);
    media.addEventListener?.("change", change);
    return () => media.removeEventListener?.("change", change);
  }, [query]);
  return wide;
}

const TICKETS = ["заявка", "заявки", "заявок"] as const;
const filters = [
  ["new", "Новые"],
  ["mine", "Мои"],
  ["in_progress", "В работе"],
  ["verification_pending", "Ждут проверки жителями"],
  ["closed", "Закрытые"],
  ["all", "Все"],
];
export function AdminApp({ client = ticketClient, embedded = false, companyId }: { client?: TicketClient; embedded?: boolean; companyId?: string }) {
  const [location, setLocation] = useState(window.location.href);
  const route = new URL(location);
  const ticket = route.searchParams.get("ticket");
  const house = route.searchParams.get("house") ?? "all";
  const filter = filters.some(([id]) => id === route.searchParams.get("filter")) ? route.searchParams.get("filter")! : "all";
  const wide = useWide();
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
  const load = useCallback(
    async (signal: AbortSignal) => {
      const capabilities = await client.capabilities(signal);
      await client.authenticate(capabilities, signal);
      const me = await client.me(signal);
      if (companyId) {
        const scoped = await client.request<{ house_id: string }[]>(`/api/v1/companies/${companyId}/houses`, { signal });
        me.houses = me.houses.filter((h) => scoped.some((s) => s.house_id === h.id));
      }
      return { capabilities, me };
    },
    [client, companyId],
  );
  const session = useResource("employee-session", load);
  const [revision, setRevision] = useState(0);
  const refresh = () => {
    session.refresh();
    setRevision((v) => v + 1);
  };
  useEffect(() => {
    const refresh = () => {
      session.refresh();
      setRevision((v) => v + 1);
    };
    window.addEventListener("administration-refresh", refresh);
    return () => window.removeEventListener("administration-refresh", refresh);
  }, [session.refresh]);
  useEffect(() => {
    document.getElementById("page-title")?.focus();
  }, [ticket, Boolean(session.data)]);
  const me = session.data?.me;
  // Only navigation choices: every list/detail/command is authorized independently by the API.
  const houses = me?.houses.filter((h) => h.role !== "resident") ?? [];
  // Возврат из детали сохраняет фильтры очереди: они в адресе.
  const queueHref = adminUrl({ house: house === "all" ? undefined : house, filter: filter === "all" ? undefined : filter });
  const queue = me && (
    <>
      {!(ticket && wide) && (
        <header className="page-header">
          <h1 id="page-title" tabIndex={-1}>
            Заявки
          </h1>
          <p className="ds-subtle">Заявки жителей по вашим домам: кто исполнитель и на каком этапе работа.</p>
        </header>
      )}
      {ticket && wide && <h2 className="ds-visually-hidden">Очередь заявок</h2>}
      <div className="queue-toolbar">
        <label className="house-select">
          Дом
          <select value={house} onChange={(e) => navigate(adminUrl({ house: e.target.value, filter, ticket: ticket ?? undefined }), true)}>
            <option value="all">Все доступные дома</option>
            {houses.map((h) => (
              <option key={h.id} value={h.id}>
                {h.address}
              </option>
            ))}
          </select>
        </label>
      </div>
      <nav className="queue-filters" aria-label="Фильтры заявок">
        {filters.map(([id, label]) => (
          <a
            key={id}
            aria-current={filter === id ? "page" : undefined}
            href={adminUrl({ house, filter: id })}
            onClick={(e) => {
              e.preventDefault();
              navigate(adminUrl({ house, filter: id, ticket: ticket ?? undefined }), true);
            }}
          >
            {label}
          </a>
        ))}
      </nav>
      {houses.length === 0 && (
        <section className="ds-state">
          <h2>Нет доступной рабочей очереди</h2>
          <p>Назначения на дома нет или доступ отозван. Доступ выдаёт администратор управляющей компании.</p>
        </section>
      )}
      {house !== "all" && !houses.some((h) => h.id === house) && (
        <section className="ds-state">
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
            current={ticket}
            compact={Boolean(ticket && wide)}
            open={(id) => navigate(adminUrl({ house: house === "all" ? undefined : house, filter: filter === "all" ? undefined : filter, ticket: id }), wide)}
          />
        ))}
    </>
  );
  const detail = me && ticket && (
    <TicketDetail
      key={`${me.id}:${ticket}`}
      id={ticket}
      me={me}
      client={client}
      revision={revision}
      navigate={navigate}
      backHref={queueHref}
      inPanel={wide}
    />
  );
  return (
    <div className={embedded ? "ticket-workspace" : "admin-shell"}>
      {!embedded && (
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
          <p className="admin-sidebar-note">Работа с проблемами дома и проверка результата</p>
        </aside>
      )}
      <div className={embedded ? "ticket-workspace-main" : "app-shell admin-main"}>
        {!embedded && (
          <div className="admin-toolbar">
            <span>{me?.display_name ?? "Кабинет сотрудника"}</span>
            <button className="ds-btn ds-btn-secondary" disabled={session.loading} onClick={refresh}>
              Обновить
            </button>
          </div>
        )}
        {!me ? (
          <>
            <header className="page-header">
              <h1 id="page-title" tabIndex={-1}>
                Заявки
              </h1>
            </header>
            <TicketState loading={session.loading} error={session.error} retry={session.refresh} />
          </>
        ) : session.error ? (
          <TicketState error={session.error} retry={refresh} />
        ) : (
          // Одна структура при любой ширине: смена «широкий/узкий» не пересоздаёт
          // деталь заявки и не закрывает открытый диалог действия.
          <div className={ticket && wide ? "split" : undefined}>
            {(!ticket || wide) && (
              <section
                className={ticket && wide ? "split-list" : undefined}
                aria-label={ticket && wide ? "Очередь заявок" : undefined}
              >
                {queue}
              </section>
            )}
            {ticket && (
              <section
                className={wide ? "split-detail" : undefined}
                aria-label={wide ? "Заявка" : undefined}
              >
                {detail}
              </section>
            )}
          </div>
        )}
        {/* Выбор участника — только для локального стенда; внизу, чтобы не определять рабочую компоновку. */}
        {session.data?.capabilities.environment !== "production" &&
          route.searchParams.has("test_actor") &&
          session.data?.capabilities.features.test_auth && (
            <div className="demo-session">
              <span className="demo-badge">Локальный стенд · вход без пароля</span>
              <label>
                Участник проверки
                <select
                  aria-label="Участник проверки"
                  value={route.searchParams.get("test_actor") ?? "a16-admin"}
                  onChange={(e) => {
                    window.location.assign(`/admin/?test_actor=${encodeURIComponent(e.target.value)}`);
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
      </div>
    </div>
  );
}
function HouseQueue({
  client,
  house,
  me,
  filter,
  revision,
  current,
  compact,
  open,
}: {
  client: TicketClient;
  house: Me["houses"][number];
  me: string;
  filter: string;
  revision: number;
  current: string | null;
  compact: boolean;
  open: (id: string) => void;
}) {
  const [offset, setOffset] = useState(0);
  const load = useCallback(
    async (signal: AbortSignal) => {
      const tickets = await client.tickets(house.id, filter, me, offset, signal);
      const incidents = await Promise.all(tickets.items.map((t) => client.incident(t.incident_id, signal, house.id)));
      return { tickets, incidents };
    },
    [client, house.id, filter, me, offset],
  );
  const resource = useResource(`${house.id}:${filter}:${offset}:${revision}`, load);
  const data = resource.data;
  return (
    <section className="house-queue" aria-label={house.address}>
      <div className="ticket-line">
        <h2>{house.address}</h2>
        {data && <span className="ds-meta">{countLabel(data.tickets.page.total, TICKETS)}</span>}
      </div>
      {!data ? (
        <TicketState loading={resource.loading} error={resource.error} retry={resource.refresh} missing="Очередь этого дома больше недоступна: управление домом или ваше назначение изменились." />
      ) : (
        <>
          {Boolean(resource.error) && <TicketState error={resource.error} retry={resource.refresh} missing="Очередь этого дома больше недоступна: управление домом или ваше назначение изменились." />}
          {resource.stale && (
            <div className="refresh-notice" role="status">
              <span>Данные могли измениться.</span>
              <button className="ds-btn ds-btn-secondary ds-btn-small" onClick={resource.refresh}>
                Обновить очередь
              </button>
            </div>
          )}
          {data.tickets.items.length === 0 ? (
            <p className="ds-subtle">Заявок в этом списке нет. Выберите другой фильтр или обновите очередь.</p>
          ) : (
            <table className="queue-table" aria-label={`Заявки: ${house.address}`}>
              <thead>
                <tr>
                  <th scope="col">Заявка</th>
                  <th scope="col">Проблема</th>
                  <th scope="col">Статус</th>
                  <th scope="col" className="col-wide">
                    Исполнитель
                  </th>
                  <th scope="col" className="col-wide">
                    Создана
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.tickets.items.map((t, i) => (
                  <TicketRow
                    key={t.id}
                    ticket={t}
                    incident={data.incidents[i]}
                    current={t.id === current}
                    compact={compact}
                    open={open}
                  />
                ))}
              </tbody>
            </table>
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
  current,
  compact,
  open,
}: {
  ticket: Ticket;
  incident: Awaited<ReturnType<TicketClient["incident"]>>;
  current: boolean;
  compact: boolean;
  open: (id: string) => void;
}) {
  const next = ticketActions(ticket.allowed_actions).find(
    (a) => a.enabled && ["accept", "start", "work-attempts", "resume"].includes(a.code),
  );
  const place = placeText(incident.location);
  const href = adminUrl({ ticket: ticket.id });
  const nextUpdate = ticket.deadlines.find((d) => d.kind === "next_update" && d.due_at);
  return (
    <tr
      aria-current={current || undefined}
      className="is-clickable"
      onClick={(e) => {
        // Мышь: вся строка открывает заявку. Клавиатура и экранный диктор — ссылка в названии.
        if ((e.target as HTMLElement).closest("a, button") || window.getSelection()?.toString()) return;
        open(ticket.id);
      }}
    >
      <td className="cell-id" data-label="Заявка">
        {ticket.internal_number}
      </td>
      <td className="cell-main">
        <a
          href={href}
          aria-label={`Открыть заявку ${ticket.internal_number}: ${incident.title || categoryLabel(incident.category)}`}
          onClick={(e) => {
            if (e.ctrlKey || e.metaKey || e.shiftKey || e.button !== 0) return;
            e.preventDefault();
            open(ticket.id);
          }}
        >
          {incident.title || categoryLabel(incident.category)}
        </a>
        <p className="ds-meta">
          {[categoryLabel(incident.category), place, countLabel(incident.report_count, ["сообщение", "сообщения", "сообщений"])]
            .filter(Boolean)
            .join(" · ")}
        </p>
      </td>
      <td data-label="Статус">
        <TicketStatusBadge status={ticket.status} />
        {next && !compact && (
          <p className="ds-meta">
            Дальше: {next.code === "accept" && !ticket.assignee_id ? "взять в работу" : actionLabels[next.code].toLowerCase()}
          </p>
        )}
      </td>
      <td className="col-wide" data-label="Исполнитель">
        {ticket.assignee_name ?? (ticket.assignee_id ? "Назначен" : <span className="ds-subtle">Не назначен</span>)}
        {ticket.requires_reassignment && <p className="ds-meta">Нужно переназначить</p>}
      </td>
      <td className="col-wide cell-when" data-label="Создана">
        {formatStaffWhen(ticket.created_at)}
        {nextUpdate && <p>Обновление: {formatStaffWhen(nextUpdate.due_at)}</p>}
      </td>
    </tr>
  );
}
