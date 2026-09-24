import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { Landing } from "./Landing";
import "./site.css";

/** Публичная страница продукта: `/site` и корень сайта в обычном браузере. */
export function renderLanding(root: HTMLElement) {
  createRoot(root).render(<StrictMode><Landing /></StrictMode>);
}
