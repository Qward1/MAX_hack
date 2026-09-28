import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { EmployeeGate } from "./EmployeeGate";
import { adminClient, type Schema } from "./administration";
import { ThemeToggle } from "../shared/ui/ThemeToggle";
import "../shared/styles/main.css";
import "./admin.css";
import "./administration.css";
import "./system-last.css";

/**
 * Единый вход `/login` (D2): сотрудник УК и суперадмин входят одной формой
 * (пароль + TOTP, A-10) и попадают в свой кабинет по роли с сервера.
 */
export function LoginDestinations() {
  const [data, setData] = useState<Schema["EmployeeDestinations"] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    adminClient.request<Schema["EmployeeDestinations"]>("/api/v1/auth/employee/destinations").then(result => {
      if (!active) return;
      if (result.platform && !result.companies.length) window.location.replace("/platform-admin/");
      else if (!result.platform && result.companies.length) window.location.replace("/admin/");
      else setData(result);
    }).catch(() => { if (active) setError("Не удалось определить кабинет. Обновите страницу."); });
    return () => { active = false; };
  }, []);
  return <main className="auth-layout"><ThemeToggle className="auth-theme-toggle" /><section className="auth-card">
    {error ? <p role="alert">{error}</p> : !data ? <p role="status">Открываем кабинет…</p> : data.platform ? <>
      <h1>Выберите кабинет</h1>
      <div className="button-row"><a className="ticket-button" href="/platform-admin/">Управление платформой</a>
        <a className="ticket-button secondary" href="/admin/">Кабинет управляющей компании</a></div>
    </> : <>
      <h1>Нет доступных кабинетов</h1>
      <p>Ваш доступ к управляющей компании отозван или организация приостановлена. Обратитесь к администратору УК.</p>
    </>}
  </section></main>;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode><EmployeeGate unified><LoginDestinations /></EmployeeGate></StrictMode>,
);
