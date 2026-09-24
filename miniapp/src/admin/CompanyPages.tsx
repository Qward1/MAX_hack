import { useState } from "react";
import { Feedback, History, OneTimeLink, Status, Title, dateInput, formValue, submitted, useAction, useRead, type Schema } from "./administration";

type House = Schema["CompanyHouseView"];
export function Organization({ base }: { base: string }) {
  const r = useRead<Schema["CompanyView"]>(`${base}/organization`);
  return <><Title>Организация</Title><Feedback loading={r.loading} error={r.error} />{!r.error && r.data &&
    <dl className="admin-facts"><dt>Полное наименование</dt><dd>{r.data.legal_name ?? r.data.name}</dd>
      <dt>ИНН</dt><dd>{r.data.inn ?? "Не указан"}</dd><dt>Статус</dt><dd><Status value={r.data.status} /></dd>
      <dt>Контакт</dt><dd>{[r.data.contact_name, r.data.contact_email, r.data.contact_phone].filter(Boolean).join(" · ") || "Не указан"}</dd>
    </dl>}</>;
}
export function Overview({ base }: { base: string }) {
  const r = useRead<Schema["CompanyOverview"]>(`${base}/overview`);
  const names: Record<string, string> = { open_tickets: "Открытых заявок", unassigned_tickets: "Без исполнителя",
    verification_pending: "На проверке жителями", house_count: "Домов в управлении", active_employees: "Сотрудников", binding_problems: "Проблем с MAX" };
  return <><Title description="Текущая работа вашей управляющей компании">Обзор</Title><Feedback loading={r.loading} error={r.error} />
    {!r.error && r.data && <dl className="overview-grid">{Object.entries(r.data).map(([k, v]) => <div key={k}><dt>{names[k]}</dt><dd>{v}</dd></div>)}</dl>}</>;
}
export function Staff({ base }: { base: string }) {
  const people = useRead<Schema["MembershipView"][]>(`${base}/staff`);
  const invitations = useRead<Schema["InvitationView"][]>(`${base}/employee-invitations`);
  const houses = useRead<House[]>(`${base}/houses`);
  const [selected, setSelected] = useState<string | null>(null);
  const [link, setLink] = useState("");
  const [inviteKey, setInviteKey] = useState(() => crypto.randomUUID());
  const action = useAction(() => { people.refresh(); invitations.refresh(); });
  return <><Title description="Приглашения и доступ к домам вашей УК">Сотрудники</Title>
    <Feedback loading={people.loading} error={people.error ?? action.error} />
    {!people.error && <><form className="inline-form" onSubmit={async e => {
      const data = submitted(e);
      const result = await action.run<Schema["InvitationView"]>(`${base}/employee-invitations`,
        { organization_role: formValue(data, "role") }, inviteKey);
      if (result) { setLink(result.invitation_url ?? ""); setInviteKey(crypto.randomUUID()); }
    }}><label>Роль сотрудника<select name="role"><option value="operator">Оператор</option><option value="company_admin">Администратор УК</option></select></label>
      <button className="ticket-button" disabled={action.busy}>Пригласить сотрудника</button></form>
      {link && <OneTimeLink url={link} />}
      <ul className="admin-records">{people.data?.map(p => <li key={p.user_id}>
        <button className="record-link" onClick={() => setSelected(p.user_id)}>{p.display_name}</button>
        <span>{p.role === "company_admin" ? "Администратор УК" : "Оператор"}</span><Status value={p.status} />
      </li>)}</ul>
      {selected && <StaffAssignments key={selected} user={selected} base={base} houses={houses.data ?? []} refresh={people.refresh} />}
      <h2>Приглашения</h2><Feedback error={invitations.error} />
      <ul className="admin-records">{invitations.data?.map(inv => <li key={inv.id}>
        <span>{inv.organization_role === "company_admin" ? "Администратор УК" : "Оператор"}</span><Status value={inv.status} />
        <time>До {new Date(inv.expires_at).toLocaleString("ru-RU")}</time>
        {["pending", "claimed"].includes(inv.status) && <button className="ticket-button secondary" disabled={action.busy}
          onClick={() => void action.run(`${base}/employee-invitations/${inv.id}/revoke`)}>Отозвать приглашение</button>}
      </li>)}</ul></>}
  </>;
}
function StaffAssignments({ base, user, houses, refresh }: { base: string; user: string; houses: House[]; refresh: () => void }) {
  const r = useRead<Schema["StaffDetail"]>(`${base}/staff/${user}`);
  const [confirm, setConfirm] = useState(false);
  const action = useAction(() => { r.refresh(); refresh(); });
  return <section className="admin-detail"><h2>{r.data?.display_name ?? "Сотрудник"}</h2><Feedback loading={r.loading} error={r.error ?? action.error} />
    {r.data && !r.error && <><p><Status value={r.data.status} /></p>
      {r.data.status === "active" && <><h3>Доступ к домам</h3>
        {houses.length === 0 && <p>Сначала запросите управление домом в разделе «Дома».</p>}
        {houses.map(h => <label className="assignment-row" key={h.management_id}>{h.address}
          <select aria-label={`Доступ: ${h.address}`} disabled={action.busy}
            value={r.data?.assignments.find(a => a.management_id === h.management_id)?.role ?? "none"}
            onChange={e => void action.run(`${base}/staff/${user}/assignments`, { management_id: h.management_id, role: e.target.value === "none" ? null : e.target.value })}>
            <option value="none">Нет доступа</option><option value="operator">Оператор</option><option value="responsible">Ответственный</option>
          </select></label>)}
        <p className="muted">Администратор УК имеет доступ ко всем текущим домам своей организации. Назначение ответственного определяет работу с заявками дома.</p>
        {!confirm ? <button className="ticket-button secondary" onClick={() => setConfirm(true)}>Отозвать доступ сотрудника</button> :
          <div className="admin-feedback"><p>Сотрудник потеряет доступ к этой УК. Его незакрытые заявки вернутся в очередь без исполнителя.</p>
            <button className="ticket-button" disabled={action.busy} onClick={() => void action.run(`${base}/staff/${user}/revoke`)}>Подтвердить отзыв</button>
            <button className="ticket-button secondary" onClick={() => setConfirm(false)}>Отмена</button></div>}
      </>}
    </>}
  </section>;
}
export function MyHouses({ base }: { base: string }) {
  const r = useRead<House[]>(`${base}/houses`);
  return <><Title description="Дома, на которые вы назначены">Мои дома</Title><Feedback loading={r.loading} error={r.error} />
    {!r.error && <HouseList houses={r.data ?? []} />}</>;
}
export function HouseList({ houses }: { houses: House[] }) {
  return houses.length ? <div className="house-cards">{houses.map(h => <section className="admin-detail" key={h.management_id}>
    <h2>{h.address}</h2><p>Управление с {new Date(h.valid_from).toLocaleDateString("ru-RU")}{h.valid_to && ` до ${new Date(h.valid_to).toLocaleDateString("ru-RU")}`}</p>
    <p>{h.open_ticket_count} открытых заявок · {h.operator_count} операторов · {h.responsible_count} ответственных</p>
    {h.warning && <p className="admin-feedback">{h.warning}</p>}
    <h3>Подключение MAX</h3>{!h.bindings.length && <p className="muted">Чат пока не подключён</p>}
    {h.bindings.map(b => <p key={b.id}>{b.title ?? "MAX-чат"} · <Status value={b.status} />{b.suspension_reason && ` · ${b.suspension_reason}`}
      {b.status === "active" && b.passive_capture_enabled != null && ` · Чтение чата: ${b.passive_capture_enabled ? "включено" : "выключено"}`}</p>)}
  </section>)}</div> : <p className="state-panel">Доступных домов пока нет.</p>;
}
export function CompanyHouses({ base }: { base: string }) {
  const houses = useRead<House[]>(`${base}/houses`);
  const requests = useRead<Schema["HouseRequestView"][]>(`${base}/house-management-requests`);
  const [show, setShow] = useState(false);
  const [key, setKey] = useState(() => crypto.randomUUID());
  const action = useAction(requests.refresh);
  return <><Title description="Действующее управление и заявки на подключение домов">Дома</Title>
    <button className="ticket-button" onClick={() => setShow(!show)}>Запросить управление домом</button>
    {show && <form className="ticket-form admin-detail" onSubmit={async e => {
      const data = submitted(e);
      const result = await action.run(`${base}/house-management-requests`, { requested_address: formValue(data, "address"),
        requested_valid_from: new Date(`${formValue(data, "date")}T00:00:00`).toISOString(), basis_text: formValue(data, "basis") }, key);
      if (result) { setShow(false); setKey(crypto.randomUUID()); }
    }}><label>Адрес<input name="address" required minLength={5} maxLength={500} /></label>
      <label>Дата начала управления<input name="date" type="date" required defaultValue={dateInput(new Date())} /></label>
      <label>Основание и комментарий<textarea name="basis" required maxLength={2000} /></label>
      <p className="muted">Доступ к дому появится после решения платформы. Совпадение адреса не подтверждает управление.</p>
      <button className="ticket-button" disabled={action.busy}>Подать заявку на управление</button></form>}
    <Feedback loading={houses.loading} error={houses.error ?? requests.error ?? action.error} />
    {!houses.error && <HouseList houses={houses.data ?? []} />}
    <h2>Заявки на управление</h2>{requests.data?.map(r => <section className="admin-detail" key={r.id}>
      <h3>{r.requested_address}</h3><Status value={r.status} /><p>{r.decision_reason}</p><History rows={r.history ?? []} />
    </section>)}
  </>;
}
export function ChatConnections({ base }: { base: string }) {
  const houses = useRead<House[]>(`${base}/houses`);
  const capabilities = useRead<Schema["CapabilitiesResponse"]>("/api/v1/capabilities");
  const action = useAction(houses.refresh);
  const [token, setToken] = useState("");
  const [confirm, setConfirm] = useState<string | null>(null);
  const available = capabilities.data?.features.passive_capture === true;
  const aiAnalysis = capabilities.data?.features.passive_ai_analysis === true;
  return <><Title description="Подключение существующих чатов к подтверждённым домам">MAX-чаты</Title>
    <Feedback loading={houses.loading} error={houses.error ?? action.error} />
    {token && <section className="one-time-link"><h2>Продолжите в MAX</h2><p>Передайте администратору чата эту команду для личного сообщения боту ДомСигнал:</p>
      <input aria-label="Команда подключения MAX" readOnly value={`/start ${token}`} onFocus={e => e.target.select()} />
      <p>Затем администратор добавляет существующего бота в группу. После проверки обновите страницу и подтвердите подключение.</p></section>}
    {!houses.error && houses.data?.map(h => <section className="admin-detail" key={h.management_id}><h2>{h.address}</h2>
      {h.bindings.map(b => <div key={b.id} className="connection-row">
        <p>{b.title ?? "MAX-чат"} · <Status value={b.status} /> · {b.scope_type === "entrance" ? `Подъезд ${b.scope_value}` : "Весь дом"}
          {b.suspension_reason && ` · ${b.suspension_reason}`}</p>
        {b.status === "active" && <PassiveSwitch binding={b} available={available} aiAnalysis={aiAnalysis} busy={action.busy}
          confirming={confirm === b.id} ask={() => setConfirm(b.id)} cancel={() => setConfirm(null)}
          change={async enabled => { await action.run(`/api/v1/chat-bindings/${b.id}/passive-capture`, { enabled }); setConfirm(null); }} />}
      </div>)}
      <button className="ticket-button" disabled={action.busy} onClick={async () => {
        const result = await action.run<Schema["ConnectionView"]>(`/api/v1/houses/${h.house_id}/chat-connections`, { scope_type: "house" });
        if (result) setToken(result.correlation_token ?? "");
      }}>Подключить существующий MAX-чат</button>
      {h.connection_requests.map(r => <div className="connection-row" key={r.id}><Status value={r.status} />
        <p>{r.last_error_code}</p>
        {["max_verified", "awaiting_approval"].includes(r.status) && <button className="ticket-button" disabled={action.busy}
          onClick={() => void action.run(`/api/v1/chat-connections/${r.id}/approve`, { confirm: true })}>Подтвердить подключение</button>}
        {!["completed", "rejected", "cancelled", "expired"].includes(r.status) && <>
          <button className="ticket-button secondary" disabled={action.busy} onClick={() => void action.run(`/api/v1/chat-connections/${r.id}/cancel`)}>Отменить подключение</button>
          <button className="ticket-button secondary" disabled={action.busy} onClick={() => void action.run(`/api/v1/chat-connections/${r.id}/reject`)}>Отклонить подключение</button></>}
      </div>)}
    </section>)}
  </>;
}

export function PassiveSwitch({ binding, available, aiAnalysis, busy, confirming, ask, cancel, change }: {
  binding: Schema["ChatSummary"]; available: boolean; aiAnalysis: boolean; busy: boolean; confirming: boolean;
  ask: () => void; cancel: () => void; change: (enabled: boolean) => Promise<void>;
}) {
  const enabled = binding.passive_capture_enabled === true;
  const hint = `passive-hint-${binding.id}`;
  return <div className="passive-switch">
    <p>Чтение чата: <strong>{enabled ? "включено" : "выключено"}</strong></p>
    {enabled && <p className="muted">Разбор переписки: {aiAnalysis ? "правила и модель (ИИ)" : "только правила, модель в чатах выключена"}</p>}
    {!confirming ? <>
      <button className="ticket-button secondary" disabled={busy || (!enabled && !available)}
        aria-describedby={!enabled && !available ? hint : undefined} onClick={ask}>
        {enabled ? "Выключить чтение чата" : "Включить чтение чата"}</button>
      {!enabled && !available && <p id={hint} className="muted">Чтение чатов выключено на сервере ДомСигнала.</p>}
    </> : <div className="admin-feedback" role="group" aria-label="Подтверждение">
      <p>{enabled
        ? "Бот перестанет сохранять сообщения этого чата. Уже собранные сигналы останутся."
        : "Бот начнёт читать сообщения чата, чтобы замечать проблемы дома. В чат один раз придёт сообщение о чтении."}</p>
      <button className="ticket-button" disabled={busy} onClick={() => void change(!enabled)}>
        {enabled ? "Подтвердить: выключить" : "Подтвердить: включить"}</button>
      <button className="ticket-button secondary" disabled={busy} onClick={cancel}>Отмена</button>
    </div>}
  </div>;
}
