import { useCallback, useEffect, useRef, useState } from "react";
import { AdminApp } from "./AdminApp";
import { SignalsApp } from "./SignalsApp";
import { adminClient, Feedback, Title, useRoute, type Schema } from "./administration";
import { useResource } from "../shared/api/useResource";
import type { SignalList } from "../shared/api/signals";
import { ChatConnections, CompanyHouses, MyHouses, Organization, Staff } from "./CompanyPages";
import { CompanyOverview } from "./Dashboards";
import { Mailings, Notices, ReceptionAdmin } from "./CommunityPages";
import { Sheet } from "../shared/ui/ChoicePicker";
import { IconMenu } from "../shared/ui/icons";

type Context = Schema["CompanyContext"];
const names: Record<string, string> = { overview: "Обзор", tickets: "Заявки", signals: "Сигналы", houses: "Дома",
  assigned_houses: "Мои дома", staff: "Сотрудники", chat_connections: "MAX-чаты", organization: "Организация",
  mailings: "Рассылки", notices: "Уведомления", reception: "Приём" };
const paths: Record<string, string> = { overview: "", tickets: "tickets", signals: "signals", houses: "houses",
  assigned_houses: "houses", staff: "staff", chat_connections: "max", organization: "organization",
  mailings: "mailings", notices: "notices", reception: "reception" };
// Очередь сигналов живёт в query-навигации, как заявки: ?section=signals&signal=<id>.
const isSignalsRoute = (url: URL) => url.searchParams.get("section") === "signals" || url.searchParams.has("signal");
const COUNTS_MS = 60000;
/** Рабочие разделы, которые на телефоне стоят в первом ряду; остальные — в меню «Разделы». */
const PRIORITY = ["tickets", "signals"];

type Counts = { signals?: number; critical?: number; tickets?: number };

/**
 * Счётчики задач в меню: новые сигналы (из них критические) и новые заявки.
 * Это `page.total` настоящих запросов очереди, а не расчёт во frontend.
 * Сбой счётчика не мешает работе — счётчик просто не показывается.
 */
function useQueueCounts(company: Context | undefined): Counts {
  const [counts, setCounts] = useState<Counts>({});
  const surfaces = company?.surfaces.join(",") ?? "";
  useEffect(() => {
    if (!company) return;
    let active = true;
    const controller = new AbortController();
    const read = async () => {
      const next: Counts = {};
      try {
        if (surfaces.includes("signals")) {
          const list = await adminClient.request<SignalList>(
            "/api/v1/signals?limit=1&offset=0&status=new&status=in_review&strength=critical&strength=strong&strength=medium",
            { signal: controller.signal, silentAccess: true });
          next.signals = list.page.total;
          next.critical = list.attention.count;
        }
        if (surfaces.includes("tickets")) {
          // Только дома, где у сотрудника есть рабочая роль: чужой дом — 403, а он сбросил бы сессию кабинета.
          const [scoped, me] = await Promise.all([
            adminClient.request<{ house_id: string }[]>(`/api/v1/companies/${company.company_id}/houses`,
              { signal: controller.signal, silentAccess: true }),
            adminClient.request<{ houses: { id: string; role: string }[] }>("/api/v1/me", { signal: controller.signal, silentAccess: true }),
          ]);
          const houses = scoped.filter(s => me.houses.some(h => h.id === s.house_id && h.role !== "resident"));
          // Много домов — много запросов: счётчик только там, где это дёшево.
          if (houses.length <= 12) {
            const pages = await Promise.all(houses.map(h => adminClient.request<{ page: { total: number } }>(
              `/api/v1/tickets?house_id=${encodeURIComponent(h.house_id)}&status=new&limit=1&offset=0`,
              { signal: controller.signal, silentAccess: true })));
            next.tickets = pages.reduce((sum, page) => sum + page.page.total, 0);
          }
        }
      } catch {
        /* Счётчик необязателен. */
      }
      if (active) setCounts(next);
    };
    void read();
    const timer = window.setInterval(() => { if (document.visibilityState === "visible") void read(); }, COUNTS_MS);
    const refresh = () => void read();
    window.addEventListener("administration-refresh", refresh);
    return () => { active = false; controller.abort(); window.clearInterval(timer); window.removeEventListener("administration-refresh", refresh); };
  }, [company?.company_id, surfaces]);
  return counts;
}

function NavCount({ id, value, danger, label }: { id: string; value?: number; danger?: number; label: string }) {
  if (!value) return null;
  return <>
    <span className={`nav-count${danger ? " is-danger" : ""}`} aria-hidden="true">{value}</span>
    <span id={id} className="ds-visually-hidden">{label}: {value}{danger ? `, критических: ${danger}` : ""}</span>
  </>;
}

export function CompanyPortal() {
  const { url, navigate: go } = useRoute();
  // Каждый переход портала (меню, ссылка в другой раздел, Back) заново
  // открывает раздел; перерисовка по другой причине — нет: форма решения,
  // начатая в разделе, не теряется, когда портал обновляет свой bootstrap.
  const [visit, setVisit] = useState(0);
  const navigate = (href: string) => { go(href); setVisit(v => v + 1); };
  useEffect(() => { const back = () => setVisit(v => v + 1);
    window.addEventListener("popstate", back); return () => window.removeEventListener("popstate", back); }, []);
  const load = useCallback(async (signal: AbortSignal) => {
    const caps = await adminClient.capabilities(signal);
    await adminClient.authenticate(caps, signal);
    return adminClient.request<Schema["AdminBootstrap"]>("/api/v1/admin/bootstrap", { signal });
  }, []);
  const bootstrap = useResource("company-contexts", load);
  useEffect(() => { const refresh = () => bootstrap.refresh();
    window.addEventListener("focus", refresh); return () => window.removeEventListener("focus", refresh); }, [bootstrap.refresh]);
  const companies = bootstrap.error ? [] : bootstrap.data?.companies ?? [];
  const selector = url.searchParams.get("company");
  const selected = selector ? companies.find(c => c.company_id === selector) : companies.length === 1 ? companies[0] : undefined;
  const counts = useQueueCounts(selected);
  const href = (surface: string, company = selected?.company_id) => {
    const query = new URLSearchParams(); if (company) query.set("company", company);
    const actor = url.searchParams.get("test_actor"); if (actor) query.set("test_actor", actor);
    if (surface === "signals") { query.set("section", "signals"); return `/admin/?${query}`; }
    return `/admin/${paths[surface] ?? surface}?${query}`;
  };
  // Ссылка из оповещения ведёт к сигналу и после выбора компании.
  const signalHref = (company: string) => {
    const target = new URL(href("signals", company), window.location.origin);
    const signal = url.searchParams.get("signal"); if (signal) target.searchParams.set("signal", signal);
    return `${target.pathname}${target.search}`;
  };
  const route = url.pathname.replace(/^\/admin\/?/, "");
  const surface = route ? Object.keys(paths).find(k => paths[k] === route && selected?.surfaces.includes(k as Context["surfaces"][number])) ?? route
    : isSignalsRoute(url) ? "signals"
    : url.searchParams.has("ticket") || url.searchParams.has("house") || url.searchParams.has("filter") ? "tickets"
    : selected?.surfaces[0] ?? "tickets";
  if (!selected) return <main className="admin-main auth-layout"><section className="auth-card">
    <Title description={companies.length > 1 ? "Вы сотрудник нескольких управляющих компаний. Сменить компанию можно в меню кабинета." : undefined}>
      {companies.length ? "Выберите управляющую компанию" : "Нет доступной рабочей очереди"}</Title>
    <Feedback loading={bootstrap.loading} error={bootstrap.error} />
    {selector && !bootstrap.loading && <p role="alert" className="ds-error">Выбранная организация недоступна.</p>}
    {companies.length === 0 && !bootstrap.loading && <p>Активных назначений нет. Доступ к домам выдаёт администратор вашей управляющей компании.</p>}
    <div className="ds-stack">
      {companies.map(c => <button className="ds-btn ds-btn-secondary ds-btn-stretched" key={c.company_id} onClick={() => navigate(isSignalsRoute(url) && c.surfaces.includes("signals")
        ? signalHref(c.company_id) : href(c.surfaces[0], c.company_id))}>{c.name}</button>)}
      <button className="ds-btn ds-btn-quiet" onClick={bootstrap.refresh}>Проверить доступ</button>
    </div>
  </section></main>;
  const isOrganization = selected.surfaces.includes("staff");
  const shared = { company: selected, surface, href, navigate, visit };
  const countFor = (s: string) => s === "signals"
    ? <NavCount id={`count-${s}`} value={counts.signals} danger={counts.critical} label="новых сигналов" />
    : s === "tickets" ? <NavCount id={`count-${s}`} value={counts.tickets} label="новых заявок" /> : null;
  const described = (s: string) => (s === "signals" && counts.signals) || (s === "tickets" && counts.tickets) ? `count-${s}` : undefined;
  const refreshAll = () => { bootstrap.refresh(); window.dispatchEvent(new Event("administration-refresh")); };
  return <div className={`admin-shell has-mobile-nav ${isOrganization ? "company-workspace" : "operator-workspace"}`}>
    <MobileNavigation company={selected} companies={companies} surface={surface} counts={counts} href={href}
      navigate={navigate} displayName={bootstrap.data?.display_name} refresh={refreshAll}
      title={isOrganization ? "Управление компанией" : "Рабочее место оператора"} />
    <aside className="admin-sidebar"><a className="admin-brand" href={href(selected.surfaces[0])}>ДомСигнал
      <span>{isOrganization ? "Управление компанией" : "Рабочее место оператора"}</span></a>
      {companies.length > 1 && <label>Управляющая компания<select aria-label="Управляющая компания" value={selected.company_id}
        onChange={e => { const company = companies.find(c => c.company_id === e.target.value); if (company) navigate(href(company.surfaces[0], company.company_id)); }}>
        {companies.map(c => <option key={c.company_id} value={c.company_id}>{c.name}</option>)}</select></label>}
      <nav aria-label="Разделы кабинета">{selected.surfaces.map(s => <a key={s} className="admin-nav-link"
        aria-current={s === surface ? "page" : undefined} aria-describedby={described(s)} href={href(s)}
        onClick={e => { e.preventDefault(); navigate(href(s)); }}><span>{names[s]}</span>{countFor(s)}</a>)}</nav>
      <p className="admin-sidebar-note">{selected.name}</p>
    </aside><main className="app-shell admin-main"><div className="admin-toolbar"><span>{bootstrap.data?.display_name}</span>
      <button className="ds-btn ds-btn-secondary" onClick={refreshAll}>Обновить</button></div>
      {isOrganization ? <CompanyWorkspace key={selected.company_id} {...shared} /> : <OperatorWorkspace key={selected.company_id} {...shared} />}
    </main>
  </div>;
}
/**
 * Телефон: короткая шапка вместо трёх рядов разделов. Рабочие разделы
 * («Заявки», «Сигналы») и текущий раздел — в первом ряду, все остальные —
 * в листе «Разделы». Названия и доступ те же, что в боковом меню компьютера.
 */
function MobileNavigation({ company, companies, surface, counts, href, navigate, displayName, refresh, title }: {
  company: Context; companies: Context[]; surface: string; counts: Counts; href: (surface: string, company?: string) => string;
  navigate: (href: string) => void; displayName?: string; refresh: () => void; title: string;
}) {
  const [open, setOpen] = useState(false);
  const button = useRef<HTMLButtonElement>(null);
  const quick = company.surfaces.filter(s => PRIORITY.includes(s) || s === surface);
  const count = (s: string) => s === "signals" ? counts.signals : s === "tickets" ? counts.tickets : undefined;
  const link = (s: string, onPick?: () => void) => {
    const value = count(s);
    const danger = s === "signals" && counts.critical;
    return <a key={s} className="admin-nav-link" aria-current={s === surface ? "page" : undefined} href={href(s)}
      onClick={e => { e.preventDefault(); onPick?.(); navigate(href(s)); }}>
      <span>{names[s]}</span>
      {value ? <><span className={`nav-count${danger ? " is-danger" : ""}`} aria-hidden="true">{value}</span>
        <span className="ds-visually-hidden">, новых: {value}{danger ? `, критических: ${danger}` : ""}</span></> : null}
    </a>;
  };
  return <>
    <header className="admin-mobile-bar">
      <a className="admin-brand" href={href(company.surfaces[0])} onClick={e => { e.preventDefault(); navigate(href(company.surfaces[0])); }}>
        ДомСигнал<span>{title}</span></a>
      <button type="button" className="ds-icon-button" aria-label="Обновить" title="Обновить" onClick={refresh}>
        <span aria-hidden="true">↻</span></button>
      <button ref={button} type="button" className="ds-btn ds-btn-secondary admin-menu-button" aria-haspopup="dialog"
        aria-expanded={open} onClick={() => setOpen(true)}><IconMenu />Разделы</button>
    </header>
    <nav className="admin-quick-nav" aria-label="Рабочие разделы">{quick.map(s => link(s))}</nav>
    {open && <Sheet title="Разделы кабинета" anchor={button.current} className="admin-drawer" focus="[aria-current=page]"
      closeLabel="Закрыть" onClose={() => setOpen(false)}>
      {displayName && <p className="ds-meta">{displayName} · {company.name}</p>}
      {companies.length > 1 && <label className="ds-field">Управляющая компания<select value={company.company_id}
        onChange={e => { const next = companies.find(c => c.company_id === e.target.value); if (next) { setOpen(false); navigate(href(next.surfaces[0], next.company_id)); } }}>
        {companies.map(c => <option key={c.company_id} value={c.company_id}>{c.name}</option>)}</select></label>}
      <nav className="admin-drawer-nav" aria-label="Все разделы">{company.surfaces.map(s => link(s, () => setOpen(false)))}</nav>
    </Sheet>}
  </>;
}
type Workspace = { company: Context; surface: string; href: (surface: string) => string; navigate: (url: string) => void; visit: number };
function openTicket(navigate: (url: string) => void, href: (surface: string) => string) {
  return (ticketId: string) => {
    const target = new URL(href("tickets"), window.location.origin);
    target.pathname = "/admin/"; target.searchParams.set("ticket", ticketId);
    navigate(`${target.pathname}${target.search}`);
  };
}
function CompanyWorkspace({ company, surface, href, navigate, visit }: Workspace) {
  const base = `/api/v1/companies/${company.company_id}`;
  switch (surface) {
    case "overview": return <CompanyOverview base={base} links={overviewLinks(company, href, navigate)} />;
    case "tickets": return <AdminApp key={visit} embedded companyId={company.company_id} />;
    case "signals": return <SignalsApp key={visit} companyId={company.company_id} openTicket={openTicket(navigate, href)} />;
    case "houses": return <CompanyHouses base={base} />;
    case "staff": return <Staff base={base} />;
    case "chat_connections": return <ChatConnections base={base} />;
    case "organization": return <Organization base={base} />;
    case "mailings": return <Mailings key={visit} base={base} />;
    case "notices": return <Notices base={base} />;
    case "reception": return <ReceptionAdmin base={base} admin />;
    default: return <DeniedRoute base={base} surface={surface} />;
  }
}
function OperatorWorkspace({ company, surface, href, navigate, visit }: Workspace) {
  const base = `/api/v1/companies/${company.company_id}`;
  if (surface === "tickets") return <AdminApp key={visit} embedded companyId={company.company_id} />;
  if (surface === "signals") return <SignalsApp key={visit} companyId={company.company_id} openTicket={openTicket(navigate, href)} />;
  if (surface === "assigned_houses") return <MyHouses base={base} />;
  if (surface === "overview") return <CompanyOverview base={base} links={overviewLinks(company, href, navigate)} />;
  if (surface === "chat_connections" && company.surfaces.includes("chat_connections"))
    return <ChatConnections base={base} canRequest={false} />;
  if (surface === "mailings" && company.surfaces.includes("mailings")) return <Mailings key={visit} base={base} />;
  if (surface === "notices") return <Notices base={base} />;
  if (surface === "reception") return <ReceptionAdmin base={base} admin={false} />;
  return <DeniedRoute base={base} surface={surface} />;
}
/** Переходы из пустого обзора — только в разделы, доступные этой роли. */
function overviewLinks(company: Context, href: (surface: string) => string, navigate: (url: string) => void) {
  return {
    tickets: company.surfaces.includes("tickets") ? href("tickets") : undefined,
    signals: company.surfaces.includes("signals") ? href("signals") : undefined,
    navigate,
  };
}
function DeniedRoute({ base, surface }: { base: string; surface: string }) {
  // A typed URL is still checked by the endpoint; navigation isn't the access boundary.
  const load = useCallback((signal: AbortSignal) => adminClient.request(`${base}/${surface === "staff" ? "staff" : "organization"}`, { signal }), [base, surface]);
  const result = useResource(`${base}:${surface}`, load);
  return <><Title description="Раздел доступен другой роли. Доступ выдаёт администратор управляющей компании.">Раздел недоступен</Title>
    <Feedback loading={result.loading} error={result.error} /></>;
}
