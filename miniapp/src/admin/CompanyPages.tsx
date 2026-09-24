import { useState } from "react";
import { Feedback, History, OneTimeLink, Status, Title, connectionErrors, dateInput, formValue, submitted, useAction, useRead, type Schema } from "./administration";
import { QuotaMeter } from "./charts";

type House = Schema["CompanyHouseView"];
export function Organization({ base }: { base: string }) {
  const r = useRead<Schema["CompanyView"]>(`${base}/organization`);
  return <><Title>Организация</Title><Feedback loading={r.loading} error={r.error} />{!r.error && r.data &&
    <dl className="admin-facts"><dt>Полное наименование</dt><dd>{r.data.legal_name ?? r.data.name}</dd>
      <dt>ИНН</dt><dd>{r.data.inn ?? "Не указан"}</dd><dt>Статус</dt><dd><Status value={r.data.status} /></dd>
      <dt>Контакт</dt><dd>{[r.data.contact_name, r.data.contact_email, r.data.contact_phone].filter(Boolean).join(" · ") || "Не указан"}</dd>
    </dl>}</>;
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
        {p.open_registration && <span className="admin-status">По открытой ссылке</span>}
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
        <CredentialReset base={base} user={user} />
        {!confirm ? <button className="ticket-button secondary" onClick={() => setConfirm(true)}>Отозвать доступ сотрудника</button> :
          <div className="admin-feedback"><p>Сотрудник потеряет доступ к этой УК. Его незакрытые заявки вернутся в очередь без исполнителя.</p>
            <button className="ticket-button" disabled={action.busy} onClick={() => void action.run(`${base}/staff/${user}/revoke`)}>Подтвердить отзыв</button>
            <button className="ticket-button secondary" onClick={() => setConfirm(false)}>Отмена</button></div>}
      </>}
    </>}
  </section>;
}
/** «Сбросить пароль/MFA»: одноразовая ссылка, сессии сотрудника отзываются сразу. */
function CredentialReset({ base, user }: { base: string; user: string }) {
  const [kind, setKind] = useState<"password" | "password_mfa">("password_mfa");
  const [confirming, setConfirming] = useState(false);
  const [link, setLink] = useState("");
  const action = useAction();
  return <div className="passive-switch">
    <h3>Пароль и аутентификатор</h3>
    {link ? <OneTimeLink url={link} title="Передайте ссылку сброса сотруднику" label="Ссылка сброса" /> : <>
      <p className="muted">Сотрудник получит одноразовую ссылку и задаст новый пароль. Все его сессии закроются сразу, прежний пароль перестанет действовать.</p>
      <label>Что сбросить<select value={kind} onChange={e => setKind(e.target.value as typeof kind)}>
        <option value="password_mfa">Пароль и аутентификатор</option><option value="password">Только пароль</option></select></label>
      <Feedback error={action.error || undefined} />
      {!confirming ? <button className="ticket-button secondary" onClick={() => setConfirming(true)}>Сбросить пароль/MFA</button> :
        <div className="admin-feedback" role="group" aria-label="Подтверждение сброса">
          <p>Сотрудник сразу выйдет из кабинета на всех устройствах. Войти он сможет только по новой ссылке.</p>
          <button className="ticket-button" disabled={action.busy} onClick={async () => {
            const result = await action.run<Schema["CredentialResetIssued"]>(`${base}/staff/${user}/credential-reset`, { kind });
            if (result) { setLink(result.reset_url); setConfirming(false); }
          }}>Подтвердить сброс</button>
          <button className="ticket-button secondary" disabled={action.busy} onClick={() => setConfirming(false)}>Отмена</button>
        </div>}
    </>}
  </div>;
}
export function MyHouses({ base }: { base: string }) {
  const r = useRead<House[]>(`${base}/houses`);
  return <><Title description="Дома, на которые вы назначены">Мои дома</Title><Feedback loading={r.loading} error={r.error} />
    {!r.error && <HouseList houses={r.data ?? []} />}</>;
}
export function HouseList({ houses, manage }: { houses: House[]; manage?: { base: string; refresh: () => void } }) {
  return houses.length ? <div className="house-cards">{houses.map(h => <section className="admin-detail" key={h.management_id}>
    <h2>{h.address}</h2><p>Управление с {new Date(h.valid_from).toLocaleDateString("ru-RU")}{h.valid_to && ` до ${new Date(h.valid_to).toLocaleDateString("ru-RU")}`}</p>
    <p>{h.open_ticket_count} открытых заявок · {h.operator_count} операторов · {h.responsible_count} ответственных</p>
    {h.warning && <p className="admin-feedback">{h.warning}</p>}
    <h3>Подключение MAX</h3>{!h.bindings.length && <p className="muted">Чат пока не подключён</p>}
    {h.bindings.map(b => <p key={b.id}>{b.title ?? "MAX-чат"} · <Status value={b.status} />{b.suspension_reason && ` · ${b.suspension_reason}`}
      {b.status === "active" && b.passive_capture_enabled != null && ` · Чтение чата: ${b.passive_capture_enabled ? "включено" : "выключено"}`}</p>)}
    {manage && <OpenAccessSwitch base={manage.base} house={h} refresh={manage.refresh} />}
  </section>)}</div> : <p className="state-panel">Доступных домов пока нет.</p>;
}

/** Открытый доступ к дому (OPEN-HOUSE-ACCESS-2026-09-25): включение — с подтверждением. */
export function OpenAccessSwitch({ base, house, refresh }: { base: string; house: House; refresh: () => void }) {
  const [confirming, setConfirming] = useState(false);
  const action = useAction(refresh);
  const enabled = house.open_resident_access === true;
  const change = async () => {
    const result = await action.run<Schema["OpenAccessView"]>(`${base}/houses/${house.house_id}/open-access`,
      enabled ? { enabled: false } : { enabled: true, confirm: true });
    if (result) setConfirming(false);
  };
  return <div className="passive-switch">
    <h3>Открытый доступ</h3>
    <p>Открытый доступ: <strong>{enabled ? "включён" : "выключен"}</strong></p>
    <p className="muted">{enabled
      ? "Любой пользователь MAX может выбрать этот дом и сообщать о проблемах."
      : "Сообщать о проблемах и видеть доску могут только участники домового чата."}</p>
    <Feedback error={action.error || undefined} />
    {!confirming ? <button className="ticket-button secondary" disabled={action.busy} onClick={() => setConfirming(true)}>
      {enabled ? "Выключить открытый доступ" : "Включить открытый доступ"}</button>
    : <div className="admin-feedback" role="group" aria-label="Подтверждение открытого доступа">
      <p>{enabled
        ? "Жители, выбравшие дом сами, сразу потеряют доступ. Их заявки и история останутся у вас."
        : "Любой пользователь MAX сможет выбрать этот дом, сообщать о проблемах и видеть доску дома."}</p>
      <button className="ticket-button" disabled={action.busy} onClick={() => void change()}>
        {enabled ? "Подтвердить: выключить" : "Подтвердить: включить"}</button>
      <button className="ticket-button secondary" disabled={action.busy} onClick={() => setConfirming(false)}>Отмена</button>
    </div>}
  </div>;
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
    {!houses.error && <HouseList houses={houses.data ?? []} manage={{ base, refresh: houses.refresh }} />}
    <h2>Заявки на управление</h2>{requests.data?.map(r => <section className="admin-detail" key={r.id}>
      <h3>{r.requested_address}</h3><Status value={r.status} /><p>{r.decision_reason}</p><History rows={r.history ?? []} />
    </section>)}
  </>;
}
export function ChatConnections({ base, canRequest = true }: { base: string; canRequest?: boolean }) {
  const houses = useRead<House[]>(`${base}/houses`);
  const quota = useRead<Schema["CompanyQuotaView"]>(`${base}/chat-quota`);
  const capabilities = useRead<Schema["CapabilitiesResponse"]>("/api/v1/capabilities");
  const action = useAction(() => { houses.refresh(); quota.refresh(); });
  const [token, setToken] = useState("");
  const [remaining, setRemaining] = useState<Schema["ChatQuotaView"] | null>(null);
  const [confirm, setConfirm] = useState<string | null>(null);
  const [expand, setExpand] = useState(false);
  const available = capabilities.data?.features.passive_capture === true;
  const aiAnalysis = capabilities.data?.features.passive_ai_analysis === true;
  const exceeded = action.code === "CHAT_QUOTA_EXCEEDED";
  return <><Title description="Подключение существующих чатов к подтверждённым домам">MAX-чаты</Title>
    <ChatQuotaPanel base={base} view={quota.data} error={quota.error} refresh={quota.refresh} open={expand || (exceeded && canRequest)}
      setOpen={setExpand} canRequest={canRequest} />
    {exceeded ? <div className="admin-feedback" role="alert"><p><strong>Лимит исчерпан.</strong> {action.error}</p>
      {!canRequest ? <p>Расширение квоты запрашивает администратор УК.</p>
        : !expand && <button className="ticket-button" onClick={() => setExpand(true)}>Запросить расширение</button>}</div>
      : <Feedback loading={houses.loading} error={houses.error ?? (action.error || undefined)} />}
    {token && <section className="one-time-link"><h2>Продолжите в MAX</h2>
      {remaining?.limit != null && <p>После подключения останется свободных слотов: {Math.max((remaining.remaining ?? 0) - 1, 0)} из {remaining.limit}.</p>}
      <p>Передайте администратору чата эту команду для личного сообщения боту ДомСигнал:</p>
      <input aria-label="Команда подключения MAX" readOnly value={`/start ${token}`} onFocus={e => e.target.select()} />
      <p>Затем администратор добавляет существующего бота в группу. После проверки обновите страницу и подтвердите подключение.</p></section>}
    {!houses.error && houses.data?.map(h => <section className="admin-detail" key={h.management_id}><h2>{h.address}</h2>
      {h.bindings.map(b => <div key={b.id} className="connection-row">
        <p>{b.title ?? "MAX-чат"} · <Status value={b.status} /> · {b.scope_type === "entrance" ? `Подъезд ${b.scope_value}` : "Весь дом"}
          {b.suspension_reason && ` · ${b.suspension_reason}`}</p>
        {b.status === "active" && <PassiveSwitch binding={b} available={available} aiAnalysis={aiAnalysis} busy={action.busy}
          confirming={confirm === b.id} ask={() => setConfirm(b.id)} cancel={() => setConfirm(null)}
          change={async enabled => { await action.run(`/api/v1/chat-bindings/${b.id}/passive-capture`, { enabled }); setConfirm(null); }} />}
        {b.status === "active" && <NoticeAgain binding={b.id} />}
      </div>)}
      {h.can_connect_chats ? <button className="ticket-button" disabled={action.busy} onClick={async () => {
        const result = await action.run<Schema["ConnectionView"]>(`/api/v1/houses/${h.house_id}/chat-connections`, { scope_type: "house" });
        if (result) { setToken(result.correlation_token ?? ""); setRemaining(result.quota ?? null); }
      }}>Подключить существующий MAX-чат</button> : <p className="muted">Чаты этого дома подключает администратор УК или ответственный за дом.</p>}
      {h.connection_requests.map(r => <div className="connection-row" key={r.id}><Status value={r.status} />
        {r.last_error_code && <p>{connectionErrors[r.last_error_code] ?? r.last_error_code}</p>}
        {["max_verified", "awaiting_approval"].includes(r.status) && <button className="ticket-button" disabled={action.busy}
          onClick={() => void action.run(`/api/v1/chat-connections/${r.id}/approve`, { confirm: true })}>Подтвердить подключение</button>}
        {!["completed", "rejected", "cancelled", "expired"].includes(r.status) && <>
          <button className="ticket-button secondary" disabled={action.busy} onClick={() => void action.run(`/api/v1/chat-connections/${r.id}/cancel`)}>Отменить подключение</button>
          <button className="ticket-button secondary" disabled={action.busy} onClick={() => void action.run(`/api/v1/chat-connections/${r.id}/reject`)}>Отклонить подключение</button></>}
      </div>)}
    </section>)}
  </>;
}

/** «Отправить сообщение с кнопкой ещё раз» для уже подключённого чата. */
export function NoticeAgain({ binding }: { binding: string }) {
  const action = useAction();
  const [result, setResult] = useState<string>("");
  return <div className="passive-switch">
    <button className="ticket-button secondary" disabled={action.busy} onClick={async () => {
      setResult("");
      const view = await action.run<Schema["ChatNoticeView"]>(`/api/v1/chat-bindings/${binding}/notice`);
      if (view) setResult(view.queued
        ? "Сообщение с кнопкой «Открыть ДомСигнал» поставлено в очередь отправки в чат."
        : "Сообщение уже отправлялось в последние 10 минут. Повторите позже.");
    }}>Отправить сообщение с кнопкой ещё раз</button>
    {action.busy && <p role="status">Отправляем…</p>}
    {result && <p role="status" className="muted">{result}</p>}
    <Feedback error={action.error || undefined} />
  </div>;
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

/** «Чаты: N из Q», запрос на расширение и история квоты (CHAT-QUOTA-2026-09-26). */
export function ChatQuotaPanel({ base, view, error, refresh, open, setOpen, canRequest = true }: {
  base: string; view?: Schema["CompanyQuotaView"]; error?: unknown; refresh: () => void; open: boolean; setOpen: (open: boolean) => void;
  canRequest?: boolean;
}) {
  const [key, setKey] = useState(() => crypto.randomUUID());
  const action = useAction(refresh);
  if (error) return <Feedback error={error} />;
  if (!view) return null;
  const pending = view.requests.find(r => r.status === "pending");
  const limited = view.quota.limit !== null && view.quota.limit !== undefined;
  return <section className="admin-detail quota-panel" aria-label="Квота чатов">
    <QuotaMeter quota={view.quota} label="Подключённые чаты" />
    {pending ? <p>Запрос на расширение +{pending.requested_delta} на рассмотрении платформы.
      {canRequest && <button className="ticket-button secondary" disabled={action.busy} onClick={() => void action.run(`${base}/chat-quota/requests/${pending.id}/cancel`)}>Отозвать запрос</button>}</p>
      : limited && canRequest && (!open ? <button className="ticket-button secondary" onClick={() => setOpen(true)}>Запросить расширение</button> :
      <form className="ticket-form" onSubmit={async e => {
        const data = submitted(e);
        const result = await action.run(`${base}/chat-quota/requests`, {
          requested_delta: Number(formValue(data, "delta")), reason: formValue(data, "reason") }, key);
        if (result) { setOpen(false); setKey(crypto.randomUUID()); }
      }}><h3>Запрос на расширение квоты</h3>
        <label>Сколько чатов добавить<input name="delta" type="number" min={1} max={1000} required defaultValue={1} inputMode="numeric" /></label>
        <label>Обоснование<textarea name="reason" required minLength={3} maxLength={2000} placeholder="Например: подключаем чаты подъездов дома на ул. Баумана, 1" /></label>
        <Feedback error={action.error || undefined} />
        <div className="button-row"><button className="ticket-button" disabled={action.busy}>Отправить запрос</button>
          <button type="button" className="ticket-button secondary" onClick={() => setOpen(false)}>Отмена</button></div>
      </form>)}
    {view.requests.some(r => r.status !== "pending") && <details><summary>История запросов и выдач</summary>
      <ul className="admin-records">{view.requests.filter(r => r.status !== "pending").map(r => <li key={r.id}>
        <span>+{r.requested_delta}: {r.reason}</span><Status value={r.status} />
        {r.granted_delta != null && r.status !== "rejected" && <span>выдано +{r.granted_delta}</span>}
        {r.decision_reason && <span className="muted">{r.decision_reason}</span>}</li>)}</ul>
      <ul className="admin-records">{view.grants.map((g, i) => <li key={i}><span>{g.limit_after === null || g.limit_after === undefined ? "Без ограничения" : `Квота: ${g.limit_after}`}</span>
        <span className="muted">{g.reason}</span><time>{new Date(g.created_at).toLocaleString("ru-RU")}</time></li>)}</ul>
    </details>}
  </section>;
}
