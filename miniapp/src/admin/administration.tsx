import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from "react";
import { ticketClient } from "../shared/api/tickets";
import type { components } from "../shared/api/schema";
import { useResource } from "../shared/api/useResource";

export type Schema = components["schemas"];
export const adminClient = ticketClient;
export function useRead<T>(path: string, revision = 0) {
  const load = useCallback((signal: AbortSignal) => adminClient.request<T>(path, { signal }), [path]);
  const resource = useResource(`${path}:${revision}`, load);
  useEffect(() => { const refresh = () => resource.refresh(); window.addEventListener("administration-refresh", refresh);
    return () => window.removeEventListener("administration-refresh", refresh); }, [resource.refresh]);
  return resource;
}
export function useAction(refresh?: () => void) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function run<T>(path: string, payload: object = {}, key?: string): Promise<T | undefined> {
    if (busy) return;
    setBusy(true); setError("");
    try {
      const result = await adminClient.request<T>(path, { method: "POST", body: JSON.stringify(payload),
        headers: key ? { "Idempotency-Key": key } : {} });
      refresh?.();
      return result;
    } catch (e) { setError(e instanceof Error ? e.message : "Не удалось сохранить. Повторите попытку."); }
    finally { setBusy(false); }
  }
  return { busy, error, run };
}
export function Feedback({ loading, error }: { loading?: boolean; error?: unknown }) {
  return error ? <p role="alert" className="admin-feedback">{error instanceof Error ? error.message : String(error)}</p>
    : loading ? <p role="status">Загружаем…</p> : null;
}
export function Title({ children, description }: { children: ReactNode; description?: string }) {
  return <header className="page-header"><h1 id="page-title" tabIndex={-1}>{children}</h1>
    {description && <p className="muted">{description}</p>}</header>;
}
export const labels: Record<string, string> = {
  submitted: "Подана", under_review: "На рассмотрении", needs_info: "Нужны уточнения", approved: "Одобрена",
  rejected: "Отклонена", cancelled: "Отменена", active: "Действует", suspended: "Приостановлено",
  archived: "В архиве", pending: "Ожидает", claimed: "Регистрация начата", accepted: "Принято", expired: "Истекло",
  revoked: "Отозвано", operator: "Оператор", company_admin: "Администратор УК", responsible: "Ответственный",
  created: "Создано", connector_claimed: "Ссылка открыта в MAX", chat_detected: "Чат найден",
  max_verified: "MAX проверен", awaiting_approval: "Ожидает подтверждения", completed: "Подключён",
};
export function Status({ value }: { value: string }) {
  return <span className={`admin-status status-${value}`}>{labels[value] ?? value}</span>;
}
export function OneTimeLink({ url }: { url: string }) {
  const [copied, setCopied] = useState(false);
  return <section className="one-time-link" aria-label="Ссылка приглашения">
    <h2>Передайте ссылку сотруднику</h2><p>Ссылка показывается один раз. Сохраните её перед закрытием страницы.</p>
    <input aria-label="Одноразовая ссылка" readOnly value={url} onFocus={e => e.target.select()} />
    <button className="ticket-button" onClick={async () => {
      try { await navigator.clipboard.writeText(url); setCopied(true); }
      catch { setCopied(false); }
    }}>{copied ? "Скопировано" : "Скопировать ссылку"}</button>
    <p className="muted">Если копирование недоступно, выделите ссылку и скопируйте вручную.</p>
  </section>;
}
export function History({ rows }: { rows: Schema["AuditView"][] }) {
  const labels: Record<string, string> = {
    "company_application.submitted": "Заявка УК подана", "company_application.under_review": "Заявка УК на рассмотрении",
    "company_application.needs_info": "Запрошены уточнения по УК", "company_application.approved": "Заявка УК одобрена",
    "company_application.rejected": "Заявка УК отклонена", "company_application.cancelled": "Заявка УК отменена",
    "company.created": "Организация создана", "company.suspended": "Организация приостановлена", "company.active": "Организация возобновлена",
    "invitation.created": "Приглашение создано", "invitation.claimed": "Приглашение закреплено за сотрудником",
    "invitation.accepted": "Приглашение принято", "invitation.revoked": "Приглашение отозвано",
    "membership.created": "Доступ сотрудника активирован", "membership.revoked": "Доступ сотрудника отозван",
    "assignment.changed": "Назначение на дом изменено", "first_admin.reissued": "Первое приглашение перевыпущено",
    "house_request.submitted": "Заявка на дом подана", "house_request.under_review": "Заявка на дом на рассмотрении",
    "house_request.needs_info": "Запрошены уточнения по дому", "house_request.approved": "Заявка на дом одобрена",
    "house_request.rejected": "Заявка на дом отклонена", "house_request.cancelled": "Заявка на дом отменена",
    "management.approved": "Управление домом подтверждено", "platform.bootstrapped": "Оператор платформы создан",
    "house.open_access_enabled": "Открытый доступ к дому включён",
    "house.open_access_disabled": "Открытый доступ к дому выключен",
    "house.open_access_closed_by_platform": "Открытый доступ к дому закрыт платформой",
  };
  return <ol className="admin-history">{rows.map((r, i) => <li key={i}>
    <time>{new Date(r.occurred_at).toLocaleString("ru-RU")}</time> · {labels[r.event.replace(/^administration\./, "")] ?? "Административное действие"}
    {r.reason && <p>{r.reason}</p>}</li>)}</ol>;
}
export const formValue = (data: FormData, key: string) => String(data.get(key) ?? "").trim();
export const submitted = (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); return new FormData(event.currentTarget); };
export function useRoute() {
  const [url, setUrl] = useState(new URL(window.location.href));
  useEffect(() => { const update = () => setUrl(new URL(window.location.href));
    window.addEventListener("popstate", update); return () => window.removeEventListener("popstate", update); }, []);
  const navigate = (href: string) => { window.history.pushState(null, "", href); setUrl(new URL(window.location.href)); };
  return { url, navigate };
}

export function dateInput(value: string | Date) {
  const date = new Date(value);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}
