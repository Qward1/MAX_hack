import { createRoot } from "react-dom/client";
import { CompanyApply } from "./CompanyApply";
import "../shared/styles/main.css";
import "./admin.css";
import "./administration.css";
createRoot(document.getElementById("root")!).render(<CompanyApply />);
