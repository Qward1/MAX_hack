import { useState } from "react";
import { Feedback, History, OneTimeLink, Status, Title, dateInput, formValue, submitted, useAction, useRead, useRoute, type Schema } from "./administration";

const navigation: Record<string, string> = { applications: "Заявки УК", companies: "Организации",
  "house-management-requests": "Заявки на дома", houses: "Дома", "binding-disputes": "Спорные MAX-привязки", health: "Состояние системы", audit: "Аудит" };
export function PlatformApp() {
  const bootstrap = useRead<Schema["PlatformBootstrap"]>("/api/v1/platform/bootstrap");
  const { url, navigate } = useRoute();
  const page = url.pathname.replace(/^\/platform-admin\/?/, "") || "applications";
  return <div className="admin-shell platform-workspace"><aside className="admin-sidebar">
    <a className="admin-brand" href="/platform-admin/">ДомСигнал<span>Управление платформой</span></a>
    <nav aria-label="Разделы платформы">{!bootstrap.error && bootstrap.data?.surfaces.map(s => <a className="admin-nav-link" key={s}
      href={`/platform-admin/${s}`} aria-current={page === s ? "page" : undefined}
      onClick={e => { e.preventDefault(); navigate(`/platform-admin/${s}`); }}>{navigation[s] ?? s}</a>)}</nav>
    <p className="admin-sidebar-note">Рассмотрение заявок и состояние организаций</p>
  </aside><main className="app-shell admin-main"><Feedback loading={bootstrap.loading} error={bootstrap.error} />
    {bootstrap.data && !bootstrap.error && <><div className="toolbar">{bootstrap.data.display_name}</div>
      <PlatformPage key={page} page={page} /></>}
  </main></div>;
}
function PlatformPage({ page }: { page: string }) {
  if (page === "applications") return <ApplicationReview />;
  if (page === "house-management-requests") return <HouseReview />;
  if (page === "companies") return <PlatformCompanies />;
  if (page === "houses") return <PlatformHouses />;
  if (page === "binding-disputes") return <Disputes />;
  if (page === "health") return <Health />;
  if (page === "audit") return <Audit />;
  return <Title>Раздел не найден</Title>;
}
function ApplicationReview() {
  const [offset, setOffset] = useState(0);
  const r = useRead<Schema["ApplicationView"][]>(`/api/v1/platform/company-applications?offset=${offset}`);
  const [selected, select] = useState<string | null>(null);
  return <><Title description="Заявка не выдаёт аккаунт или доступ. При одобрении создаётся приглашение первого администратора.">Заявки УК</Title>
    <Feedback loading={r.loading} error={r.error} />
    <ul className="admin-records">{r.data?.map(a => <li key={a.id}><button className="record-link" onClick={() => select(a.id)}>{a.legal_name}</button>
      <span>ИНН {a.inn}</span><Status value={a.status} /><time>{new Date(a.submitted_at).toLocaleString("ru-RU")}</time></li>)}</ul>
    <Pages offset={offset} set={setOffset} count={r.data?.length ?? 0} />
    {selected && <ApplicationDetail key={selected} id={selected} refresh={r.refresh} />}</>;
}
function ApplicationDetail({ id, refresh }: { id: string; refresh: () => void }) {
  const r = useRead<Schema["ApplicationView"]>(`/api/v1/platform/company-applications/${id}`);
  const action = useAction(() => { r.refresh(); refresh(); });
  const [link, setLink] = useState("");
  return <section className="admin-detail"><Feedback loading={r.loading} error={r.error ?? action.error} />{r.data && <>
    <h2>{r.data.legal_name}</h2><Status value={r.data.status} />
    <dl className="admin-facts"><dt>ИНН</dt><dd>{r.data.inn}</dd><dt>Контакт</dt><dd>{r.data.contact_name} · {r.data.contact_email} · {r.data.contact_phone}</dd>
      <dt>Комментарий</dt><dd>{r.data.comment ?? "Нет комментария"}</dd></dl>
    {["submitted", "under_review", "needs_info"].includes(r.data.status) && <form className="ticket-form" onSubmit={async e => {
      const data = submitted(e); const verb = (e.nativeEvent as SubmitEvent).submitter?.getAttribute("value");
      if (!verb) return;
      const result = await action.run<Schema["CompanyApproved"] | Schema["ApplicationView"]>(`/api/v1/platform/company-applications/${id}/${verb}`, { reason: formValue(data, "reason") });
      if (result && "invitation" in result) setLink(result.invitation.invitation_url ?? "");
    }}><label>Основание решения / сообщение для заявителя<textarea name="reason" maxLength={2000} required /></label>
      <p className="muted">Уточнения передаются заявителю вручную по указанному контакту. Автоматической отправки нет.</p>
      <div className="button-row"><button className="ticket-button secondary" name="action" value="start-review" disabled={action.busy}>Начать рассмотрение</button>
        <button className="ticket-button secondary" name="action" value="request-info" disabled={action.busy}>Запросить уточнения</button>
        <button className="ticket-button" name="action" value="approve" disabled={action.busy}>Одобрить УК</button>
        <button className="ticket-button secondary" name="action" value="reject" disabled={action.busy}>Отклонить заявку</button></div></form>}
    {link && <OneTimeLink url={link} />}<History rows={r.data.history ?? []} />
  </>}</section>;
}
function HouseReview() {
  const [offset, setOffset] = useState(0);
  const r = useRead<Schema["HouseRequestView"][]>(`/api/v1/platform/house-management-requests?offset=${offset}`);
  const [selected, select] = useState<string | null>(null);
  return <><Title description="Выберите физический дом явно. Пересекающиеся периоды управления недопустимы.">Заявки на дома</Title>
    <Feedback loading={r.loading} error={r.error} /><ul className="admin-records">{r.data?.map(a => <li key={a.id}>
      <button className="record-link" onClick={() => select(a.id)}>{a.requested_address}</button><Status value={a.status} />
      <span>С {new Date(a.requested_valid_from).toLocaleDateString("ru-RU")}</span></li>)}</ul>
    <Pages offset={offset} set={setOffset} count={r.data?.length ?? 0} />
    {selected && <HouseRequestDetail key={selected} id={selected} refresh={r.refresh} />}</>;
}
function HouseRequestDetail({ id, refresh }: { id: string; refresh: () => void }) {
  const r = useRead<Schema["HouseRequestView"]>(`/api/v1/platform/house-management-requests/${id}`);
  const [offset, setOffset] = useState(0);
  const houses = useRead<Schema["PlatformHouseView"][]>(`/api/v1/platform/houses?offset=${offset}`);
  const [resolution, setResolution] = useState("");
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
      } : { reason });
    }}><label>Решение о доме<select value={resolution} onChange={e => setResolution(e.target.value)}>
      <option value="">Выберите решение</option><option value="existing">Использовать существующий дом</option><option value="new">Создать новый дом</option></select></label>
      {resolution === "existing" && <><label>Существующий дом<select name="house" required defaultValue=""><option value="">Выберите дом</option>
        {houses.data?.map(h => <option key={h.id} value={h.id}>{h.address}</option>)}</select></label>
        <Pages offset={offset} set={setOffset} count={houses.data?.length ?? 0} /></>}
      <label>Одобренная дата начала<input type="date" name="date" required defaultValue={dateInput(r.data.requested_valid_from)} /></label>
      <label className="checkbox-label"><input type="checkbox" name="backdate" />Явно подтверждаю прошлую дату на указанном основании</label>
      <label>Основание решения / уточнения<textarea name="reason" required maxLength={2000} /></label>
      <div className="button-row"><button className="ticket-button" value="approve" disabled={action.busy || !resolution}>Одобрить управление</button>
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
    <span>{c.house_count} домов · {c.employee_count} сотрудников · {c.binding_problems} проблем MAX</span></li>)}</ul>
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
function PlatformHouses() {
  const [offset, setOffset] = useState(0);
  const r = useRead<Schema["PlatformHouseView"][]>(`/api/v1/platform/houses?offset=${offset}`);
  return <><Title>Дома</Title><Feedback loading={r.loading} error={r.error} /><ul className="admin-records">{r.data?.map(h => <li key={h.id}>{h.address}<code>{h.id}</code></li>)}</ul><Pages offset={offset} set={setOffset} count={r.data?.length ?? 0} /></>;
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
