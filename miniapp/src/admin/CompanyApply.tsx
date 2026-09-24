import { useCallback, useState } from "react";
import { ApiClient } from "../shared/api/client";
import { useResource } from "../shared/api/useResource";
import { Feedback, formValue, submitted, type Schema } from "./administration";

const client = new ApiClient();
const STATUS_TITLES: Record<string, string> = {
  submitted: "Заявка получена", under_review: "Заявка на рассмотрении", needs_info: "Платформе нужны уточнения",
  approved: "Заявка одобрена", rejected: "Заявка отклонена", cancelled: "Заявка отменена",
};
const STEPS = ["submitted", "under_review", "approved"] as const;

function PublicHeader() {
  return <header className="public-header">
    <a className="admin-brand" href="/">ДомСигнал</a>
    <nav aria-label="Навигация"><a className="ticket-button secondary" href="/login">Вход</a></nav>
  </header>;
}

export function CompanyApply() {
  const [received, setReceived] = useState<Schema["ApplicationReceived"] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  return <><PublicHeader /><main className="company-apply"><aside>
    <p className="eyebrow">Для управляющих компаний</p><h1>Подключите домовые чаты к ДомСигналу</h1>
    <p>Бот замечает проблемы дома в переписке жителей, а ваша команда получает их очередью заявок с понятным следующим шагом.</p>
    <ol><li>Вы подаёте заявку и получаете ссылку на страницу статуса.</li>
      <li>Платформа проверяет организацию и выдаёт квоту — сколько чатов можно подключить.</li>
      <li>На странице статуса вы создаёте аккаунт администратора: пароль и приложение-аутентификатор.</li>
      <li>В кабинете добавляете дома, приглашаете сотрудников и подключаете чаты.</li></ol>
  </aside><section className="admin-detail">{received ? <>
    <h2>Заявка принята</h2>
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
    <form className="ticket-form" onSubmit={async e => {
      const data = submitted(e); setBusy(true); setError("");
      try {
        const addresses = formValue(data, "addresses").split("\n").map(line => line.trim()).filter(Boolean);
        setReceived(await client.request<Schema["ApplicationReceived"]>("/api/v1/onboarding/company-applications", { method: "POST", body: JSON.stringify({
          legal_name: formValue(data, "legal_name"), short_name: formValue(data, "short_name"), inn: formValue(data, "inn"),
          contact_name: formValue(data, "contact_name"), contact_position: formValue(data, "contact_position") || null,
          contact_email: formValue(data, "email") || null, contact_phone: formValue(data, "phone") || null,
          comment: formValue(data, "comment") || null, requested_chat_count: Number(formValue(data, "chats")),
          house_addresses: addresses,
        }) }));
      } catch (e) { setError(e instanceof Error ? e.message : "Не удалось отправить заявку"); }
      finally { setBusy(false); }
    }}><h2>Заявка управляющей компании</h2>
      <label>Полное наименование<input name="legal_name" required minLength={2} maxLength={300} autoComplete="organization" /></label>
      <label>Краткое наименование<input name="short_name" required minLength={2} maxLength={200} /></label>
      <label>ИНН<input name="inn" required inputMode="numeric" pattern="(?:[0-9]{10}|[0-9]{12})" maxLength={12} /></label>
      <p className="muted">Проверяется формат ИНН. Проверка по данным ФНС не выполняется.</p>
      <label>Сколько домовых чатов хотите подключить<input name="chats" type="number" required min={1} max={1000} defaultValue={1} inputMode="numeric" /></label>
      <p className="muted">Каждый чат — один слот, включая чаты отдельных подъездов. Итоговую квоту назначит платформа.</p>
      <label>Адреса домов<textarea name="addresses" maxLength={25000} placeholder={"Необязательно. Один адрес в строке, например:\nКазань, ул. Баумана, 1"} /></label>
      <label>Контактное лицо<input name="contact_name" required minLength={2} maxLength={200} autoComplete="name" /></label>
      <label>Должность<input name="contact_position" maxLength={200} autoComplete="organization-title" /></label>
      <label>Электронная почта<input type="email" name="email" maxLength={254} autoComplete="email" /></label>
      <label>Телефон<input type="tel" name="phone" maxLength={40} autoComplete="tel" /></label>
      <p className="muted">Укажите хотя бы один способ связи: телефон или почту.</p>
      <label>Комментарий<textarea name="comment" maxLength={2000} /></label>
      <Feedback error={error} /><button className="ticket-button" disabled={busy}>{busy ? "Отправляем…" : "Подать заявку"}</button>
    </form>}</section></main></>;
}

/** Страница статуса заявки по секретной ссылке `/company/apply/status/<token>`. */
export function ApplicationStatus({ token }: { token: string }) {
  const load = useCallback((signal: AbortSignal) => client.request<Schema["ApplicationStatusView"]>(
    "/api/v1/onboarding/application-status", { method: "POST", body: JSON.stringify({ token }), signal }), [token]);
  const r = useResource(`application-status:${token}`, load);
  const [view, setView] = useState<Schema["ApplicationStatusView"] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const data = view ?? (r.error ? undefined : r.data);
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
      <p className="muted">Заявка «{data.short_name}» от {new Date(data.submitted_at).toLocaleDateString("ru-RU")}</p>
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
      {data.messages.length > 0 && <section className="admin-detail"><h2>Вопросы и ответы</h2>
        <ol className="message-list">{data.messages.map((m, i) => <li key={i} className={`message-${m.author}`}>
          <strong>{m.author === "platform" ? "Платформа" : "Вы"}</strong><time>{new Date(m.created_at).toLocaleString("ru-RU")}</time><p>{m.text}</p></li>)}</ol></section>}
      {data.can_reply && <form className="ticket-form admin-detail" onSubmit={async e => {
        const form = e.currentTarget; const text = formValue(submitted(e), "text");
        if (await reply(text)) form.reset();
      }}><h2>Ответ платформе</h2>
        <label>Ваш ответ<textarea name="text" required maxLength={2000} /></label>
        <button className="ticket-button" disabled={busy}>{busy ? "Отправляем…" : "Отправить ответ"}</button></form>}
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
