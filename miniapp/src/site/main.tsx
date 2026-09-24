import { renderLanding } from "./boot";

const root = document.getElementById("root");
if (!root) throw new Error("Root element is missing");
renderLanding(root);
