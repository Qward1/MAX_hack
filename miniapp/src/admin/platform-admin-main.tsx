import { createRoot } from "react-dom/client";
import { PlatformApp } from "./PlatformApp";
import { EmployeeGate } from "./EmployeeGate";
import "../shared/styles/main.css";
import "./admin.css";
import "./administration.css";
import "./system-last.css";
createRoot(document.getElementById("root")!).render(<EmployeeGate platform><PlatformApp /></EmployeeGate>);
