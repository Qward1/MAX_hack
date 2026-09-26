import { countLabel, formatStaffTime, formatDay } from "../shared/ui/format";
import { useState } from "react";
import { Feedback, History, OneTimeLink, Status, Title, dateInput, formValue, submitted, useAction, useRead, useRoute, type Schema } from "./administration";
import { QuotaMeter } from "./charts";
import { PlatformOverview } from "./Dashboards";
import { Mailings } from "./CommunityPages";

const navigation: Record<string, string> = { overview: "Обзор", applications: "Заявки УК", "quota-requests": "Запросы квоты", companies: "Организации",
  "house-management-requests": "Заявки на дома", houses: "Дома", "binding-disputes": "Спорные MAX-привязки", health: "Состояние системы", audit: "Аудит",
  mailings: "Сообщения" };
export function PlatformApp() {
  const bootstrap = useRead<Schema["PlatformBootstrap"]>("/api/v1/platform/bootstrap");
  const { url, navigate } = useRoute();
  const page = url.pathname.replace(/^\/platform-admin\/?/, "") || "overview";
  return <div className="admin-shell platform-workspace"><aside className="admin-sidebar">
    <a className="admin-brand" href="/platform-admin/">ДомСигнал<span>Управление платформой</span></a>
    <nav aria-label="Разделы платформы">{!bootstrap.error && bootstrap.data?.surfaces.map(s => <a className="admin-nav-link" key={s}
      href={`/platform-admin/${s}`} aria-current={page === s ? "page" : undefined}
      onClick={e => { e.preventDefault(); navigate(`/platform-admin/${s}`); }}>{navigation[s] ?? s}</a>)}</nav>
    <p className="admin-sidebar-note">Рассмотрение заявок и состояние организаций</p>
  </aside><main className="app-shell admin-main"><Feedback loading={bootstrap.loading} error={bootstrap.error} />
    {bootstrap.data && !bootstrap.error && <><div className="toolbar ticket-line"><span>{bootstrap.data.display_name}</span>
      <button className="ticket-button secondary" onClick={() => window.dispatchEvent(new Event("administration-refresh"))}>Обновить</button></div>
      <PlatformPage key={page} page={page} open={next => navigate(`/platform-admin/${next}`)} /></>}
  </main></div>;
}
function PlatformPage({ page, open }: { page: string; open: (page: string) => void }) {
  if (page === "overview") return <PlatformOverview open={open} />;
  if (page === "quota-requests") return <QuotaRequests />;
  if (page === "applications") return <ApplicationReview />;
  if (page === "house-management-requests") return <HouseReview />;
  if (page === "companies") return <PlatformCompanies />;
  if (page === "houses") return <PlatformHouses />;
  if (page === "binding-disputes") return <Disputes />;
  if (page === "health") return <Health />;
  if (page === "audit") return <Audit />;
  if (page === "mailings") return <Mailings base="" platform />;
  return <Title>Раздел не найден</Title>;
}
function ApplicationReview() {
  const [offset, setOffset] = useState(0);
  const r = useRead<Schema["ApplicationView"][]>(`/api/v1/platform/company-applications?offset=${offset}`);
  const [selected, select] = useState<string | null>(null);
  return <><Title description="Заявка не выдаёт аккаунт или доступ. При одобрении создаётся приглашение первого администратора.">Заявки УК</Title>
    <Feedback loading={r.loading} error={r.error} />
    {r.data?.length === 0 && <p className="state-panel">Заявок пока нет. Их подают на странице «Подключить УК».</p>}
    <ul className="admin-records">{r.data?.map(a => <li key={a.id}><button className="record-link" onClick={() => select(a.id)}>{a.legal_name}</button>
      <span>ИНН {a.inn}</span>{a.requested_chat_count != null && <span>Чатов: {a.requested_chat_count}</span>}<Status value={a.status} />
      {a.inn_conflict && <span className="admin-status status-needs_info">{a.inn_conflict === "company_exists" ? "УК с этим ИНН уже есть" : "Есть другая заявка с этим ИНН"}</span>}
      <time>{formatStaffTime(a.submitted_at)}</time></li>)}</ul>
    <Pages offset={offset} set={setOffset} count={r.data?.length ?? 0} />
    {selected && <ApplicationDetail key={selected} id={selected} refresh={r.refresh} />}</>;
}
function ApplicationDetail({ id, refresh }: { id: string; refresh: () => void }) {
  const r = useRead<Schema["ApplicationView"]>(`/api/v1/platform/company-applications/${id}`);
  const action = useAction(() => { r.refresh(); refresh(); });
  const [link, setLink] = useState("");
  const [unlimited, setUnlimited] = useState(false);
  const a = r.data;
  return <section className="admin-detail"><Feedback loading={r.loading} error={r.error ?? (action.error || undefined)} />{a && <>
    <h2>{a.legal_name}</h2><Status value={a.status} />
    {a.inn_conflict && <p className="admin-feedback">{a.inn_conflict === "company_exists"
      ? "Организация с этим ИНН уже подключена. Вторую УК с тем же ИНН одобрить нельзя."
      : "С этим ИНН есть другая открытая заявка. Одобрить можно только одну."}</p>}
    <dl className="admin-facts"><dt>ИНН</dt><dd>{a.inn}</dd>
      <dt>Контактное лицо</dt><dd>{[a.contact_name, a.contact_position].filter(Boolean).join(", ")}</dd>
      <dt>Связь</dt><dd>{[a.contact_email, a.contact_phone].filter(Boolean).join(", ") || "Не указана"}</dd>
      <dt>Сколько чатов хотят подключить</dt><dd>{a.requested_chat_count ?? "Не указано (заявка до D2)"}</dd>
      <dt>Адреса домов</dt><dd>{a.house_addresses?.length ? <ul className="plain-list">{a.house_addresses.map(h => <li key={h}>{h}</li>)}</ul> : "Не указаны"}</dd>
      <dt>Комментарий</dt><dd>{a.comment ?? "Нет комментария"}</dd>
      {a.status === "approved" && <><dt>Выданная квота чатов</dt><dd>{a.granted_chat_quota ?? "Без ограничения"}</dd></>}</dl>
    {a.messages && a.messages.length > 0 && <><h3>Вопросы и ответы</h3><ol className="message-list">{a.messages.map((m, i) => <li key={i} className={`message-${m.author}`}>
      <strong>{m.author === "platform" ? "Платформа" : "Заявитель"}</strong><time>{formatStaffTime(m.created_at)}</time><p>{m.text}</p></li>)}</ol></>}
    {["submitted", "under_review", "needs_info"].includes(a.status) && <form className="ticket-form" onSubmit={async e => {
      const data = submitted(e); const verb = (e.nativeEvent as SubmitEvent).submitter?.getAttribute("value");
      if (!verb) return;
      const payload: Record<string, unknown> = { reason: formValue(data, "reason") };
      if (verb === "approve") { if (unlimited) payload.unlimited = true; else payload.chat_quota = Number(formValue(data, "quota")); }
      const result = await action.run<Schema["CompanyApproved"] | Schema["ApplicationView"]>(`/api/v1/platform/company-applications/${id}/${verb}`, payload);
      if (result && "invitation" in result && result.invitation) setLink(result.invitation.invitation_url ?? "");
    }}><label>Основание решения / сообщение для заявителя<textarea name="reason" maxLength={2000} required /></label>
      <p className="muted">{a.status_link_issued
        ? "Заявитель видит статус, вопросы и решение на своей странице статуса. После одобрения он сам создаст аккаунт администратора."
        : "Заявка подана до страницы статуса: уточнения передаются заявителю вручную, приглашение появится после одобрения."}</p>
      <fieldset className="quota-fieldset"><legend>Квота чатов при одобрении</legend>
        <label>Сколько домовых чатов может подключить УК<input name="quota" type="number" min={0} max={10000} inputMode="numeric"
          defaultValue={a.requested_chat_count ?? 1} disabled={unlimited} required={!unlimited} /></label>
        <label className="checkbox-label"><input type="checkbox" checked={unlimited} onChange={e => setUnlimited(e.target.checked)} />Без ограничения</label>
        <p className="muted">Если квота отличается от запрошенной, укажите причину в основании решения — заявитель её увидит.</p>
      </fieldset>
      <div className="button-row"><button className="ticket-button secondary" name="action" value="start-review" disabled={action.busy}>Начать рассмотрение</button>
        <button className="ticket-button secondary" name="action" value="request-info" disabled={action.busy}>Запросить уточнения</button>
        <button className="ticket-button" name="action" value="approve" disabled={action.busy}>Одобрить УК</button>
        <button className="ticket-button secondary" name="action" value="reject" disabled={action.busy}>Отклонить заявку</button></div></form>}
    {link && <OneTimeLink url={link} />}<History rows={a.history ?? []} />
  </>}</section>;
}
function HouseReview() {
  const [offset, setOffset] = useState(0);
  const r = useRead<Schema["HouseRequestView"][]>(`/api/v1/platform/house-management-requests?offset=${offset}`);
  const [selected, select] = useState<string | null>(null);
  return <><Title description="Выберите физический дом явно. Пересекающиеся периоды управления недопустимы.">Заявки на дома</Title>
    <Feedback loading={r.loading} error={r.error} /><ul className="admin-records">{r.data?.map(a => <li key={a.id}>
      <button className="record-link" onClick={() => select(a.id)}>{a.requested_address}</button><Status value={a.status} />
      <span>С {formatDay(a.requested_valid_from)}</span></li>)}</ul>
    <Pages offset={offset} set={setOffset} count={r.data?.length ?? 0} />
    {selected && <HouseRequestDetail key={selected} id={selected} refresh={r.refresh} />}</>;
}
function HouseRequestDetail({ id, refresh }: { id: string; refresh: () => void }) {
  const r = useRead<Schema["HouseRequestView"]>(`/api/v1/platform/house-management-requests/${id}`);
  const [offset, setOffset] = useState(0);
  const houses = useRead<Schema["PlatformHouseView"][]>(`/api/v1/platform/houses?offset=${offset}`);
  const [resolution, setResolution] = useState("");
  const [region, setRegion] = useState("");
  const packs = useRead<Schema["RegionPackView"][]>("/api/v1/platform/region-packs");
  const action = useAction(() => { r.refresh(); refresh(); });
  return <section className="admin-detail"><Feedback loading={r.loading} error={r.error ?? action.error} />{r.data && <>
    <h2>{r.data.requested_address}</h2><p>УК: <code>{r.data.company_id}</code></p><p>{r.data.basis_text}</p><Status value={r.data.status} />
    {r.data.candidate_house_id && <p>Возможное совпадение: <code>{r.data.candidate_house_id}</code>. Требуется ваше решение.</p>}
    {["submitted", "under_review", "needs_info"].includes(r.data.status) && <form className="ticket-form" onSubmit={async e => {
      const data = submitted(e); const verb = (e.nativeEvent as SubmitEvent).submitter?.getAttribute("value");
      if (!verb) return;
      const reason = formValue(data, "reason");
      if (verb === "approve" && !resolution) return;
      await action.run(`/api/v1/platform/house-management-requests/${id}/${verb}`, verb === "approve" ? {
        reason, resolution, house_id: resolution === "existing" ? formValue(data, "house") : null,
        valid_from: new Date(`${formValue(data, "date")}T00:00:00`).toISOString(), confirm_backdate: data.get("backdate") === "on",
        ...regionPayload(data),
      } : { reason });
    }}><label>Решение о доме<select value={resolution} onChange={e => setResolution(e.target.value)}>
      <option value="">Выберите решение</option><option value="existing">Использовать существующий дом</option><option value="new">Создать новый дом</option></select></label>
      {resolution === "existing" && <><label>Существующий дом<select name="house" required defaultValue=""><option value="">Выберите дом</option>
        {houses.data?.map(h => <option key={h.id} value={h.id}>{h.address}</option>)}</select></label>
        <Pages offset={offset} set={setOffset} count={houses.data?.length ?? 0} /></>}
      <RegionFields packs={packs.data} region={region} onRegion={setRegion} />
      <label>Одобренная дата начала<input type="date" name="date" required defaultValue={dateInput(r.data.requested_valid_from)} /></label>
      <label className="checkbox-label"><input type="checkbox" name="backdate" />Явно подтверждаю прошлую дату на указанном основании</label>
      <label>Основание решения / уточнения<textarea name="reason" required maxLength={2000} /></label>
      <div className="button-row"><button className="ticket-button" value="approve" disabled={action.busy || !resolution || !region}>Одобрить управление</button>
        <button className="ticket-button secondary" value="start-review" disabled={action.busy}>Начать рассмотрение</button>
        <button className="ticket-button secondary" value="request-info" disabled={action.busy}>Запросить уточнения</button>
        <button className="ticket-button secondary" value="reject" disabled={action.busy}>Отклонить заявку</button></div></form>}
    <History rows={r.data.history ?? []} />
  </>}</section>;
}
function PlatformCompanies() {
  const [offset, setOffset] = useState(0);
  const r = useRead<Schema["CompanyView"][]>(`/api/v1/platform/companies?offset=${offset}`);
  const [selected, select] = useState<string | null>(null);
  return <><Title>Организации</Title><Feedback loading={r.loading} error={r.error} /><ul className="admin-records">{r.data?.map(c => <li key={c.id}>
    <button className="record-link" onClick={() => select(c.id)}>{c.name}</button><Status value={c.status} />
    <span>{countLabel(c.house_count, ["дом", "дома", "домов"])} · {countLabel(c.employee_count, ["сотрудник", "сотрудника", "сотрудников"])} · {countLabel(c.binding_problems, ["проблема с MAX", "проблемы с MAX", "проблем с MAX"])}</span></li>)}</ul>
    <Pages offset={offset} set={setOffset} count={r.data?.length ?? 0} />
    {selected && <PlatformCompany key={selected} id={selected} refresh={r.refresh} />}</>;
}
function PlatformCompany({ id, refresh }: { id: string; refresh: () => void }) {
  const r = useRead<Schema["CompanyView"]>(`/api/v1/platform/companies/${id}`);
  const action = useAction(() => { r.refresh(); refresh(); });
  const [link, setLink] = useState("");
  const [key, setKey] = useState(() => crypto.randomUUID());
  return <section className="admin-detail"><Feedback loading={r.loading} error={r.error ?? action.error} />{r.data && <>
    <h2>{r.data.legal_name ?? r.data.name}</h2><p>ИНН {r.data.inn ?? "не указан"}</p><Status value={r.data.status} />
    <CompanyQuota id={id} refresh={() => { r.refresh(); refresh(); }} />
    <OpenRegistration id={id} active={r.data.status === "active"} />
    <form className="ticket-form" onSubmit={e => { const data = submitted(e);
      void action.run(`/api/v1/platform/companies/${id}/${r.data?.status === "active" ? "suspend" : "reactivate"}`, { reason: formValue(data, "reason") });
    }}><label>Основание<textarea name="reason" required maxLength={2000} /></label>
      <p>Приостановка закрывает рабочий доступ сотрудников и приём приглашений. История сохраняется.</p>
      <button className="ticket-button" disabled={action.busy || r.data.status === "archived"}>{r.data.status === "active" ? "Приостановить организацию" : "Возобновить организацию"}</button></form>
    {r.data.employee_count === 0 && r.data.inn && r.data.status === "active" && <form className="ticket-form" onSubmit={async e => {
      const data = submitted(e);
      const invitation = await action.run<Schema["InvitationView"]>(`/api/v1/platform/companies/${id}/invitations/first-admin`, { reason: formValue(data, "reason") }, key);
      if (invitation) { setLink(invitation.invitation_url ?? ""); setKey(crypto.randomUUID()); }
    }}><h3>Первый администратор</h3><p>Если прежняя ссылка потеряна или истекла, выпустите новую. Старые незавершённые приглашения будут отозваны.</p>
      <label>Причина новой ссылки<textarea name="reason" required maxLength={2000} /></label>
      <button className="ticket-button secondary" disabled={action.busy}>Перевыпустить приглашение первого администратора</button></form>}
    {link && <OneTimeLink url={link} />}
  </>}</section>;
}
export function PlatformHouses() {
  const [offset, setOffset] = useState(0);
  const r = useRead<Schema["PlatformHouseView"][]>(`/api/v1/platform/houses?offset=${offset}`);
  const packs = useRead<Schema["RegionPackView"][]>("/api/v1/platform/region-packs");
  return <><Title>Дома</Title><OpenHouses /><h2>Все дома</h2><Feedback loading={r.loading} error={r.error} /><ul className="admin-records">{r.data?.map(h => <li key={h.id}>{h.address}<code>{h.id}</code>
    {h.region_code ? <span>{[h.region_code, h.municipality_code].filter(Boolean).join(" / ")}</span>
      : <><span className="admin-status status-needs_info">Регион не задан</span><SetRegion house={h.id} packs={packs.data} refresh={r.refresh} /></>}</li>)}</ul>
    <Pages offset={offset} set={setOffset} count={r.data?.length ?? 0} /></>;
}
/** Регион дома из загруженного справочника (D4): каналы, пояс тихих часов и сводки. */
const TERRITORIES: [string, string][] = [["mixed", "Смешанная: двор решает диспетчер"], ["uk", "Двор — зона УК"],
  ["municipal", "Двор — муниципальная территория"], ["unknown", "Не известна"]];
function RegionFields({ packs, region, onRegion }: { packs?: Schema["RegionPackView"][]; region: string; onRegion: (value: string) => void }) {
  const pack = packs?.find(p => p.region_code === region);
  return <fieldset className="quota-fieldset"><legend>Регион дома</legend>
    <label>Регион<select name="region" value={region} onChange={e => onRegion(e.target.value)}><option value="">Выберите регион</option>
      {packs?.map(p => <option key={p.region_code} value={p.region_code}>{p.name} ({p.region_code})</option>)}</select></label>
    {pack && pack.municipalities.length > 0 && <label>Муниципалитет<select name="municipality" key={pack.region_code}>
      {pack.municipalities.map(m => <option key={m.code} value={m.code}>{m.name}</option>)}</select></label>}
    <label>Территория двора<select name="territory" defaultValue="mixed">{TERRITORIES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
    <p className="muted">Регион определяет официальные каналы и часовой пояс тихих часов и сводки. Без региона дом видит только федеральные каналы.</p>
  </fieldset>;
}
function regionPayload(data: FormData) {
  return { region_code: formValue(data, "region") || null, municipality_code: formValue(data, "municipality") || null,
    territory_policy: formValue(data, "territory") || "mixed" };
}
function SetRegion({ house, packs, refresh }: { house: string; packs?: Schema["RegionPackView"][]; refresh: () => void }) {
  const [open, setOpen] = useState(false);
  const [region, setRegion] = useState("");
  const action = useAction(() => { setOpen(false); refresh(); });
  if (!open) return <button type="button" className="ticket-button secondary" onClick={() => setOpen(true)}>Задать регион</button>;
  return <form className="inline-form" onSubmit={e => { const data = submitted(e);
    void action.run(`/api/v1/platform/houses/${house}/region`, { reason: formValue(data, "reason"), ...regionPayload(data) });
  }}><Feedback error={action.error || undefined} /><RegionFields packs={packs} region={region} onRegion={setRegion} />
    <label>Основание<input name="reason" required minLength={3} maxLength={2000} /></label>
    <button className="ticket-button" disabled={action.busy || !region}>Сохранить регион</button>
    <button type="button" className="ticket-button secondary" onClick={() => setOpen(false)}>Отмена</button></form>;
}
/** Дома с открытым доступом: платформа видит все и может закрыть с причиной. */
function OpenHouses() {
  const r = useRead<Schema["PlatformOpenHouseView"][]>("/api/v1/platform/open-houses");
  const action = useAction(r.refresh);
  const [closing, setClosing] = useState<string | null>(null);
  return <section className="admin-detail" aria-labelledby="open-houses-title"><h2 id="open-houses-title">Открытый доступ</h2>
    <Feedback loading={r.loading} error={r.error ?? (action.error || undefined)} />
    {r.data?.length === 0 && <p>Домов с открытым доступом нет.</p>}
    <ul className="admin-records">{r.data?.map(h => <li key={h.house_id}><span>{h.address}</span><span>{h.company_name}</span>
      {h.open_access_changed_at && <time>С {formatStaffTime(h.open_access_changed_at)}</time>}
      {closing !== h.house_id ? <button className="ticket-button secondary" onClick={() => setClosing(h.house_id)}>Закрыть доступ</button>
        : <form className="inline-form" onSubmit={async e => {
          const data = submitted(e);
          const result = await action.run(`/api/v1/platform/houses/${h.house_id}/open-access/close`, { reason: formValue(data, "reason") });
          if (result) setClosing(null);
        }}><label>Причина<input name="reason" required minLength={3} maxLength={500} /></label>
          <button className="ticket-button" disabled={action.busy}>Подтвердить закрытие</button>
          <button type="button" className="ticket-button secondary" onClick={() => setClosing(null)}>Отмена</button></form>}
    </li>)}</ul></section>;
}
function Disputes() {
  const r = useRead<Schema["PlatformBindingView"][]>("/api/v1/platform/binding-disputes");
  return <><Title description="Справочные данные для разбора конфликтов. Обычное подключение выполняет администратор УК.">Спорные MAX-привязки</Title>
    <Feedback loading={r.loading} error={r.error} />{r.data?.length === 0 && <p>Приостановленных и отозванных привязок нет.</p>}
    {r.data?.map(b => <section className="admin-detail" key={b.id}><h2>{b.title ?? "MAX-чат"}</h2><Status value={b.status} /><p>{b.suspension_reason}</p>
      <p>Дом <code>{b.house_id}</code></p><p>Управление <code>{b.management_id}</code></p></section>)}</>;
}
function Health() {
  const r = useRead<Schema["PlatformHealth"]>("/api/v1/platform/health");
  return <><Title>Состояние системы</Title><Feedback loading={r.loading} error={r.error} />{r.data && <dl className="admin-facts">
    <dt>База данных</dt><dd>Доступна</dd><dt>Ожидают обработки</dt><dd>{r.data.pending_jobs}</dd><dt>Ошибки задач</dt><dd>{r.data.failed_jobs}</dd>
    <dt>Ожидают доставки</dt><dd>{r.data.pending_deliveries}</dd></dl>}</>;
}
function Audit() {
  const [offset, setOffset] = useState(0);
  const r = useRead<Schema["AuditView"][]>(`/api/v1/platform/audit?offset=${offset}`);
  return <><Title description="Административные решения и изменения доступа">Аудит</Title><Feedback loading={r.loading} error={r.error} /><History rows={r.data ?? []} />
    <Pages offset={offset} set={setOffset} count={r.data?.length ?? 0} /></>;
}
function Pages({ offset, set, count }: { offset: number; set: (value: number) => void; count: number }) {
  if (!offset && count < 100) return null;
  return <div className="button-row"><button type="button" className="ticket-button secondary" disabled={!offset} onClick={() => set(Math.max(0, offset - 100))}>Предыдущие</button>
    <button type="button" className="ticket-button secondary" disabled={count < 100} onClick={() => set(offset + 100)}>Следующие</button></div>;
}

/** Квота чатов организации: текущее состояние, изменение с причиной, история. */
function CompanyQuota({ id, refresh }: { id: string; refresh: () => void }) {
  const r = useRead<Schema["CompanyQuotaView"]>(`/api/v1/platform/companies/${id}/chat-quota`);
  const action = useAction(() => { r.refresh(); refresh(); });
  const [unlimited, setUnlimited] = useState(false);
  return <section className="quota-panel" aria-labelledby={`quota-${id}`}><h3 id={`quota-${id}`}>Квота чатов</h3>
    <Feedback loading={r.loading} error={r.error ?? (action.error || undefined)} />
    {r.data && <><QuotaMeter quota={r.data.quota} />
      <form className="inline-form" onSubmit={async e => {
        const data = submitted(e);
        await action.run(`/api/v1/platform/companies/${id}/chat-quota`, {
          limit: unlimited ? null : Number(formValue(data, "limit")), reason: formValue(data, "reason") });
      }}><label>Новая квота<input name="limit" type="number" min={0} max={10000} inputMode="numeric" disabled={unlimited} required={!unlimited}
          defaultValue={r.data.quota.limit ?? r.data.quota.used} /></label>
        <label className="checkbox-label"><input type="checkbox" checked={unlimited} onChange={e => setUnlimited(e.target.checked)} />Без ограничения</label>
        <label>Причина<input name="reason" required minLength={3} maxLength={2000} /></label>
        <button className="ticket-button" disabled={action.busy}>Изменить квоту</button></form>
      <p className="muted">Снижение не отключает подключённые чаты: УК будет отмечена как превысившая квоту, новые подключения заблокируются.</p>
      <details><summary>История выдач</summary><ul className="admin-records">{r.data.grants.map((g, i) => <li key={i}>
        <span>{g.limit_after === null || g.limit_after === undefined ? "Без ограничения" : `Квота ${g.limit_after}`}</span>
        <span>{g.reason}</span><time>{formatStaffTime(g.created_at)}</time></li>)}</ul></details></>}
  </section>;
}

/** Открытая регистрация сотрудников УК по публичной ссылке. */
function OpenRegistration({ id, active }: { id: string; active: boolean }) {
  const r = useRead<Schema["OpenRegistrationView"]>(`/api/v1/platform/companies/${id}/open-registration`);
  const action = useAction(r.refresh);
  const [link, setLink] = useState("");
  const enabled = r.data?.enabled === true;
  return <section className="quota-panel" aria-labelledby={`join-${id}`}><h3 id={`join-${id}`}>Открытая регистрация сотрудников</h3>
    <Feedback loading={r.loading} error={r.error ?? (action.error || undefined)} />
    {r.data && <>
      <p>Регистрация по ссылке: <strong>{enabled ? "открыта" : "закрыта"}</strong>
        {r.data.changed_at && <> с {formatStaffTime(r.data.changed_at)}</>}</p>
      <p className="muted">По ссылке человек сам создаёт логин, пароль и второй фактор и становится оператором этой УК на всех её текущих домах.</p>
      <form className="inline-form" onSubmit={async e => {
        const data = submitted(e); const verb = (e.nativeEvent as SubmitEvent).submitter?.getAttribute("value");
        const result = await action.run<Schema["OpenRegistrationView"]>(`/api/v1/platform/companies/${id}/open-registration`,
          { enabled: verb !== "close", reason: formValue(data, "reason") });
        setLink(result?.join_url ?? "");
      }}><label>Причина<input name="reason" required minLength={3} maxLength={2000} /></label>
        {active && <button className="ticket-button" value="open" disabled={action.busy}>{enabled ? "Выпустить новую ссылку" : "Открыть регистрацию"}</button>}
        {enabled && <button className="ticket-button secondary" value="close" disabled={action.busy}>Закрыть регистрацию</button>}
      </form>
      {link && <OneTimeLink url={link} title="Ссылка регистрации сотрудников" label="Ссылка регистрации" />}
      <h4>Зарегистрировались по ссылке</h4>
      {(r.data.employees ?? []).length === 0 ? <p className="muted">Пока никого.</p> :
        <ul className="admin-records">{(r.data.employees ?? []).map(e => <li key={e.user_id}><span>{e.display_name}</span><span>{e.login_name}</span>
          <Status value={e.status} />{e.registered_at && <time>{formatStaffTime(e.registered_at)}</time>}</li>)}</ul>}
    </>}
  </section>;
}

/** Запросы УК на расширение квоты: одобрить полностью, частично или отклонить. */
function QuotaRequests() {
  const [all, setAll] = useState(false);
  const r = useRead<Schema["ChatQuotaRequestView"][]>(`/api/v1/platform/chat-quota-requests?pending=${all ? "false" : "true"}`);
  return <><Title description="Решение меняет квоту УК сразу; причина видна администратору УК">Запросы на расширение квоты</Title>
    <label className="checkbox-label"><input type="checkbox" checked={all} onChange={e => setAll(e.target.checked)} />Показать и рассмотренные</label>
    <Feedback loading={r.loading} error={r.error} />
    {r.data?.length === 0 && <p className="state-panel">{all ? "Запросов пока не было." : "Запросов, ждущих решения, нет."}</p>}
    {r.data?.map(q => <QuotaRequest key={q.id} request={q} refresh={r.refresh} />)}</>;
}
function QuotaRequest({ request, refresh }: { request: Schema["ChatQuotaRequestView"]; refresh: () => void }) {
  const action = useAction(refresh);
  return <section className="admin-detail"><h2>{request.company_name ?? "УК"}: +{request.requested_delta}</h2><Status value={request.status} />
    {request.quota && <QuotaMeter quota={request.quota} />}
    <p>{request.reason}</p><time>{formatStaffTime(request.created_at)}</time>
    {request.decision_reason && <p className="muted">Решение: {request.decision_reason}{request.granted_delta ? ` (выдано +${request.granted_delta})` : ""}</p>}
    <Feedback error={action.error || undefined} />
    {request.status === "pending" && <form className="ticket-form" onSubmit={async e => {
      const data = submitted(e); const verb = (e.nativeEvent as SubmitEvent).submitter?.getAttribute("value");
      await action.run(`/api/v1/platform/chat-quota-requests/${request.id}/decide`, {
        granted_delta: verb === "reject" ? 0 : Number(formValue(data, "granted")), reason: formValue(data, "reason") });
    }}><label>Сколько выдать<input name="granted" type="number" min={1} max={request.requested_delta} defaultValue={request.requested_delta} inputMode="numeric" /></label>
      <label>Причина решения<textarea name="reason" required minLength={3} maxLength={2000} /></label>
      <div className="button-row"><button className="ticket-button" value="approve" disabled={action.busy}>Одобрить</button>
        <button className="ticket-button secondary" value="reject" disabled={action.busy}>Отклонить</button></div></form>}
  </section>;
}
