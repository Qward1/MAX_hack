import { formatStaffTime } from "../shared/ui/format";
import { useEffect, useState } from "react";
import { adminClient, Feedback, Title, useAction, useRead, type Schema } from "./administration";

/**
 * D3 в кабинете: объявления, рассылки и опросы (один механизм), настройки
 * бота в чате, профиль УК, уведомления платформы и сводка, запись на приём.
 * Каждое действие проверяет сервер; интерфейс только показывает доступное.
 */

type Broadcast = Schema["BroadcastView"];
type Audience = Schema["BroadcastAudience"];
type Channel = Schema["BroadcastCreate"]["channels"][number];

export const SERVICE_ONLY_RULE = "Только сервисные сообщения для жителей. Реклама запрещена.";
const PLATFORM_RULE = "Только сервисные сообщения. Реклама запрещена.";
const kindLabels: Record<string, string> = { announcement: "Объявление", mailing: "Рассылка", poll: "Опрос" };
const topicLabels: Record<string, string> = { outage: "Отключение", works: "Работы", meeting: "Собрание", other: "Другое" };
const statusLabels: Record<string, string> = {
  draft: "Черновик", scheduled: "Запланировано", sent: "Отправлено", cancelled: "Отменено",
};
const channelLabels: Record<string, string> = {
  chat: "Пост в домовой чат", dm: "Личные сообщения жителям", feed: "Лента «Объявления» в ДомСигнале",
  staff: "Кабинеты и личные сообщения сотрудников УК",
};
const reasonLabels: Record<string, string> = {
  UNSUBSCRIBED: "отписались от рассылок", NO_DIALOG: "нет диалога с ботом", NO_MAX_IDENTITY: "нет диалога с ботом",
  CHAT_SETTING_OFF: "выключено в настройках чата", RETRACTED: "удалено до отправки",
  ACCESS_REVOKED: "нет доступа к дому", CHAT_BINDING_INACTIVE: "чат отключён", MAX_IDENTITY_CHANGED: "сменился аккаунт MAX",
};
const when = (value?: string | null) => formatStaffTime(value) ?? "";

function localInput(date: Date) {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function Skipped({ skipped }: { skipped?: Record<string, number> }) {
  const entries = Object.entries(skipped ?? {});
  if (!entries.length) return <>—</>;
  return <>{entries.map(([code, count]) => `${reasonLabels[code] ?? code}: ${count}`).join("; ")}</>;
}

// ================================================================ рассылки

export function Mailings({ base, platform = false }: { base: string; platform?: boolean }) {
  const listPath = platform ? "/api/v1/platform/broadcasts" : `${base}/broadcasts`;
  const [offset, setOffset] = useState(0);
  const list = useRead<Schema["BroadcastList"]>(`${listPath}?limit=20&offset=${offset}`);
  const [selected, select] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const refresh = () => list.refresh();
  return <>
    <Title description={platform
      ? "Сообщения платформы: в кабинеты и личку сотрудников УК и в домовые чаты, где это разрешено"
      : "Объявления, рассылки и опросы жителям ваших домов. Черновик → предпросмотр → подтверждение → отправка."}>
      {platform ? "Сообщения платформы" : "Рассылки"}</Title>
    {!creating && !selected && <button className="ticket-button" onClick={() => setCreating(true)}>Новое сообщение</button>}
    {creating && <MailingEditor base={base} platform={platform} onDone={(id) => { setCreating(false); refresh(); if (id) select(id); }} />}
    {selected && <MailingDetail key={selected} id={selected} base={base} platform={platform}
      close={() => { select(null); refresh(); }} refresh={refresh} />}
    <Feedback loading={list.loading && !list.data} error={list.error} />
    {list.data && !list.error && !creating && !selected && (list.data.items.length ? <ul className="admin-records">
      {list.data.items.map(item => <li key={item.id}>
        <button className="record-link" onClick={() => { setCreating(false); select(item.id); }}>{item.title}</button>
        <span>{kindLabels[item.kind]}</span>
        <span className={`admin-status status-${item.status}`}>{item.retracted_at ? "Удалено" : statusLabels[item.status]}</span>
        <time>{item.sent_at ? when(item.sent_at) : item.scheduled_at ? `на ${when(item.scheduled_at)}` : `создано ${when(item.created_at)}`}</time>
        {item.author_name && <span className="muted">{item.author_name}</span>}
      </li>)}</ul> : <p className="state-panel">Сообщений пока нет. Начните с «Новое сообщение».</p>)}
    {list.data && list.data.page.total > 20 && <div className="button-row">
      <button className="ticket-button secondary" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 20))}>Предыдущие</button>
      <button className="ticket-button secondary" disabled={offset + 20 >= list.data.page.total} onClick={() => setOffset(offset + 20)}>Следующие</button>
    </div>}
  </>;
}

type Draft = {
  kind: "announcement" | "mailing" | "poll";
  topic: "outage" | "works" | "meeting" | "other";
  title: string; body: string;
  question: string; options: string[]; multiple: boolean; closes: string;
  audience: Audience; channels: Channel[];
};

function initialDraft(platform: boolean, source?: Broadcast): Draft {
  const closes = localInput(new Date(Date.now() + 3 * 86400000));
  if (source) return {
    kind: source.kind, topic: source.topic ?? "works", title: source.title, body: source.body,
    question: source.poll?.question ?? "", options: source.poll?.options.map(o => o.label) ?? ["", ""],
    multiple: source.poll?.multiple ?? false, closes: source.poll ? localInput(new Date(source.poll.closes_at)) : closes,
    audience: source.audience, channels: source.channels,
  };
  return {
    kind: platform ? "mailing" : "announcement", topic: "works", title: "", body: "",
    question: "", options: ["", ""], multiple: false, closes,
    audience: { mode: "all", only_with_chat: false, only_open_access: false },
    channels: platform ? ["staff"] : ["chat", "feed"],
  };
}

// Поля формы для ошибок схемы (422): правила сервиса приходят готовым текстом.
const MAILING_FIELDS: Record<string, string> = {
  kind: "вид", topic: "тему объявления", title: "заголовок", body: "текст", audience: "кому",
  channels: "каналы", poll: "вопрос, варианты (без повторов) и срок опроса",
};

function MailingEditor({ base, platform, source, onDone }: {
  base: string; platform: boolean; source?: Broadcast; onDone: (id?: string) => void;
}) {
  const [draft, setDraft] = useState<Draft>(() => initialDraft(platform, source));
  const [key] = useState(() => crypto.randomUUID());
  const action = useAction(undefined, MAILING_FIELDS);
  const houses = useRead<Schema["BroadcastHouseOption"][]>(platform ? "/api/v1/capabilities" : `${base}/broadcast-houses`);
  const companies = useRead<Schema["CompanyView"][]>(platform ? "/api/v1/platform/companies" : "/api/v1/capabilities");
  const regions = useRead<string[]>(platform ? "/api/v1/platform/broadcast-regions" : "/api/v1/capabilities");
  const set = (patch: Partial<Draft>) => setDraft(value => ({ ...value, ...patch }));
  const setAudience = (patch: Partial<Audience>) => setDraft(value => ({ ...value, audience: { ...value.audience, ...patch } }));
  const houseOptions = !platform && Array.isArray(houses.data) ? houses.data : [];
  const companyOptions = platform && Array.isArray(companies.data) ? companies.data : [];
  const regionOptions = platform && Array.isArray(regions.data) ? regions.data
    : [...new Set(houseOptions.map(h => h.region_code).filter(Boolean) as string[])];
  const channels: Channel[] = platform ? ["staff", "chat"] : ["chat", "dm", "feed"];
  const toggleList = <T,>(list: T[], item: T) => list.includes(item) ? list.filter(v => v !== item) : [...list, item];
  async function save(event: React.FormEvent) {
    event.preventDefault();
    const payload = {
      kind: draft.kind,
      topic: draft.kind === "announcement" ? draft.topic : null,
      title: draft.title.trim(), body: draft.body.trim(),
      audience: draft.audience, channels: draft.channels,
      poll: draft.kind === "poll" ? {
        question: draft.question.trim(), options: draft.options.map(o => o.trim()).filter(Boolean),
        multiple: draft.multiple, closes_at: new Date(draft.closes).toISOString(),
      } : null,
    };
    const result = source
      ? await action.run<Broadcast>(`/api/v1/broadcasts/${source.id}/update`, { ...payload, expected_version: source.version })
      : await action.run<Broadcast>(platform ? "/api/v1/platform/broadcasts" : `${base}/broadcasts`, payload, key);
    if (result) onDone(result.id);
  }
  return <form className="ticket-form admin-detail mailing-form" onSubmit={save}>
    <h2>{source ? "Изменить черновик" : "Новое сообщение"}</h2>
    <p className="admin-feedback"><strong>{platform ? PLATFORM_RULE : SERVICE_ONLY_RULE}</strong> Сообщение уйдёт от имени {platform ? "ДомСигнала" : "вашей УК"}.</p>
    <fieldset className="choice-row"><legend>Вид</legend>
      {(platform ? ["mailing", "announcement"] : ["announcement", "mailing", "poll"]).map(kind =>
        <label key={kind} className="checkbox-label"><input type="radio" name="kind" checked={draft.kind === kind}
          onChange={() => set({ kind: kind as Draft["kind"] })} />{kindLabels[kind]}</label>)}
    </fieldset>
    {draft.kind === "announcement" && <label>Тема объявления<select value={draft.topic} onChange={e => set({ topic: e.target.value as Draft["topic"] })}>
      {Object.entries(topicLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>}
    <label>Заголовок<input value={draft.title} required minLength={3} maxLength={200} onChange={e => set({ title: e.target.value })} /></label>
    <label>Текст{draft.kind === "poll" && " (необязательно)"}<textarea value={draft.body} maxLength={3000} rows={5}
      required={draft.kind !== "poll"} onChange={e => set({ body: e.target.value })} /></label>
    {draft.kind === "poll" && <fieldset className="choice-row poll-editor"><legend>Опрос</legend>
      <label>Вопрос<input value={draft.question} required minLength={3} maxLength={300} onChange={e => set({ question: e.target.value })} /></label>
      {draft.options.map((option, index) => <div key={index} className="inline-form">
        <label>Вариант {index + 1}<input value={option} required maxLength={100}
          onChange={e => set({ options: draft.options.map((o, i) => i === index ? e.target.value : o) })} /></label>
        {draft.options.length > 2 && <button type="button" className="ticket-button secondary"
          onClick={() => set({ options: draft.options.filter((_, i) => i !== index) })}>Убрать вариант {index + 1}</button>}
      </div>)}
      {draft.options.length < 10 && <button type="button" className="ticket-button secondary"
        onClick={() => set({ options: [...draft.options, ""] })}>Добавить вариант</button>}
      <label className="checkbox-label"><input type="checkbox" checked={draft.multiple} onChange={e => set({ multiple: e.target.checked })} />
        Можно выбрать несколько вариантов</label>
      <label>Голосование до<input type="datetime-local" value={draft.closes} required onChange={e => set({ closes: e.target.value })} /></label>
      <p className="muted">Подпись опроса: «Предварительный опрос. Не является решением общего собрания собственников».</p>
    </fieldset>}
    <fieldset className="choice-row"><legend>Кому</legend>
      {(platform ? [["all", "Все УК"], ["companies", "Выбранные УК"], ["region", "УК региона"]]
        : [["all", "Все дома"], ["houses", "Выбранные дома"], ["filter", "По фильтру"]]).map(([mode, label]) =>
        <label key={mode} className="checkbox-label"><input type="radio" name="mode" checked={draft.audience.mode === mode}
          onChange={() => setAudience({ mode: mode as Audience["mode"] })} />{label}</label>)}
      {draft.audience.mode === "houses" && <div className="check-list">{houseOptions.map(h =>
        <label key={h.house_id} className="checkbox-label"><input type="checkbox" checked={(draft.audience.house_ids ?? []).includes(h.house_id)}
          onChange={() => setAudience({ house_ids: toggleList(draft.audience.house_ids ?? [], h.house_id) })} />{h.address}
          {h.has_chat ? " · чат подключён" : ""}</label>)}</div>}
      {draft.audience.mode === "companies" && <div className="check-list">{companyOptions.map(c =>
        <label key={c.id} className="checkbox-label"><input type="checkbox" checked={(draft.audience.company_ids ?? []).includes(c.id)}
          onChange={() => setAudience({ company_ids: toggleList(draft.audience.company_ids ?? [], c.id) })} />{c.name}</label>)}</div>}
      {(draft.audience.mode === "filter" || draft.audience.mode === "region") && <>
        <label>Регион<select value={draft.audience.region_code ?? ""} onChange={e => setAudience({ region_code: e.target.value || null })}
          required={draft.audience.mode === "region"}>
          <option value="">{draft.audience.mode === "region" ? "Выберите регион" : "Любой"}</option>
          {regionOptions.map(code => <option key={code} value={code}>{code}</option>)}</select></label>
        {draft.audience.mode === "filter" && <>
          <label className="checkbox-label"><input type="checkbox" checked={draft.audience.only_with_chat ?? false}
            onChange={e => setAudience({ only_with_chat: e.target.checked })} />Только дома с подключённым чатом</label>
          <label className="checkbox-label"><input type="checkbox" checked={draft.audience.only_open_access ?? false}
            onChange={e => setAudience({ only_open_access: e.target.checked })} />Только дома с открытым доступом</label>
        </>}
      </>}
    </fieldset>
    <fieldset className="choice-row"><legend>Каналы</legend>
      {channels.map(channel => <label key={channel} className="checkbox-label"><input type="checkbox" checked={draft.channels.includes(channel)}
        onChange={() => set({ channels: toggleList(draft.channels, channel) })} />{channelLabels[channel]}</label>)}
      {!platform && <p className="muted">Личные сообщения получают только жители, начавшие диалог с ботом; кнопка «Не получать рассылки» уважается. Опрос всегда есть в ленте дома.</p>}
      {platform && <p className="muted">В домовой чат сообщение платформы уходит только там, где УК разрешила «Сообщения платформы» в настройках чата.</p>}
    </fieldset>
    <Feedback error={action.error || undefined} />
    <div className="button-row">
      <button className="ticket-button" disabled={action.busy || draft.channels.length === 0}>{source ? "Сохранить черновик" : "Создать черновик"}</button>
      <button type="button" className="ticket-button secondary" onClick={() => onDone(source?.id)}>Отмена</button>
    </div>
  </form>;
}

function MailingDetail({ id, base, platform, close, refresh }: {
  id: string; base: string; platform: boolean; close: () => void; refresh: () => void;
}) {
  const r = useRead<Broadcast>(`/api/v1/broadcasts/${id}`);
  const [editing, setEditing] = useState(false);
  const [preview, setPreview] = useState<Schema["BroadcastPreview"] | null>(null);
  const [previewError, setPreviewError] = useState("");
  const [service, setService] = useState(false);
  const [later, setLater] = useState(false);
  const [sendAt, setSendAt] = useState(() => localInput(new Date(Date.now() + 3600000)));
  const [confirmRetract, setConfirmRetract] = useState(false);
  const [edit, setEdit] = useState<{ title: string; body: string } | null>(null);
  const action = useAction(() => { r.refresh(); refresh(); setPreview(null); });
  const b = r.data;
  // Отказ сервера (например, «уже отправлено») — показать актуальное состояние.
  const act = async (path: string, payload: object) => {
    const result = await action.run(path, payload);
    if (result === undefined) { r.refresh(); refresh(); }
    return result;
  };
  useEffect(() => {
    if (!b) return;
    // «Отправить сейчас» ставит сообщение в очередь: карточка ждёт отправки
    // сама (живая проверка D3 — иначе висела «Запланировано»). Позже —
    // проверка ко времени отправки. После отправки — пока идут доставки.
    let delay: number | null = null;
    if (b.status === "scheduled" && b.scheduled_at) {
      const due = new Date(b.scheduled_at).getTime() - Date.now();
      delay = due <= 0 ? 2000 : Math.min(due + 1000, 60000);
    } else if (b.status === "sent" && (b.stats ?? []).some(s => s.pending > 0 || s.deferred_quiet_hours > 0)) {
      delay = 5000;
    }
    if (delay === null) return;
    const timer = window.setTimeout(() => { r.refresh(); if (b.status === "scheduled") refresh(); }, delay);
    return () => window.clearTimeout(timer);
  }, [b, r.refresh, refresh]);
  async function loadPreview() {
    setPreviewError("");
    try { setPreview(await adminClient.request<Schema["BroadcastPreview"]>(`/api/v1/broadcasts/${id}/preview`)); }
    catch (e) { setPreviewError(e instanceof Error ? e.message : "Не удалось посчитать получателей"); }
  }
  if (editing && b) return <MailingEditor base={base} platform={platform} source={b} onDone={() => { setEditing(false); r.refresh(); refresh(); }} />;
  return <section className="admin-detail" aria-label="Сообщение">
    <div className="button-row"><button className="ticket-button secondary" onClick={close}>← К списку</button></div>
    <Feedback loading={r.loading && !b} error={r.error ?? (action.error || undefined)} />
    {b && <>
      <h2>{b.title}</h2>
      <p><span className={`admin-status status-${b.status}`}>{b.retracted_at ? "Удалено автором" : statusLabels[b.status]}</span>{" "}
        {kindLabels[b.kind]}{b.topic ? ` · ${topicLabels[b.topic]}` : ""} · {b.sender}</p>
      {b.body && <p className="pre-wrap">{b.body}</p>}
      <dl className="admin-facts">
        <dt>Каналы</dt><dd>{b.channels.map(c => channelLabels[c]).join("; ")}</dd>
        <dt>Автор</dt><dd>{b.author_name ?? "—"}{b.confirmed_by_name ? ` · подтвердил(а): ${b.confirmed_by_name}` : ""}</dd>
        {b.scheduled_at && <><dt>Отправка</dt><dd>{when(b.sent_at ?? b.scheduled_at)}</dd></>}
        {(b.houses ?? []).length > 0 && <><dt>Дома</dt><dd>{(b.houses ?? []).join("; ")}</dd></>}
        {b.edited_at && <><dt>Изменено</dt><dd>{when(b.edited_at)}</dd></>}
      </dl>
      {b.poll && <PollResultsView poll={b.poll} />}
      {b.status === "draft" && <>
        <div className="button-row">
          <button className="ticket-button secondary" onClick={() => setEditing(true)}>Изменить черновик</button>
          <button className="ticket-button secondary" onClick={() => void loadPreview()}>Предпросмотр получателей</button>
          <button className="ticket-button secondary" disabled={action.busy}
            onClick={() => void act(`/api/v1/broadcasts/${id}/cancel`, { expected_version: b.version })}>Удалить черновик</button>
        </div>
        {previewError && <p role="alert" className="admin-feedback">{previewError}</p>}
        {preview && <PreviewTable preview={preview} />}
        <form className="ticket-form confirm-form" onSubmit={e => {
          e.preventDefault();
          void act(`/api/v1/broadcasts/${id}/confirm`, {
            expected_version: b.version, service_only: true,
            ...(later ? { send_at: new Date(sendAt).toISOString() } : {}),
          });
        }}>
          <h3>Подтверждение</h3>
          <label className="checkbox-label"><input type="checkbox" checked={service} onChange={e => setService(e.target.checked)} required />
            {platform ? "Это сервисное сообщение, не реклама" : "Это сервисное сообщение для жителей, не реклама"}</label>
          <fieldset className="choice-row"><legend>Когда отправить</legend>
            <label className="checkbox-label"><input type="radio" name="when" checked={!later} onChange={() => setLater(false)} />Сейчас</label>
            <label className="checkbox-label"><input type="radio" name="when" checked={later} onChange={() => setLater(true)} />По расписанию</label>
            {later && <label>Дата и время<input type="datetime-local" value={sendAt} onChange={e => setSendAt(e.target.value)} required /></label>}
          </fieldset>
          <p className="muted">Тихие часы чата переносят пост до их окончания. Отменить можно до отправки.</p>
          <button className="ticket-button" disabled={action.busy || !service}>{later ? "Запланировать отправку" : "Подтвердить и отправить"}</button>
        </form>
      </>}
      {b.status === "scheduled" && <div className="button-row">
        <button className="ticket-button" disabled={action.busy}
          onClick={() => void act(`/api/v1/broadcasts/${id}/cancel`, { expected_version: b.version })}>Отменить отправку</button>
      </div>}
      {b.status === "sent" && <>
        <StatsTable stats={b.stats ?? []} />
        {!b.retracted_at && <div className="button-row">
          {(b.allowed_actions ?? []).includes("edit_content") && !edit &&
            <button className="ticket-button secondary" onClick={() => setEdit({ title: b.title, body: b.body })}>Исправить текст</button>}
          {(b.allowed_actions ?? []).includes("close_poll") &&
            <button className="ticket-button secondary" disabled={action.busy}
              onClick={() => void act(`/api/v1/broadcasts/${id}/close-poll`, { expected_version: b.version })}>Закрыть опрос</button>}
          {!confirmRetract ? <button className="ticket-button secondary" onClick={() => setConfirmRetract(true)}>Удалить сообщение</button>
            : <div className="admin-feedback" role="group" aria-label="Подтверждение удаления">
              <p>Пост в домовом чате заменится на «Сообщение удалено автором», из ленты сообщение исчезнет. Уже доставленные личные сообщения останутся.</p>
              <button className="ticket-button" disabled={action.busy}
                onClick={() => void act(`/api/v1/broadcasts/${id}/retract`, { expected_version: b.version })}>Подтвердить удаление</button>
              <button className="ticket-button secondary" onClick={() => setConfirmRetract(false)}>Отмена</button></div>}
        </div>}
        {edit && <form className="ticket-form" onSubmit={async e => {
          e.preventDefault();
          const result = await act(`/api/v1/broadcasts/${id}/edit`, { expected_version: b.version, ...edit });
          if (result) setEdit(null);
        }}>
          <h3>Исправить отправленное</h3>
          <p className="muted">Пост в домовом чате изменится в том же сообщении, нового поста не будет. Личные сообщения не меняются.</p>
          <label>Заголовок<input value={edit.title} required minLength={3} maxLength={200} onChange={e => setEdit({ ...edit, title: e.target.value })} /></label>
          <label>Текст<textarea value={edit.body} required maxLength={3000} rows={5} onChange={e => setEdit({ ...edit, body: e.target.value })} /></label>
          <div className="button-row"><button className="ticket-button" disabled={action.busy}>Сохранить исправление</button>
            <button type="button" className="ticket-button secondary" onClick={() => setEdit(null)}>Отмена</button></div>
        </form>}
      </>}
    </>}
  </section>;
}

function PreviewTable({ preview }: { preview: Schema["BroadcastPreview"] }) {
  return <div className="table-scroll"><table className="admin-table" aria-label="Предпросмотр получателей">
    <caption>Домов в аудитории: {preview.houses}{preview.companies ? ` · УК: ${preview.companies}` : ""}</caption>
    <thead><tr><th>Канал</th><th>Всего</th><th>Получат</th><th>Пропущено</th></tr></thead>
    <tbody>{preview.channels.map(c => <tr key={c.channel}><td>{channelLabels[c.channel]}</td><td>{c.targets}</td>
      <td>{c.will_send}</td><td><Skipped skipped={c.skipped} /></td></tr>)}</tbody>
  </table></div>;
}

function StatsTable({ stats }: { stats: Schema["ChannelStats"][] }) {
  return <div className="table-scroll"><table className="admin-table" aria-label="Статистика отправки">
    <thead><tr><th>Канал</th><th>Доставлено</th><th>Ошибка</th><th>Исход неизвестен</th><th>Ожидает</th><th>Тихие часы</th><th>Пропущено</th></tr></thead>
    <tbody>{stats.map(s => <tr key={s.channel}><td>{channelLabels[s.channel]}</td><td>{s.accepted}</td><td>{s.failed}</td>
      <td>{s.unknown}</td><td>{s.pending}</td><td>{s.deferred_quiet_hours}</td><td><Skipped skipped={s.skipped} /></td></tr>)}</tbody>
  </table></div>;
}

export function PollResultsView({ poll }: { poll: Schema["PollResults"] }) {
  return <div className="poll-results">
    <h3>{poll.question}</h3>
    <p className="muted">{poll.closed ? "Опрос закрыт" : `Голосование до ${when(poll.closes_at)}`} · проголосовали: {poll.voters}</p>
    <ul className="plain-list">{poll.options.map(o => <li key={o.id}>{o.label} — {o.votes} ({Math.round(o.share * 100)}%)</li>)}</ul>
    <p className="muted">Предварительный опрос. Не является решением общего собрания собственников.</p>
  </div>;
}

// ============================================================ настройки чата

export function ChatSettingsPanel({ bindingId }: { bindingId: string }) {
  const r = useRead<Schema["ChatSettingsView"]>(`/api/v1/chat-bindings/${bindingId}/settings`);
  const action = useAction(r.refresh);
  const [form, setForm] = useState<Schema["ChatSettingsUpdate"] | null>(null);
  const [saved, setSaved] = useState(false);
  const view = r.data;
  const value = form ?? (view ? {
    post_ticket_status: view.post_ticket_status, post_company_messages: view.post_company_messages,
    post_polls: view.post_polls, post_platform_messages: view.post_platform_messages,
    quiet_start: view.quiet_start, quiet_end: view.quiet_end,
  } : null);
  const noQuiet = value ? value.quiet_start === value.quiet_end : false;
  const flags: [keyof Schema["ChatSettingsUpdate"], string][] = [
    ["post_ticket_status", "Статусы заявок, созданных оператором или по /report"],
    ["post_company_messages", "Объявления и рассылки УК"],
    ["post_polls", "Опросы"],
    ["post_platform_messages", "Сообщения платформы ДомСигнал"],
  ];
  return <details className="passive-switch chat-settings">
    <summary>Что бот публикует в этом чате</summary>
    <Feedback loading={r.loading && !view} error={r.error} />
    {value && view && <form className="ticket-form" onSubmit={async e => {
      e.preventDefault(); setSaved(false);
      const result = await action.run(`/api/v1/chat-bindings/${bindingId}/settings`, value);
      if (result) { setForm(null); setSaved(true); }
    }}>
      <fieldset className="choice-row" disabled={!view.can_edit}><legend>По решению человека</legend>
        {flags.map(([name, label]) => <label key={name} className="checkbox-label"><input type="checkbox" checked={Boolean(value[name])}
          onChange={e => setForm({ ...value, [name]: e.target.checked })} />{label}</label>)}
      </fieldset>
      <p className="muted">Памятка безопасности и сообщение о чтении чата не отключаются: это автоматический голос бота.</p>
      <fieldset className="choice-row" disabled={!view.can_edit}><legend>Тихие часы, МСК</legend>
        <label className="checkbox-label"><input type="checkbox" checked={noQuiet}
          onChange={e => setForm({ ...value, quiet_start: e.target.checked ? "00:00" : "22:00", quiet_end: e.target.checked ? "00:00" : "08:00" })} />Без тихих часов</label>
        {!noQuiet && <div className="inline-form">
          <label>С<input type="time" value={value.quiet_start} required onChange={e => setForm({ ...value, quiet_start: e.target.value })} /></label>
          <label>До<input type="time" value={value.quiet_end} required onChange={e => setForm({ ...value, quiet_end: e.target.value })} /></label>
        </div>}
        <p className="muted">Объявления, опросы и необязательные правки ждут конца тихих часов; факт принятия заявки — нет.</p>
      </fieldset>
      <Feedback error={action.error || undefined} />
      {view.can_edit ? <button className="ticket-button" disabled={action.busy || !form}>Сохранить настройки</button>
        : <p className="muted">Настройки меняет администратор УК или ответственный за дом.</p>}
      {saved && <p role="status" className="muted">Настройки сохранены.</p>}
    </form>}
    {view && (view.history ?? []).length > 0 && <><h4>История изменений</h4><ol className="admin-history">
      {(view.history ?? []).map((row, i) => <li key={i}><time>{when(row.occurred_at)}</time> · {row.actor_name ?? "Сотрудник"}<p>{row.summary}</p></li>)}</ol></>}
  </details>;
}

// =============================================================== профиль УК

const profileFields: [keyof Schema["CompanyProfileUpdate"], string, string][] = [
  ["dispatcher_phone", "Аварийно-диспетчерская служба (телефон)", "tel"],
  ["phone", "Телефон", "tel"],
  ["email", "Почта", "email"],
  ["office_hours", "Часы работы", "text"],
  ["reception_hours", "Часы приёма", "text"],
  ["website", "Сайт", "url"],
  ["office_address", "Адрес офиса", "text"],
];
const profileErrors: Record<string, string> = {
  phone: "телефон", dispatcher_phone: "телефон диспетчерской", email: "почта", website: "сайт (начинается с https://)",
};

export function CompanyProfileForm({ base }: { base: string }) {
  const r = useRead<Schema["CompanyProfileView"]>(`${base}/profile`);
  const action = useAction(r.refresh);
  const [saved, setSaved] = useState(false);
  const view = r.data;
  return <section className="admin-detail" aria-label="Контакты для жителей">
    <h2>Контакты для жителей</h2>
    <p className="muted">Жители увидят эти сведения в разделе «Мой дом» с пометкой «по данным УК» и датой обновления.</p>
    <Feedback loading={r.loading && !view} error={r.error} />
    {view && <form className="ticket-form" onSubmit={async e => {
      e.preventDefault(); setSaved(false);
      const data = new FormData(e.currentTarget);
      const payload = Object.fromEntries(profileFields.map(([name]) => [name, String(data.get(name) ?? "").trim() || null]));
      const result = await action.run(`${base}/profile`, payload);
      if (result) setSaved(true);
    }}>
      <fieldset className="choice-row" disabled={!view.can_edit}>
        {profileFields.map(([name, label, type]) => <label key={name}>{label}
          <input name={name} type={type} defaultValue={view[name] ?? ""} maxLength={name === "office_address" ? 500 : 300} /></label>)}
      </fieldset>
      {action.error && <p role="alert" className="admin-feedback">{action.code === "validation_error"
        ? `Проверьте поля: ${Object.values(profileErrors).join(", ")}.` : action.error}</p>}
      {view.can_edit ? <button className="ticket-button" disabled={action.busy}>Сохранить контакты</button>
        : <p className="muted">Контакты заполняет администратор УК.</p>}
      {view.updated_at && <p className="muted">Обновлено {when(view.updated_at)}</p>}
      {saved && <p role="status" className="muted">Контакты сохранены.</p>}
    </form>}
  </section>;
}

export function HouseFactsForm({ base, house, refresh }: { base: string; house: Schema["CompanyHouseView"]; refresh: () => void }) {
  const action = useAction(refresh);
  return <details className="passive-switch"><summary>Сведения о доме для жителей</summary>
    <form className="inline-form" onSubmit={e => {
      e.preventDefault();
      const data = new FormData(e.currentTarget);
      const number = (name: string) => { const value = String(data.get(name) ?? "").trim(); return value ? Number(value) : null; };
      void action.run(`${base}/houses/${house.house_id}/facts`, { entrance_count: number("entrances"), floor_count: number("floors") });
    }}>
      <label>Подъездов<input name="entrances" type="number" min={1} max={100} inputMode="numeric" defaultValue={house.entrance_count ?? ""} /></label>
      <label>Этажей<input name="floors" type="number" min={1} max={200} inputMode="numeric" defaultValue={house.floor_count ?? ""} /></label>
      <button className="ticket-button secondary" disabled={action.busy}>Сохранить</button>
    </form>
    <p className="muted">Необязательно. Жители увидят «по данным УК»{house.facts_updated_at ? `, обновлено ${when(house.facts_updated_at)}` : ""}.</p>
    <Feedback error={action.error || undefined} />
  </details>;
}

// ================================================= уведомления и сводка

export function Notices({ base }: { base: string }) {
  const notices = useRead<Schema["PlatformNoticeList"]>(`${base}/platform-notices?limit=20`);
  const settings = useRead<Schema["StaffSettings"]>(`${base}/me/settings`);
  const action = useAction(settings.refresh);
  const s = settings.data;
  return <>
    <Title description="Сообщения платформы ДомСигнал и ваша ежедневная сводка">Уведомления</Title>
    <section className="admin-detail" aria-label="Ежедневная сводка">
      <h2>Ежедневная сводка в MAX</h2>
      <p>В 09:00 МСК бот пришлёт в личные сообщения: новые сигналы за сутки по силе, заявки без исполнителя, ожидающие проверки жителями, возвращённые в работу. В пустой день сообщения нет.</p>
      <Feedback loading={settings.loading && !s} error={settings.error ?? (action.error || undefined)} />
      {s && <>
        <p>Сводка: <strong>{s.daily_digest_enabled ? "включена" : "выключена"}</strong></p>
        {!s.max_linked && <p className="admin-feedback">Бот пока не может вам написать: откройте бота ДомСигнал в MAX и нажмите «Начать».</p>}
        <button className="ticket-button secondary" disabled={action.busy}
          onClick={() => void action.run(`${base}/me/settings`, { daily_digest_enabled: !s.daily_digest_enabled })}>
          {s.daily_digest_enabled ? "Выключить сводку" : "Включить сводку"}</button>
      </>}
    </section>
    <h2>Сообщения платформы</h2>
    <Feedback loading={notices.loading && !notices.data} error={notices.error} />
    {notices.data && (notices.data.items.length ? <ul className="admin-records">{notices.data.items.map(n => <li key={n.id}>
      <div><strong>{n.title}</strong><p className="pre-wrap">{n.body}</p></div><time>{when(n.sent_at)}</time></li>)}</ul>
      : <p className="state-panel">Сообщений платформы пока нет.</p>)}
  </>;
}

// ================================================================ приём

export function ReceptionAdmin({ base, admin }: { base: string; admin: boolean }) {
  const r = useRead<Schema["ReceptionSlotView"][]>(`${base}/reception-slots`);
  const action = useAction(r.refresh);
  const [starts, setStarts] = useState(() => localInput(new Date(Date.now() + 2 * 86400000)));
  return <>
    <Title description="Время приёма жителей и записи на него">Приём</Title>
    {admin && <form className="inline-form admin-detail" onSubmit={e => {
      e.preventDefault();
      const data = new FormData(e.currentTarget);
      void action.run(`${base}/reception-slots`, {
        starts_at: new Date(starts).toISOString(),
        duration_minutes: Number(data.get("duration") ?? 30),
        capacity: Number(data.get("capacity") ?? 1),
        place: String(data.get("place") ?? "").trim() || null,
      });
    }}>
      <label>Дата и время<input type="datetime-local" value={starts} required onChange={e => setStarts(e.target.value)} /></label>
      <label>Длительность, мин<input name="duration" type="number" min={5} max={240} defaultValue={30} required /></label>
      <label>Мест<input name="capacity" type="number" min={1} max={50} defaultValue={3} required /></label>
      <label>Место<input name="place" maxLength={500} placeholder="По умолчанию — адрес офиса" /></label>
      <button className="ticket-button">Добавить время приёма</button>
    </form>}
    <Feedback loading={r.loading && !r.data} error={r.error ?? (action.error || undefined)} />
    {r.data && (r.data.length ? <ul className="admin-records">{r.data.map(slot => <li key={slot.id}>
      <div><strong>{when(slot.starts_at)}</strong> · {slot.duration_minutes} мин · занято {slot.booked} из {slot.capacity}
        {slot.place && <p className="muted">{slot.place}</p>}
        {(slot.bookings ?? []).length > 0 && <ul className="plain-list">{(slot.bookings ?? []).map(b =>
          <li key={b.id}>{b.resident_name} · {b.house_address} · {b.topic}{b.status === "cancelled" ? " (отменена)" : ""}</li>)}</ul>}
      </div>
      <span className={`admin-status status-${slot.status}`}>{slot.status === "open" ? "Открыто" : "Отменено"}</span>
      {admin && slot.status === "open" && <button className="ticket-button secondary" disabled={action.busy}
        onClick={() => void action.run(`${base}/reception-slots/${slot.id}/cancel`)}>Отменить время</button>}
    </li>)}</ul> : <p className="state-panel">Время приёма пока не задано.{admin ? " Добавьте его формой выше." : ""}</p>)}
  </>;
}

