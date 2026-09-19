import { useState } from "react";
import { ApiClient } from "../shared/api/client";
import { Feedback, formValue, submitted, type Schema } from "./administration";

const client = new ApiClient();
export function CompanyApply() {
  const [received, setReceived] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  return <main className="company-apply"><aside><a className="admin-brand" href="/company/apply">ДомСигнал</a>
    <p className="eyebrow">Для управляющих компаний</p><h1>Работа с домом начинается с команды.</h1>
    <p>Подайте заявку. После рассмотрения первый администратор получит приглашение и сможет собрать команду, запросить управление домами и подключить MAX-чаты.</p>
    <ol><li>Заявка компании</li><li>Рассмотрение платформой</li><li>Приглашение администратора</li></ol>
  </aside><section className="admin-detail">{received ? <><h2>Данные получены</h2>
    <p>Для уточнений с вами свяжутся вручную по указанному контакту. Заявка сама по себе не создаёт аккаунт и не открывает доступ к домам.</p></> :
    <form className="ticket-form" onSubmit={async e => {
      const data = submitted(e); setBusy(true); setError("");
      try {
        await client.request<Schema["ApplicationReceived"]>("/api/v1/onboarding/company-applications", { method: "POST", body: JSON.stringify({
          legal_name: formValue(data, "legal_name"), short_name: formValue(data, "short_name"), inn: formValue(data, "inn"),
          contact_name: formValue(data, "contact_name"), contact_email: formValue(data, "email") || null,
          contact_phone: formValue(data, "phone") || null, comment: formValue(data, "comment") || null,
        }) }); setReceived(true);
      } catch (e) { setError(e instanceof Error ? e.message : "Не удалось отправить заявку"); }
      finally { setBusy(false); }
    }}><h2>Заявка управляющей компании</h2>
      <label>Полное наименование<input name="legal_name" required minLength={2} maxLength={300} autoComplete="organization" /></label>
      <label>Краткое наименование<input name="short_name" required minLength={2} maxLength={200} /></label>
      <label>ИНН<input name="inn" required inputMode="numeric" pattern="(?:[0-9]{10}|[0-9]{12})" maxLength={12} /></label>
      <p className="muted">Проверяется формат ИНН. Проверка по данным ФНС не выполняется.</p>
      <label>Контактное лицо<input name="contact_name" required minLength={2} maxLength={200} autoComplete="name" /></label>
      <label>Электронная почта<input type="email" name="email" maxLength={254} autoComplete="email" /></label>
      <label>Телефон<input type="tel" name="phone" maxLength={40} autoComplete="tel" /></label>
      <p className="muted">Укажите хотя бы один способ связи: телефон или почту.</p>
      <label>Комментарий<textarea name="comment" maxLength={2000} /></label>
      <Feedback error={error} /><button className="ticket-button" disabled={busy}>{busy ? "Отправляем…" : "Подать заявку"}</button>
    </form>}</section></main>;
}
