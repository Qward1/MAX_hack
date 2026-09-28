import { formatStaffTime } from "../shared/ui/format";
import { createContext, useCallback, useContext, useEffect, useState, type FormEvent, type ReactNode } from "react";
import { ApiProblem } from "../shared/api/client";
import { ticketClient } from "../shared/api/tickets";
import type { components } from "../shared/api/schema";
import { notify } from "../shared/ui/Toast";
import { type ResourceOptions, useResource } from "../shared/api/useResource";

export type Schema = components["schemas"];
/**
 * Проверочный аккаунт жюри в демо-УК (F1 §5.5): разрушающие действия над
 * витриной закрыты и в API (403 `showcase_protected`), и здесь — кнопка
 * выключена, рядом та же фраза, что у сервера.
 */
export const SHOWCASE_NOTE = "Недоступно для проверочного аккаунта: это действие изменило бы витрину, которую проверяют и другие.";
export const ShowcaseLock = createContext(false);
export function useShowcaseLock() { return useContext(ShowcaseLock); }
export function LockNote({ show }: { show: boolean }) {
  return show ? <p className="muted showcase-note">{SHOWCASE_NOTE}</p> : null;
}
export const adminClient = ticketClient;
export function useRead<T>(path: string, revision = 0, options: ResourceOptions = {}) {
  const load = useCallback((signal: AbortSignal) => adminClient.request<T>(path, { signal }), [path]);
  const resource = useResource(`${path}:${revision}`, load, options);
  useEffect(() => { const refresh = () => resource.refresh(); window.addEventListener("administration-refresh", refresh);
    return () => window.removeEventListener("administration-refresh", refresh); }, [resource.refresh]);
  return resource;
}
/**
 * Текст ошибки для формы при 422: правило сервиса уже сказано по-русски
 * («Опрос должен быть открыт хотя бы 10 минут») — показать его; техническая
 * ошибка схемы — назвать поля по словарю `fields`; иначе detail проблемы.
 */
export function problemText(e: unknown, fields: Record<string, string> = {}, fallback = "Не удалось сохранить. Повторите попытку."): string {
  if (e instanceof ApiProblem && e.problem.code === "validation_error") {
    const errors = e.problem.field_errors ?? [];
    const told = errors.map(f => f.message).filter(message => /[а-яё]/i.test(message ?? ""));
    if (told.length) return [...new Set(told)].join(" ");
    const named = errors.map(f => fields[f.field.split(".")[1] ?? f.field]).filter(Boolean);
    return named.length ? `Проверьте: ${[...new Set(named)].join("; ")}.` : "Проверьте заполнение полей формы.";
  }
  return e instanceof Error ? e.message : fallback;
}
/**
 * Действие кабинета: занятость, ошибка у формы и — если задано `success` —
 * общее уведомление о результате (F-14). Введённое при ошибке не теряется.
 */
export function useAction(refresh?: () => void, fields: Record<string, string> = {}, success?: string) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [code, setCode] = useState("");
  async function run<T>(path: string, payload: object = {}, key?: string): Promise<T | undefined> {
    if (busy) return;
    setBusy(true); setError(""); setCode("");
    try {
      const result = await adminClient.request<T>(path, { method: "POST", body: JSON.stringify(payload),
        headers: key ? { "Idempotency-Key": key } : {} });
      refresh?.();
      if (success) notify(success);
      return result;
    } catch (e) {
      setError(problemText(e, fields));
      setCode(e instanceof ApiProblem ? e.problem.code : "");
    }
    finally { setBusy(false); }
  }
  return { busy, error, code, run };
}
export function Feedback({ loading, error }: { loading?: boolean; error?: unknown }) {
  return error ? <p role="alert" className="admin-feedback">{error instanceof Error ? error.message : String(error)}</p>
    : loading ? <p role="status">Загружаем…</p> : null;
}
/** Заголовок страницы кабинета: h1, описание на ширину контента и действие справа (U-11). */
export function Title({ children, description, actions }: { children: ReactNode; description?: string; actions?: ReactNode }) {
  return <header className="page-header"><h1 id="page-title" tabIndex={-1}>{children}</h1>
    {description && <p className="muted">{description}</p>}
    {actions && <div className="page-actions">{actions}</div>}</header>;
}
export const labels: Record<string, string> = {
  submitted: "Подана", under_review: "На рассмотрении", needs_info: "Нужны уточнения", approved: "Одобрена",
  rejected: "Отклонена", cancelled: "Отменена", active: "Действует", suspended: "Приостановлено",
  archived: "В архиве", pending: "Ожидает", claimed: "Регистрация начата", accepted: "Принято", expired: "Истекло",
  revoked: "Отозвано", operator: "Оператор", company_admin: "Администратор УК", responsible: "Ответственный",
  created: "Создано", connector_claimed: "Ссылка открыта в MAX", chat_detected: "Чат найден",
  max_verified: "MAX проверен", awaiting_approval: "Ожидает подтверждения", completed: "Подключён",
  partially_approved: "Одобрено частично", used: "Использована",
};
/** Коды отказа подключения чата — словами для кабинета. */
export const connectionErrors: Record<string, string> = {
  CHAT_QUOTA_EXCEEDED: "Лимит подключённых чатов исчерпан",
  tenant_suspended: "Организация приостановлена: новые чаты не подключаются",
  chat_already_bound: "Этот чат уже подключён к другому дому",
  connector_not_chat_admin: "Подключающий больше не администратор чата",
  bot_permission_missing: "Боту не выданы права администратора с чтением сообщений",
  bot_removed: "Бота удалили из чата",
  connection_expired: "Срок запроса истёк — создайте новый",
  management_not_active: "Управление домом не действует",
  connector_connection_in_progress: "У администратора чата уже идёт другое подключение",
  chat_type_unsupported: "Подключить можно только групповой чат MAX",
  connection_code_used: "Код подключения уже использован — начните подключение заново",
  connection_not_detected: "Бот ещё не появился в группе",
  connection_not_verified: "Проверка в MAX ещё не прошла",
  max_temporarily_unavailable: "MAX временно недоступен — повторите через минуту",
  max_not_configured: "Связь с MAX на сервере не настроена",
};
export function Status({ value }: { value: string }) {
  return <span className={`admin-status status-${value}`}>{labels[value] ?? value}</span>;
}
export function OneTimeLink({ url, title = "Передайте ссылку сотруднику", label = "Ссылка приглашения" }: { url: string; title?: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  return <section className="one-time-link" aria-label={label}>
    <h2>{title}</h2><p>Ссылка показывается один раз. Сохраните её перед закрытием страницы.</p>
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
    "company_application.answered": "Заявитель ответил на вопросы",
    "company_application.notify_link": "Заявитель запросил уведомления в MAX", "chat_quota.set": "Квота чатов изменена",
    "chat_quota_request.submitted": "Запрошено расширение квоты", "chat_quota_request.approved": "Расширение квоты одобрено",
    "chat_quota_request.partially_approved": "Расширение квоты одобрено частично", "chat_quota_request.rejected": "В расширении квоты отказано",
    "credential_reset.password": "Выдана ссылка сброса пароля", "credential_reset.password_mfa": "Выдана ссылка сброса пароля и MFA",
    "credential_reset.used": "Пароль задан по ссылке сброса", "open_registration.enabled": "Открытая регистрация включена",
    "open_registration.closed": "Открытая регистрация закрыта", "open_registration.registered": "Сотрудник зарегистрировался по ссылке",
    "open_registration.joined": "Сотрудник по ссылке получил доступ",
  };
  return <ol className="admin-history">{rows.map((r, i) => <li key={i}>
    <time>{formatStaffTime(r.occurred_at)}</time> · {labels[r.event.replace(/^administration\./, "")] ?? "Административное действие"}
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
