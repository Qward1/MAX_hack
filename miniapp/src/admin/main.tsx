import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { CompanyPortal } from "./CompanyPortal";
import { InvitationAccept } from "./InvitationAccept";
import { EmployeeGate } from "./EmployeeGate";
import "../shared/styles/main.css";
import "./admin.css";
import "./administration.css";
const root = document.getElementById("root");
if (!root) throw new Error("Root element is missing");
const invitationToken = window.location.pathname.startsWith("/admin/invite/") ? window.location.pathname.split("/").pop() : undefined;
createRoot(root).render(
  <StrictMode>
    <EmployeeGate invitationToken={invitationToken}>{invitationToken ? <InvitationAccept token={invitationToken} /> : <CompanyPortal />}</EmployeeGate>
  </StrictMode>,
);
