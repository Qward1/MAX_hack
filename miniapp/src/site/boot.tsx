import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { Landing } from "./Landing";
import "../shared/styles/tokens.css";
import "./site.css";

/** Публичная страница продукта: `/site` и корень сайта в обычном браузере. */
export function renderLanding(root: HTMLElement) {
  // Корень сайта отдаёт общий index.html мини-приложения: у лендинга свой заголовок вкладки.
  document.title = "ДомСигнал — проблемы дома из домового чата в работу";
  createRoot(root).render(<StrictMode><Landing /></StrictMode>);
}
