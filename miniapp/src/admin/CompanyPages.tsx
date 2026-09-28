import { useConfirm } from "../shared/ui/useConfirm";
import { countLabel, formatStaffTime, formatDay } from "../shared/ui/format";
import { AddressListForm } from "./HouseBatch";
import { useEffect, useState, type FormEvent } from "react";
import { POLL_LIST_MS, POLL_WAITING_MS } from "../shared/api/useResource";
import { Feedback, History, OneTimeLink, Status, Title, connectionErrors, dateInput, formValue, submitted, useAction, useRead, type Schema } from "./administration";
import { QuotaMeter } from "./charts";
import { ChatSettingsPanel, CompanyProfileForm, HouseFactsForm } from "./CommunityPages";

type House = Schema["CompanyHouseView"];
export function Organization({ base }: { base: string }) {
  const r = useRead<Schema["CompanyView"]>(`${base}/organization`);
  return <><Title>Организация</Title><Feedback loading={r.loading} error={r.error} />{!r.error && r.data &&
    <dl className="admin-facts"><dt>Полное наименование</dt><dd>{r.data.legal_name ?? r.data.name}</dd>
      <dt>ИНН</dt><dd>{r.data.inn ?? "Не указан"}</dd><dt>Статус</dt><dd><Status value={r.data.status} /></dd>
      <dt>Контакт</dt><dd>{[r.data.contact_name, r.data.contact_email, r.data.contact_phone].filter(Boolean).join(" · ") || "Не указан"}</dd>
    </dl>}
    {!r.error && <CompanyProfileForm base={base} />}</>;
}
const ROLE_CHOICES = [
  ["operator", "Оператор", "Работает с заявками и сигналами домов, к которым вы дадите доступ."],
  ["company_admin", "Администратор УК", "Доступ ко всем домам организации; управляет сотрудниками, домами и чатами."],
] as const;
const ACCESS_CHOICES = [["none", "Нет доступа"], ["operator", "Оператор"], ["responsible", "Ответственный"]] as const;

export function Staff({ base }: { base: string }) {
  const people = useRead<Schema["MembershipView"][]>(`${base}/staff`);
  const invitations = useRead<Schema["InvitationView"][]>(`${base}/employee-invitations`);
  const houses = useRead<House[]>(`${base}/houses`);
  const [selected, setSelected] = useState<string | null>(null);
  const [link, setLink] = useState("");
  const [inviteKey, setInviteKey] = useState(() => crypto.randomUUID());
  const action = useAction(() => { people.refresh(); invitations.refresh(); });
  const confirm = useConfirm();
  return <><Title description="Приглашения и доступ к домам вашей УК">Сотрудники</Title>
    {confirm.dialog}
    <Feedback loading={people.loading} error={people.error ?? action.error} />
    {!people.error && <><form className="ticket-form invite-form" onSubmit={async e => {
      const data = submitted(e);
      const result = await action.run<Schema["InvitationView"]>(`${base}/employee-invitations`,
        { organization_role: formValue(data, "role") }, inviteKey);
      if (result) { setLink(result.invitation_url ?? ""); setInviteKey(crypto.randomUUID()); }
    }}><fieldset><legend>Роль нового сотрудника</legend>
        <div className="ds-radio-cards">{ROLE_CHOICES.map(([value, label, hint], i) => <label className="ds-radio-card" key={value}>
          <input type="radio" name="role" value={value} defaultChecked={i === 0} /><strong>{label}</strong><span className="ds-hint">{hint}</span>
        </label>)}</div></fieldset>
      <div><button className="ticket-button" disabled={action.busy}>Пригласить сотрудника</button></div></form>
      {link && <OneTimeLink url={link} />}
      <ul className="admin-records staff-list" aria-label="Сотрудники">{people.data?.map(p => <li key={p.user_id}>
        {/* Имя — название кнопки; роль и статус — её описание. Раскрывает карточку на месте, а не ведёт на другую страницу. */}
        <button type="button" className={`staff-row${selected === p.user_id ? " is-selected" : ""}`} aria-expanded={selected === p.user_id}
          aria-controls={selected === p.user_id ? "staff-detail" : undefined} aria-label={p.display_name} aria-describedby={`staff-meta-${p.user_id}`}
          onClick={() => setSelected(selected === p.user_id ? null : p.user_id)}>
          <span className="staff-name">{p.display_name}</span>
          <span className="staff-meta" id={`staff-meta-${p.user_id}`}>
            <span>{p.role === "company_admin" ? "Администратор УК" : "Оператор"}</span>
            <Status value={p.status} />
            {p.open_registration && <span className="admin-status">По открытой ссылке</span>}
          </span>
        </button>
      </li>)}</ul>
      {selected && <StaffAssignments key={selected} user={selected} base={base} houses={houses.data ?? []} refresh={people.refresh} />}
      <h2>Приглашения</h2><Feedback error={invitations.error} />
      <ul className="admin-records">{invitations.data?.map(inv => <li key={inv.id}>
        <span>{inv.organization_role === "company_admin" ? "Администратор УК" : "Оператор"}</span><Status value={inv.status} />
        <time>До {formatStaffTime(inv.expires_at)}</time>
        {["pending", "claimed"].includes(inv.status) && <button className="ds-btn ds-btn-danger" disabled={action.busy}
          onClick={() => confirm.ask({ title: "Отозвать приглашение?", body: "Ссылка перестанет работать сразу. Чтобы пригласить сотрудника, создайте новое приглашение.",
            confirmLabel: "Отозвать приглашение", run: () => action.run(`${base}/employee-invitations/${inv.id}/revoke`) })}>Отозвать приглашение</button>}
      </li>)}</ul></>}
  </>;
}
function StaffAssignments({ base, user, houses, refresh }: { base: string; user: string; houses: House[]; refresh: () => void }) {
  const r = useRead<Schema["StaffDetail"]>(`${base}/staff/${user}`);
  const [confirm, setConfirm] = useState(false);
  const [saved, setSaved] = useState("");
  const action = useAction(() => { r.refresh(); refresh(); });
  const guard = useConfirm();
  const name = r.data?.display_name ?? "Сотрудник";
  return <section className="admin-detail staff-detail" id="staff-detail" aria-labelledby="staff-detail-title">
    {guard.dialog}
    <h2 id="staff-detail-title">{name}</h2><Feedback loading={r.loading} error={r.error ?? action.error} />
    {r.data && !r.error && <><p><Status value={r.data.status} /></p>
      {r.data.status === "active" && <><section className="staff-block" aria-labelledby="staff-access-title">
        <h3 id="staff-access-title">Доступ к домам</h3>
        {houses.length === 0 && <p>Сначала запросите управление домом в разделе «Дома».</p>}
        {houses.map(h => {
          const current = r.data?.assignments.find(a => a.management_id === h.management_id)?.role ?? "none";
          return <div className="assignment-row" key={h.management_id}>
            <span id={`access-${h.management_id}`}>{h.address}</span>
            <div className="ds-segmented" role="group" aria-label={`Доступ: ${h.address}`}>
              {ACCESS_CHOICES.map(([value, label]) => <button key={value} type="button" aria-pressed={current === value}
                disabled={action.busy} onClick={() => {
                  if (current === value) return;
                  setSaved("");
                  const apply = async () => {
                    const result = await action.run(`${base}/staff/${user}/assignments`, { management_id: h.management_id, role: value === "none" ? null : value });
                    if (result !== undefined) setSaved(`Сохранено: ${h.address} — ${label.toLowerCase()}.`);
                  };
                  // F-18: снять назначение — с подтверждением: заявки сотрудника по дому вернутся в очередь.
                  if (value === "none") guard.ask({ title: `Снять доступ к дому ${h.address}?`, body: `${name} перестанет видеть заявки и сигналы этого дома. Незакрытые заявки сотрудника вернутся в очередь.`,
                    confirmLabel: "Снять доступ", run: apply });
                  else void apply();
                }}>{label}</button>)}
            </div>
          </div>;
        })}
        {saved && <p role="status" className="ds-notice ds-tone-success">{saved}</p>}
        <p className="muted">Администратор УК имеет доступ ко всем текущим домам своей организации. Назначение ответственного определяет работу с заявками дома.</p>
      </section>
        <CredentialReset base={base} user={user} />
        <section className="staff-block staff-danger" aria-labelledby="staff-revoke-title">
          <h3 id="staff-revoke-title">Отзыв доступа</h3>
          <p>{name} потеряет доступ к кабинету этой УК со следующего действия. Незакрытые заявки сотрудника вернутся в очередь без исполнителя; история работы сохранится.</p>
          {!confirm ? <div><button className="ds-btn ds-btn-danger" onClick={() => setConfirm(true)}>Отозвать доступ сотрудника</button></div> :
            <div className="ds-notice ds-tone-danger" role="group" aria-label="Подтверждение отзыва доступа">
              <p><strong>Отозвать доступ: {name}?</strong> Вход в ДомСигнал и доступ к другим организациям у сотрудника останутся.</p>
              <div className="button-row"><button className="ds-btn ds-btn-destructive" disabled={action.busy} onClick={() => void action.run(`${base}/staff/${user}/revoke`)}>Подтвердить отзыв</button>
                <button className="ds-btn ds-btn-secondary" onClick={() => setConfirm(false)}>Отмена</button></div></div>}
        </section>
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
  return <section className="staff-block passive-switch" aria-labelledby="staff-reset-title">
    <h3 id="staff-reset-title">Пароль и аутентификатор</h3>
    {link ? <OneTimeLink url={link} title="Передайте ссылку сброса сотруднику" label="Ссылка сброса" /> : <>
      <p className="muted">Сотрудник получит одноразовую ссылку и задаст новый пароль. Все его сессии закроются сразу, прежний пароль перестанет действовать.</p>
      <fieldset><legend>Что сбросить</legend><div className="ds-segmented">
        <label><input type="radio" name={`reset-${user}`} value="password_mfa" checked={kind === "password_mfa"} onChange={() => setKind("password_mfa")} />Пароль и аутентификатор</label>
        <label><input type="radio" name={`reset-${user}`} value="password" checked={kind === "password"} onChange={() => setKind("password")} />Только пароль</label>
      </div></fieldset>
      <Feedback error={action.error || undefined} />
      {!confirming ? <div><button className="ticket-button secondary" onClick={() => setConfirming(true)}>Сбросить пароль/MFA</button></div> :
        <div className="admin-feedback" role="group" aria-label="Подтверждение сброса">
          <p>Сотрудник сразу выйдет из кабинета на всех устройствах. Войти он сможет только по новой ссылке.</p>
          <div className="button-row"><button className="ticket-button" disabled={action.busy} onClick={async () => {
            const result = await action.run<Schema["CredentialResetIssued"]>(`${base}/staff/${user}/credential-reset`, { kind });
            if (result) { setLink(result.reset_url); setConfirming(false); }
          }}>Подтвердить сброс</button>
          <button className="ticket-button secondary" disabled={action.busy} onClick={() => setConfirming(false)}>Отмена</button></div>
        </div>}
    </>}
  </section>;
}
export function MyHouses({ base }: { base: string }) {
  const r = useRead<House[]>(`${base}/houses`, 0, { poll: POLL_LIST_MS });
  return <><Title description="Дома, на которые вы назначены">Мои дома</Title><Feedback loading={r.loading} error={r.error} />
    {!r.error && <HouseList houses={r.data ?? []} base={base} />}</>;
}
export function HouseList({ houses, manage, base = manage?.base }: { houses: House[]; manage?: { base: string; refresh: () => void }; base?: string }) {
  return houses.length ? <div className="house-cards">{houses.map(h => <section className="admin-detail" key={h.management_id}>
    <h2>{h.address}</h2><p>Управление с {formatDay(h.valid_from)}{h.valid_to && ` до ${formatDay(h.valid_to)}`}</p>
    <p>{countLabel(h.open_ticket_count, ["открытая заявка", "открытые заявки", "открытых заявок"])} · {countLabel(h.operator_count, ["оператор", "оператора", "операторов"])} · {countLabel(h.responsible_count, ["ответственный", "ответственных", "ответственных"])}</p>
    {h.warning && <p className="admin-feedback">{h.warning}</p>}
    <h3>Подключение MAX</h3>{!h.bindings.length && <p className="muted">Чат пока не подключён</p>}
    {h.bindings.map(b => <p key={b.id}>{b.title ?? "MAX-чат"} · <Status value={b.status} />{b.suspension_reason && ` · ${b.suspension_reason}`}
      {b.status === "active" && b.passive_capture_enabled != null && ` · Чтение чата: ${b.passive_capture_enabled ? "включено" : "выключено"}`}</p>)}
    {manage && <OpenAccessSwitch base={manage.base} house={h} refresh={manage.refresh} />}
    {manage && <HouseFactsForm base={manage.base} house={h} refresh={manage.refresh} />}
    {base && <HouseCouncil base={base} house={h} />}
  </section>)}</div> : <p className="state-panel">Доступных домов пока нет.</p>;
}

/**
 * Совет дома (D4): члены совета и предложения жителей. Отмечает и снимает
 * членов совета только администратор УК (`can_manage`), с основанием;
 * остальные сотрудники видят состав и предложения. Данные — при раскрытии.
 */
export function HouseCouncil({ base, house }: { base: string; house: House }) {
  const [open, setOpen] = useState(false);
  return <details className="passive-switch" onToggle={e => setOpen(e.currentTarget.open)}>
    <summary>Совет дома</summary>
    {open && <CouncilDetail base={base} houseId={house.house_id} />}
  </details>;
}
const councilStatus: Record<string, string> = { new: "Ждёт рассмотрения", converted: "Вынесено на опрос" };
const COUNCIL_FIELDS = { user_id: "житель", reason: "основание — от 3 до 500 символов" };
function CouncilDetail({ base, houseId }: { base: string; houseId: string }) {
  const path = `${base}/houses/${houseId}/council`;
  const r = useRead<Schema["CouncilAdminView"]>(path);
  const action = useAction(r.refresh, COUNCIL_FIELDS);
  const [asking, setAsking] = useState<{ user: string; name: string; revoke: boolean } | null>(null);
  const [search, setSearch] = useState("");
  const [notice, setNotice] = useState("");
  // Повтор после сбоя — с тем же ключом: второй черновик опроса не появится.
  const [pollKeys] = useState(() => new Map<string, string>());
  const view = r.data;
  const members = view?.members ?? [];
  const query = search.trim().toLowerCase();
  const candidates = (view?.residents ?? []).filter(p => !p.is_member && p.display_name.toLowerCase().includes(query));
  const proposals = view?.proposals ?? [];
  const ask = (user: string, name: string, revoke: boolean) => { setNotice(""); setAsking({ user, name, revoke }); };
  const change = async (event: FormEvent<HTMLFormElement>) => {
    if (!asking) return;
    const reason = formValue(submitted(event), "reason");
    const result = asking.revoke
      ? await action.run<Schema["CouncilAdminView"]>(`${path}/members/${asking.user}/revoke`, { reason })
      : await action.run<Schema["CouncilAdminView"]>(`${path}/members`, { user_id: asking.user, reason });
    if (result) { setNotice(asking.revoke ? `${asking.name}: отметка о членстве в совете снята.` : `${asking.name} отмечен(а) в совете дома.`); setAsking(null); }
  };
  const toPoll = async (proposal: string) => {
    setNotice("");
    const key = pollKeys.get(proposal) ?? crypto.randomUUID();
    pollKeys.set(proposal, key);
    const result = await action.run<Schema["BroadcastView"]>(`${base}/proposals/${proposal}/poll`, {}, key);
    if (result) setNotice("Черновик опроса создан — откройте раздел «Рассылки», проверьте и отправьте.");
  };
  const reasonForm = (revoke: boolean) => asking && asking.revoke === revoke &&
    <form className="ticket-form admin-feedback" aria-label="Подтверждение: совет дома" onSubmit={e => void change(e)}>
      <p>{revoke ? `Снять ${asking.name} из совета дома?` : `Отметить ${asking.name} в совете дома?`} Основание попадёт в журнал действий.</p>
      <label>Основание<textarea name="reason" required minLength={3} maxLength={500}
        placeholder={revoke ? "Например: житель попросил снять отметку" : "Например: избран на общем собрании"} /></label>
      <div className="button-row"><button className="ticket-button" disabled={action.busy}>{revoke ? "Подтвердить: снять" : "Подтвердить: отметить в совет"}</button>
        <button type="button" className="ticket-button secondary" disabled={action.busy} onClick={() => setAsking(null)}>Отмена</button></div>
    </form>;
  return <>
    <Feedback loading={r.loading && !view} error={r.error ?? (action.error || undefined)} />
    {notice && <p role="status" className="muted">{notice}</p>}
    {view && !r.error && <>
      <p className="muted">Совет дома публикует объявления и опросы для своего дома с подписью «Сообщение от совета дома».
        {view.can_manage ? " Отмечать и снимать членов совета может администратор УК." : " Состав совета меняет администратор УК."}</p>
      <h4>Члены совета</h4>
      {members.length ? <ul className="admin-records">{members.map(m => <li key={m.user_id}>
        <span>{m.display_name}</span><time>в совете с {formatDay(m.since)}</time>
        {view.can_manage && <button className="ticket-button secondary" disabled={action.busy} aria-label={`Снять из совета: ${m.display_name}`}
          onClick={() => ask(m.user_id, m.display_name, true)}>Снять</button>}
      </li>)}</ul> : <p className="muted">В совете дома пока никого нет.</p>}
      {reasonForm(true)}
      {view.can_manage && <>
        <h4>Жители дома</h4>
        {(view.residents ?? []).some(p => !p.is_member) ? <>
          <div className="inline-form"><label>Найти жителя<input value={search} onChange={e => setSearch(e.target.value)} maxLength={100} /></label></div>
          <ul className="admin-records">{candidates.map(p => <li key={p.user_id}><span>{p.display_name}</span>
            <button className="ticket-button secondary" disabled={action.busy} aria-label={`Отметить в совет: ${p.display_name}`}
              onClick={() => ask(p.user_id, p.display_name, false)}>Отметить в совет</button></li>)}</ul>
          {!candidates.length && <p className="muted">Никого не нашли.</p>}
        </> : <p className="muted">Жителей для выбора нет. В совет можно отметить участника домового чата или жителя, выбравшего дом с открытым доступом.</p>}
        {reasonForm(false)}
      </>}
      <h4>Предложения жителей</h4>
      {proposals.length ? <ul className="admin-records">{proposals.map(p => <li key={p.id}>
        <span className="pre-wrap">{p.text}</span>
        <span className="admin-status">{councilStatus[p.status] ?? p.status}</span>
        <time>{formatStaffTime(p.created_at)}</time>
        {view.can_manage && p.status === "new" && <button className="ticket-button secondary" disabled={action.busy}
          aria-label={`Сделать опросом: ${p.text.slice(0, 80)}`} onClick={() => void toPoll(p.id)}>Сделать опросом</button>}
      </li>)}</ul> : <p className="muted">Жители пока ничего не предложили.</p>}
      {view.can_manage && proposals.some(p => p.status === "new") &&
        <p className="muted">«Сделать опросом» создаёт черновик опроса с вариантами «За», «Против», «Нужно обсудить» на 3 дня. Его можно изменить в разделе «Рассылки» до отправки.</p>}
    </>}
  </>;
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
  // U-06: дом появляется у администратора сам, как только платформа одобрила заявку.
  const [waiting, setWaiting] = useState(false);
  const poll = { poll: waiting ? POLL_WAITING_MS : POLL_LIST_MS };
  const houses = useRead<House[]>(`${base}/houses`, 0, poll);
  const requests = useRead<Schema["HouseRequestView"][]>(`${base}/house-management-requests`, 0, poll);
  const pending = (requests.data ?? []).some(r => ["submitted", "under_review", "needs_info"].includes(r.status));
  useEffect(() => { setWaiting(pending); }, [pending]);
  const [show, setShow] = useState(false);
  const [list, setList] = useState(false);
  const [key, setKey] = useState(() => crypto.randomUUID());
  const action = useAction(requests.refresh);
  return <><Title description="Действующее управление и заявки на подключение домов">Дома</Title>
    <div className="button-row"><button className="ticket-button" aria-expanded={show} onClick={() => setShow(!show)}>Запросить управление домом</button>
      <button className="ticket-button secondary" aria-expanded={list} onClick={() => setList(!list)}>Вставить список адресов</button></div>
    {list && <AddressListForm base={base} onDone={requests.refresh} />}
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
  // U-05: пока идёт подключение, страница сама проверяет статус раз в 5 с.
  const [waiting, setWaiting] = useState(false);
  const houses = useRead<House[]>(`${base}/houses`, 0, { poll: waiting ? POLL_WAITING_MS : POLL_LIST_MS });
  const active = (houses.data ?? []).some(h => h.connection_requests.some(r => !["completed", "rejected", "cancelled", "expired"].includes(r.status)));
  useEffect(() => { setWaiting(active); }, [active]);
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
      <p>1. Администратор чата открывает бота ДомСигнал по кнопке — код подключения передаётся сам, бот ответит, что делать дальше.</p>
      {capabilities.data?.bot_url && <a className="ticket-button" href={`${capabilities.data.bot_url}?start=${token}`} target="_blank" rel="noopener noreferrer">Открыть бота в MAX</a>}
      <p className="muted">Или отправьте боту в личные сообщения эту команду целиком:</p>
      <input aria-label="Команда подключения MAX" readOnly value={`/start ${token}`} onFocus={e => e.target.select()} />
      <p>2. После ответа бота администратор добавляет бота в группу дома и делает его администратором с правом читать все сообщения.</p>
      <p>3. Обновите эту страницу и нажмите «Подтвердить подключение».</p></section>}
    {!houses.error && houses.data?.map(h => <section className="admin-detail" key={h.management_id}><h2>{h.address}</h2>
      {h.bindings.map(b => <div key={b.id} className="connection-row">
        <p>{b.title ?? "MAX-чат"} · <Status value={b.status} /> · {b.scope_type === "entrance" ? `Подъезд ${b.scope_value}` : "Весь дом"}
          {b.suspension_reason && ` · ${b.suspension_reason}`}</p>
        {b.status === "active" && <PassiveSwitch binding={b} available={available} aiAnalysis={aiAnalysis} busy={action.busy}
          confirming={confirm === b.id} ask={() => setConfirm(b.id)} cancel={() => setConfirm(null)}
          change={async enabled => { await action.run(`/api/v1/chat-bindings/${b.id}/passive-capture`, { enabled }); setConfirm(null); }} />}
        {b.status === "active" && <NoticeAgain binding={b.id} />}
        {b.status === "active" && <ChatSettingsPanel bindingId={b.id} />}
      </div>)}
      {h.can_connect_chats ? <button className="ticket-button" disabled={action.busy} onClick={async () => {
        const result = await action.run<Schema["ConnectionView"]>(`/api/v1/houses/${h.house_id}/chat-connections`, { scope_type: "house" });
        if (result) { setToken(result.correlation_token ?? ""); setRemaining(result.quota ?? null); }
      }}>Подключить существующий MAX-чат</button> : <p className="muted">Чаты этого дома подключает администратор УК или ответственный за дом.</p>}
      {h.connection_requests.map(r => <div className="connection-row" key={r.id}><Status value={r.status} />
        {r.last_error_code && <p>{connectionErrors[r.last_error_code] ?? r.last_error_code}</p>}
        {r.status === "chat_detected" && r.last_error_code && <p className="muted">Исправьте это в MAX и нажмите «Подтвердить подключение» — проверка пройдёт заново.</p>}
        {["chat_detected", "max_verified", "awaiting_approval"].includes(r.status) && <button className="ticket-button" disabled={action.busy}
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
        <span className="muted">{g.reason}</span><time>{formatStaffTime(g.created_at)}</time></li>)}</ul>
    </details>}
  </section>;
}
