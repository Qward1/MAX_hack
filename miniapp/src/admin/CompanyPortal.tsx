import { useCallback, useEffect, useState } from "react";
import { AdminApp } from "./AdminApp";
import { SignalsApp } from "./SignalsApp";
import { adminClient, Feedback, Title, useRoute, type Schema } from "./administration";
import { useResource } from "../shared/api/useResource";
import { ChatConnections, CompanyHouses, MyHouses, Organization, Staff } from "./CompanyPages";
import { CompanyOverview } from "./Dashboards";

type Context = Schema["CompanyContext"];
const names: Record<string, string> = { overview: "Обзор", tickets: "Заявки", signals: "Сигналы", houses: "Дома",
  assigned_houses: "Мои дома", staff: "Сотрудники", chat_connections: "MAX-чаты", organization: "Организация" };
const paths: Record<string, string> = { overview: "", tickets: "tickets", signals: "signals", houses: "houses",
  assigned_houses: "houses", staff: "staff", chat_connections: "max", organization: "organization" };
// Очередь сигналов живёт в query-навигации, как заявки: ?section=signals&signal=<id>.
const isSignalsRoute = (url: URL) => url.searchParams.get("section") === "signals" || url.searchParams.has("signal");

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
  if (!selected) return <main className="admin-main"><Title>{companies.length ? "Выберите управляющую компанию" : "Нет доступной рабочей очереди"}</Title>
    <Feedback loading={bootstrap.loading} error={bootstrap.error} />
    {selector && !bootstrap.loading && <p role="alert">Выбранная организация недоступна.</p>}
    {companies.length === 0 && !bootstrap.loading && <p>Активных назначений нет. Обратитесь к администратору вашей УК.</p>}
    {companies.map(c => <button className="ticket-button" key={c.company_id} onClick={() => navigate(isSignalsRoute(url) && c.surfaces.includes("signals")
      ? signalHref(c.company_id) : href(c.surfaces[0], c.company_id))}>{c.name}</button>)}
    <button className="ticket-button secondary" onClick={bootstrap.refresh}>Проверить доступ</button>
  </main>;
  const isOrganization = selected.surfaces.includes("staff");
  const shared = { company: selected, surface, href, navigate, visit };
  return <div className={`admin-shell ${isOrganization ? "company-workspace" : "operator-workspace"}`}>
    <aside className="admin-sidebar"><a className="admin-brand" href={href(selected.surfaces[0])}>ДомСигнал
      <span>{isOrganization ? "Управление компанией" : "Рабочее место оператора"}</span></a>
      {companies.length > 1 && <label>Управляющая компания<select aria-label="Управляющая компания" value={selected.company_id}
        onChange={e => { const company = companies.find(c => c.company_id === e.target.value); if (company) navigate(href(company.surfaces[0], company.company_id)); }}>
        {companies.map(c => <option key={c.company_id} value={c.company_id}>{c.name}</option>)}</select></label>}
      <nav aria-label="Разделы кабинета">{selected.surfaces.map(s => <a key={s} className="admin-nav-link"
        aria-current={s === surface ? "page" : undefined} href={href(s)} onClick={e => { e.preventDefault(); navigate(href(s)); }}>{names[s]}</a>)}</nav>
      <p className="admin-sidebar-note">{selected.name}</p>
    </aside><main className="app-shell admin-main"><div className="toolbar ticket-line"><span>{bootstrap.data?.display_name}</span>
      <button className="ticket-button secondary" onClick={() => { bootstrap.refresh(); window.dispatchEvent(new Event("administration-refresh")); }}>Обновить</button></div>
      {isOrganization ? <CompanyWorkspace key={selected.company_id} {...shared} /> : <OperatorWorkspace key={selected.company_id} {...shared} />}
    </main>
  </div>;
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
    case "overview": return <CompanyOverview base={base} />;
    case "tickets": return <AdminApp key={visit} embedded companyId={company.company_id} />;
    case "signals": return <SignalsApp key={visit} companyId={company.company_id} openTicket={openTicket(navigate, href)} />;
    case "houses": return <CompanyHouses base={base} />;
    case "staff": return <Staff base={base} />;
    case "chat_connections": return <ChatConnections base={base} />;
    case "organization": return <Organization base={base} />;
    default: return <DeniedRoute base={base} surface={surface} />;
  }
}
function OperatorWorkspace({ company, surface, href, navigate, visit }: Workspace) {
  const base = `/api/v1/companies/${company.company_id}`;
  if (surface === "tickets") return <AdminApp key={visit} embedded companyId={company.company_id} />;
  if (surface === "signals") return <SignalsApp key={visit} companyId={company.company_id} openTicket={openTicket(navigate, href)} />;
  if (surface === "assigned_houses") return <MyHouses base={base} />;
  if (surface === "overview") return <CompanyOverview base={base} />;
  if (surface === "chat_connections" && company.surfaces.includes("chat_connections"))
    return <ChatConnections base={base} canRequest={false} />;
  return <DeniedRoute base={base} surface={surface} />;
}
function DeniedRoute({ base, surface }: { base: string; surface: string }) {
  // A typed URL is still checked by the endpoint; navigation isn't the access boundary.
  const load = useCallback((signal: AbortSignal) => adminClient.request(`${base}/${surface === "staff" ? "staff" : "organization"}`, { signal }), [base, surface]);
  const result = useResource(`${base}:${surface}`, load);
  return <><Title>Раздел недоступен</Title><Feedback loading={result.loading} error={result.error} /></>;
}
