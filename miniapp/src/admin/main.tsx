import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { AdminApp } from "./AdminApp";
import { EmployeeGate } from "./EmployeeGate";
import "../shared/styles/main.css";
import "./admin.css";
const root = document.getElementById("root");
if (!root) throw new Error("Root element is missing");
createRoot(root).render(
  <StrictMode>
    <EmployeeGate><AdminApp /></EmployeeGate>
  </StrictMode>,
);
