import { StrictMode, useEffect } from "react";
import { createRoot } from "react-dom/client";
import { CompanyPortal } from "./CompanyPortal";
import { InvitationAccept } from "./InvitationAccept";
import { EmployeeGate } from "./EmployeeGate";
import "../shared/styles/main.css";
import "./admin.css";
import "./administration.css";
import "./system-last.css";
const root = document.getElementById("root");
if (!root) throw new Error("Root element is missing");
const path = window.location.pathname;
const secret = (prefix: string) => path.startsWith(prefix) ? path.slice(prefix.length).split("/")[0] || undefined : undefined;
const invitationToken = secret("/admin/invite/");
// D2: новый пароль по ссылке сброса и регистрация по открытой ссылке УК.
const resetToken = secret("/admin/reset/");
const joinCode = secret("/join/");
// Вкладка называет задачу страницы, а не общий кабинет.
if (invitationToken) document.title = "Приглашение в кабинет · ДомСигнал";
else if (resetToken) document.title = "Новый пароль · ДомСигнал";
else if (joinCode) document.title = "Регистрация сотрудника · ДомСигнал";

/** После входа по ссылке — в кабинет без секрета в адресе. */
function OpenCabinet() {
  useEffect(() => { window.location.replace("/admin/"); }, []);
  return <main className="auth-layout"><p role="status">Открываем кабинет…</p></main>;
}

createRoot(root).render(
  <StrictMode>
    <EmployeeGate invitationToken={invitationToken} resetToken={resetToken} joinCode={joinCode}>
      {invitationToken ? <InvitationAccept token={invitationToken} /> : resetToken || joinCode ? <OpenCabinet /> : <CompanyPortal />}
    </EmployeeGate>
  </StrictMode>,
);
