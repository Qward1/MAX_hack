import { formatStaffTime, formatDay } from "../shared/ui/format";
import { type ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { ApiClient, ApiProblem } from "../shared/api/client";
import { useResource, POLL_WAITING_MS } from "../shared/api/useResource";
import { Feedback, formValue, problemText, submitted, type Schema } from "./administration";

const client = new ApiClient();
const STATUS_TITLES: Record<string, string> = {
  submitted: "Заявка получена", under_review: "Заявка на рассмотрении", needs_info: "Платформе нужны уточнения",
  approved: "Заявка одобрена", rejected: "Заявка отклонена", cancelled: "Заявка отменена",
};
const STEPS = ["submitted", "under_review", "approved"] as const;
/** Что исправить, если сервер отклонил поле заявки (422). */
const APPLY_FIELDS: Record<string, string> = {
  legal_name: "полное наименование — от 2 символов", short_name: "краткое наименование — от 2 символов",
  inn: "ИНН — 10 или 12 цифр", requested_chat_count: "число чатов — от 1 до 1000",
  house_addresses: "адреса домов — каждый не короче 5 символов, не больше 50 строк",
  contact_name: "контактное лицо — от 2 символов", contact_position: "должность — до 200 символов",
  contact_email: "электронную почту — в виде name@example.ru", contact_phone: "телефон — цифры, например +7 900 000-00-00",
  body: "контакты — укажите телефон или электронную почту", comment: "комментарий — до 2000 символов",
};
/** Проверка адресов до отправки: называет строку, которую нужно исправить. */
export function addressProblem(lines: string[]): string {
  if (lines.length > 50) return "Укажите не больше 50 адресов — остальные можно передать платформе позже.";
  const short = lines.findIndex(line => line.length < 5);
  return short < 0 ? "" : `Адрес в строке ${short + 1} слишком короткий: укажите город, улицу и дом.`;
}

function PublicHeader() {
  return <header className="public-header">
    <a className="admin-brand" href="/">ДомСигнал</a>
    <nav aria-label="Навигация"><a className="ticket-button secondary" href="/login">Войти</a></nav>
  </header>;
}

/** Поле формы → поле API (для ошибок 422 от сервера). */
const API_FIELDS: Record<string, string> = {
  legal_name: "legal_name", short_name: "short_name", inn: "inn", requested_chat_count: "chats",
  house_addresses: "addresses", contact_name: "contact_name", contact_position: "contact_position",
  contact_email: "email", contact_phone: "phone", body: "email", comment: "comment",
};
type Errors = Record<string, string>;

/** Проверка до отправки: у каждого поля — своя понятная ошибка рядом с ним. */
export function applicationErrors(data: FormData): Errors {
  const errors: Errors = {};
  const value = (key: string) => formValue(data, key);
  if (value("legal_name").length < 2) errors.legal_name = "Укажите полное наименование — от 2 символов.";
  if (value("short_name").length < 2) errors.short_name = "Укажите краткое наименование — от 2 символов.";
  if (!/^(?:\d{10}|\d{12})$/.test(value("inn"))) errors.inn = "Укажите ИНН — 10 или 12 цифр.";
  const chats = Number(value("chats"));
  if (!Number.isInteger(chats) || chats < 1 || chats > 1000) errors.chats = "Укажите число чатов от 1 до 1000.";
  if (value("contact_name").length < 2) errors.contact_name = "Укажите контактное лицо — от 2 символов.";
  if (value("email") && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value("email")))
    errors.email = "Укажите почту в виде name@example.ru.";
  if (!value("email") && !value("phone")) errors.email = "Укажите телефон или электронную почту — хотя бы одно.";
  const addresses = value("addresses").split("\n").map(line => line.trim()).filter(Boolean);
  const address = addressProblem(addresses);
  if (address) errors.addresses = address;
  return errors;
}

const FIELD_ORDER = ["legal_name", "short_name", "inn", "chats", "contact_name", "contact_position", "email", "phone", "addresses", "comment"];

function Field({ name, label, optional, hint, error, children }: {
  name: string; label: string; optional?: boolean; hint?: string; error?: string;
  children: (props: { id: string; name: string; "aria-invalid"?: boolean; "aria-describedby"?: string }) => ReactNode;
}) {
  const id = `apply-${name}`;
  const described = [hint && `${id}-hint`, error && `${id}-error`].filter(Boolean).join(" ") || undefined;
  return <div className={`ds-field${error ? " has-error" : ""}`}>
    <label htmlFor={id}>{label}{optional && <span className="ds-optional"> (необязательно)</span>}</label>
    {hint && <p className="ds-hint" id={`${id}-hint`}>{hint}</p>}
    {error && <p className="ds-error" id={`${id}-error`}>{error}</p>}
    {children({ id, name, "aria-invalid": error ? true : undefined, "aria-describedby": described })}
  </div>;
}

export function CompanyApply() {
  const [received, setReceived] = useState<Schema["ApplicationReceived"] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [errors, setErrors] = useState<Errors>({});
  const [copied, setCopied] = useState(false);
  const summary = useRef<HTMLDivElement>(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => { if (attempt) summary.current?.focus(); }, [attempt]);
  const listed = FIELD_ORDER.filter(key => errors[key]);
  // Порядок в разметке — порядок телефона: вступление, форма, подробности.
  // На компьютере подробности стоят в левой колонке под вступлением (сетка).
  return <><PublicHeader /><main className="company-apply"><div className="apply-intro">
    <p className="eyebrow">Для управляющих компаний</p><h1>Подключите домовые чаты к ДомСигналу</h1>
    <p>Бот замечает проблемы дома в переписке жителей, а ваша команда получает их очередью заявок.</p>
    {!received && <a className="ticket-button secondary apply-jump" href="#company-application">Перейти к заявке</a>}
  </div><section className="admin-detail apply-card" id="company-application" aria-labelledby="company-application-title">{received ? <>
    <h2 id="company-application-title">Заявка принята</h2>
    <p>{received.message}</p>
    {received.status_url && <div className="one-time-link">
      <label>Ссылка на страницу статуса<input readOnly value={received.status_url} onFocus={e => e.target.select()} /></label>
      <div className="button-row">
        <a className="ticket-button" href={new URL(received.status_url).pathname}>Открыть страницу статуса</a>
        <button type="button" className="ticket-button secondary" onClick={async () => {
          try { await navigator.clipboard.writeText(received.status_url ?? ""); setCopied(true); } catch { setCopied(false); }
        }}>{copied ? "Скопировано" : "Скопировать ссылку"}</button></div>
      <p className="muted">Ссылка показывается один раз и заменяет пароль к заявке. Не пересылайте её посторонним.</p>
    </div>}
    <p className="muted">Заявка сама по себе не создаёт аккаунт и не открывает доступ к домам.</p></> :
    <form className="ticket-form apply-form" noValidate onSubmit={async e => {
      const data = submitted(e);
      const found = applicationErrors(data);
      setErrors(found); setError("");
      if (Object.keys(found).length) { setAttempt(n => n + 1); return; }
      const addresses = formValue(data, "addresses").split("\n").map(line => line.trim()).filter(Boolean);
      setBusy(true);
      try {
        setReceived(await client.request<Schema["ApplicationReceived"]>("/api/v1/onboarding/company-applications", { method: "POST", body: JSON.stringify({
          legal_name: formValue(data, "legal_name"), short_name: formValue(data, "short_name"), inn: formValue(data, "inn"),
          contact_name: formValue(data, "contact_name"), contact_position: formValue(data, "contact_position") || null,
          contact_email: formValue(data, "email") || null, contact_phone: formValue(data, "phone") || null,
          comment: formValue(data, "comment") || null, requested_chat_count: Number(formValue(data, "chats")),
          house_addresses: addresses,
        }) }));
      } catch (e) {
        // Ошибка сервера по полю — рядом с полем и в общем списке; иначе — общим сообщением.
        const fields: Errors = {};
        if (e instanceof ApiProblem) for (const item of e.problem.field_errors ?? []) {
          const key = API_FIELDS[item.field.split(".").at(-1) ?? ""];
          const hint = APPLY_FIELDS[item.field.split(".").at(-1) ?? ""];
          if (key && hint && !fields[key]) fields[key] = `Проверьте ${hint}.`;
        }
        if (Object.keys(fields).length) { setErrors(fields); setAttempt(n => n + 1); }
        else setError(problemText(e, APPLY_FIELDS, "Не удалось отправить заявку"));
      }
      finally { setBusy(false); }
    }}><h2 id="company-application-title">Заявка управляющей компании</h2>
      <p className="ds-hint">Займёт несколько минут. Все поля обязательны, кроме отмеченных «необязательно».</p>
      {listed.length > 0 && <div className="error-summary" role="alert" tabIndex={-1} ref={summary} aria-labelledby="apply-errors-title">
        <h3 id="apply-errors-title">Проверьте {listed.length === 1 ? "одно поле" : `поля: ${listed.length}`}</h3>
        <ul>{listed.map(key => <li key={key}><a href={`#apply-${key}`} onClick={ev => {
          ev.preventDefault(); document.getElementById(`apply-${key}`)?.focus();
        }}>{errors[key]}</a></li>)}</ul>
      </div>}
      <fieldset className="apply-group"><legend>Организация</legend>
        <Field name="legal_name" label="Полное наименование" error={errors.legal_name}>{props =>
          <input {...props} required minLength={2} maxLength={300} autoComplete="organization" />}</Field>
        <Field name="short_name" label="Краткое наименование" error={errors.short_name}>{props =>
          <input {...props} required minLength={2} maxLength={200} />}</Field>
        <Field name="inn" label="ИНН" hint="10 или 12 цифр. Проверяется формат, проверка по данным ФНС не выполняется." error={errors.inn}>{props =>
          <input {...props} required inputMode="numeric" maxLength={12} />}</Field>
        <Field name="chats" label="Сколько домовых чатов хотите подключить" error={errors.chats}
          hint="Каждый чат — один слот, включая чаты отдельных подъездов. Итоговую квоту назначит платформа.">{props =>
          <input {...props} type="number" required min={1} max={1000} defaultValue={1} inputMode="numeric" />}</Field>
      </fieldset>
      <fieldset className="apply-group"><legend>Контакт для связи</legend>
        <Field name="contact_name" label="Контактное лицо" error={errors.contact_name}>{props =>
          <input {...props} required minLength={2} maxLength={200} autoComplete="name" />}</Field>
        <Field name="contact_position" label="Должность" optional>{props =>
          <input {...props} maxLength={200} autoComplete="organization-title" />}</Field>
        <p className="ds-hint">Почта или телефон — нужно хотя бы одно.</p>
        <Field name="email" label="Электронная почта" error={errors.email}>{props =>
          <input {...props} type="email" maxLength={254} autoComplete="email" />}</Field>
        <Field name="phone" label="Телефон" error={errors.phone}>{props =>
          <input {...props} type="tel" maxLength={40} autoComplete="tel" placeholder="+7 900 000-00-00" />}</Field>
      </fieldset>
      <fieldset className="apply-group"><legend>Дополнительно</legend>
        <Field name="addresses" label="Адреса домов" optional hint="Один адрес в строке, например: Казань, ул. Баумана, 1. Не больше 50." error={errors.addresses}>{props =>
          <textarea {...props} maxLength={25000} />}</Field>
        <Field name="comment" label="Комментарий" optional error={errors.comment}>{props =>
          <textarea {...props} maxLength={2000} />}</Field>
      </fieldset>
      <Feedback error={error} /><div><button className="ticket-button" disabled={busy}>{busy ? "Отправляем…" : "Подать заявку"}</button></div>
    </form>}</section><div className="apply-more">
    <details className="ds-disclosure apply-steps"><summary>Как проходит подключение</summary>
      <ol className="ds-disclosure-body"><li>Вы подаёте заявку и получаете ссылку на страницу статуса.</li>
        <li>Платформа проверяет организацию и выдаёт квоту — сколько чатов можно подключить.</li>
        <li>На странице статуса вы создаёте аккаунт администратора: пароль и приложение-аутентификатор.</li>
        <li>В кабинете добавляете дома, приглашаете сотрудников и подключаете чаты.</li></ol></details>
    <p><a href="/privacy">Политика данных</a> — что бот читает в чатах, что хранит и как отключить чтение.</p>
  </div></main></>;
}

/** Страница статуса заявки по секретной ссылке `/company/apply/status/<token>`. */
export function ApplicationStatus({ token }: { token: string }) {
  const load = useCallback((signal: AbortSignal) => client.request<Schema["ApplicationStatusView"]>(
    "/api/v1/onboarding/application-status", { method: "POST", body: JSON.stringify({ token }), signal }), [token]);
  const r = useResource(`application-status:${token}`, load, { poll: POLL_WAITING_MS });
  const [view, setView] = useState<Schema["ApplicationStatusView"] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [botLink, setBotLink] = useState("");
  const data = view ?? (r.error ? undefined : r.data);
  async function notifyLink() {
    setBusy(true); setError("");
    try {
      const link = await client.request<Schema["NotifyLink"]>("/api/v1/onboarding/application-status/notify-link",
        { method: "POST", body: JSON.stringify({ token }) });
      setBotLink(link.bot_url);
    } catch (e) { setError(e instanceof Error ? e.message : "Не удалось подготовить ссылку на бота"); }
    finally { setBusy(false); }
  }
  async function reply(text: string) {
    setBusy(true); setError("");
    try { setView(await client.request<Schema["ApplicationStatusView"]>("/api/v1/onboarding/application-status/reply",
      { method: "POST", body: JSON.stringify({ token, text }) })); return true; }
    catch (e) { setError(e instanceof Error ? e.message : "Не удалось отправить ответ"); return false; }
    finally { setBusy(false); }
  }
  async function createAccount() {
    setBusy(true); setError("");
    try {
      const link = await client.request<Schema["AdminInvitationLink"]>("/api/v1/onboarding/application-status/admin-invitation",
        { method: "POST", body: JSON.stringify({ token }) });
      window.location.assign(new URL(link.invitation_url).pathname);
    } catch (e) { setError(e instanceof Error ? e.message : "Не удалось открыть создание аккаунта"); setBusy(false); }
  }
  const reached = data ? (data.status === "approved" ? 3 : data.status === "submitted" ? 1 : 2) : 0;
  return <><PublicHeader /><main className="application-status">
    <Feedback loading={r.loading && !data} error={r.error} />
    {data && <>
      <p className="muted">Заявка «{data.short_name}» от {formatDay(data.submitted_at)}</p>
      <h1>{STATUS_TITLES[data.status] ?? "Статус заявки"}</h1>
      {!["rejected", "cancelled"].includes(data.status) && <ol className="status-steps" aria-label="Этапы заявки">
        {STEPS.map((step, i) => <li key={step} className={i < reached ? "is-done" : undefined} aria-current={i === reached - 1 ? "step" : undefined}>
          {step === "submitted" ? "Заявка получена" : step === "under_review" ? "Проверка платформой" : "Одобрена"}</li>)}</ol>}
      {data.status === "approved" && <section className="admin-detail">
        <h2>Квота подключения чатов</h2>
        <p className="status-figure">{data.quota_unlimited ? "Без ограничения" : `${data.granted_chat_quota ?? 0} ${plural(data.granted_chat_quota ?? 0)}`}</p>
        {data.requested_chat_count != null && !data.quota_unlimited && data.granted_chat_quota !== data.requested_chat_count &&
          <p className="muted">Вы запрашивали: {data.requested_chat_count}. Расширение можно запросить из кабинета.</p>}
        {data.decision_reason && <p>{data.decision_reason}</p>}
        {data.admin_account === "create" && <>
          <p>Создайте аккаунт первого администратора: логин, пароль и приложение-аутентификатор (TOTP).</p>
          <button className="ticket-button" disabled={busy} onClick={() => void createAccount()}>{busy ? "Открываем…" : "Создать аккаунт администратора"}</button></>}
        {data.admin_account === "active" && <><p>Аккаунт администратора создан.</p><a className="ticket-button" href="/login">Войти в кабинет</a></>}
        {data.admin_account === "unavailable" && <p className="admin-feedback">Организация сейчас приостановлена. Свяжитесь с платформой по контакту из заявки.</p>}
      </section>}
      {data.status === "rejected" && data.decision_reason && <section className="admin-detail"><h2>Причина</h2><p>{data.decision_reason}</p></section>}
      {["submitted", "under_review"].includes(data.status) && <p>Платформа проверяет организацию. Решение и вопросы появятся на этой странице — сохраните её в закладки.</p>}
      {/* F-09: у отклонённой или отменённой заявки квоты и уведомлений больше нет. */}
      {!["approved", "rejected", "cancelled"].includes(data.status) && data.requested_chat_count != null &&
        <p className="muted">Запрошено: {data.requested_chat_count} {plural(data.requested_chat_count)}. Итоговую квоту назначит платформа.</p>}
      {data.messages.length > 0 && <section className="admin-detail"><h2>Вопросы и ответы</h2>
        <ol className="message-list">{data.messages.map((m, i) => <li key={i} className={`message-${m.author}`}>
          <strong>{m.author === "platform" ? "Платформа" : "Вы"}</strong><time>{formatStaffTime(m.created_at)}</time><p>{m.text}</p></li>)}</ol></section>}
      {data.can_reply && <form className="ticket-form admin-detail" onSubmit={async e => {
        const form = e.currentTarget; const text = formValue(submitted(e), "text");
        if (await reply(text)) form.reset();
      }}><h2>Ответ платформе</h2>
        <label>Ваш ответ<textarea name="text" required maxLength={2000} /></label>
        <button className="ticket-button" disabled={busy}>{busy ? "Отправляем…" : "Отправить ответ"}</button></form>}
      {!["rejected", "cancelled"].includes(data.status) && <section className="admin-detail notify-max">
        <h2>Уведомления в MAX</h2>
        {data.max_notifications && !botLink
          ? <p>Бот ДомСигнала присылает изменения статуса этой заявки в MAX.</p>
          : <p>Бот пришлёт в MAX сообщение, когда платформа задаст вопрос или примет решение. Ссылка на эту страницу в сообщениях не передаётся.</p>}
        {botLink ? <><a className="ticket-button" href={botLink} rel="noopener">Открыть бота в MAX</a>
          <p className="muted">В боте нажмите «Начать». Ссылка одноразовая.</p></>
          : <button className="ticket-button secondary" disabled={busy} onClick={() => void notifyLink()}>
            {data.max_notifications ? "Получать в другой аккаунт MAX" : "Получать уведомления в MAX"}</button>}
      </section>}
      {data.house_addresses.length > 0 && <details><summary>Адреса из заявки</summary><ul>{data.house_addresses.map(a => <li key={a}>{a}</li>)}</ul></details>}
      <Feedback error={error || undefined} />
    </>}
  </main></>;
}

function plural(n: number) {
  const mod10 = n % 10, mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return "чат";
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return "чата";
  return "чатов";
}
