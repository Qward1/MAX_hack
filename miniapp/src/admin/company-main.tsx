import { createRoot } from "react-dom/client";
import { ApplicationStatus, CompanyApply } from "./CompanyApply";
import "../shared/styles/main.css";
import "./admin.css";
import "./administration.css";
import "./system-last.css";

// `/company/apply/status/<token>` — страница статуса заявки (D2); иначе форма заявки.
const status = window.location.pathname.match(/^\/company\/apply\/status\/([A-Za-z0-9_-]{32,100})\/?$/);
// Вкладка называет задачу страницы: форма и статус заявки — один entry.
if (status) document.title = "Статус заявки УК · ДомСигнал";
createRoot(document.getElementById("root")!).render(status ? <ApplicationStatus token={status[1]} /> : <CompanyApply />);
