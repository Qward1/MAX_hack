// Тема, выбранная на этом устройстве, — до первой отрисовки, чтобы страница не
// мигала чужой темой (src/shared/theme.ts). Без выбора тему задаёт система и MAX.
// Кнопка с атрибутом data-theme-toggle (страницы без React, например /privacy)
// переключает тему здесь же.
(function () {
  var root = document.documentElement;
  var key = "ds:theme";
  try {
    var saved = window.localStorage.getItem(key);
    if (saved === "light" || saved === "dark") root.setAttribute("data-theme", saved);
  } catch (error) {
    /* хранилище недоступно — тема системы */
  }
  function current() {
    var chosen = root.getAttribute("data-theme");
    if (chosen === "light" || chosen === "dark") return chosen;
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  function label(button) {
    button.textContent = current() === "dark" ? "Включить светлую тему" : "Включить тёмную тему";
  }
  document.addEventListener("DOMContentLoaded", function () {
    var buttons = document.querySelectorAll("[data-theme-toggle]");
    Array.prototype.forEach.call(buttons, function (button) {
      button.hidden = false;
      label(button);
      button.addEventListener("click", function () {
        var next = current() === "dark" ? "light" : "dark";
        root.setAttribute("data-theme", next);
        try {
          window.localStorage.setItem(key, next);
        } catch (error) {
          /* выбор действует до перезагрузки */
        }
        Array.prototype.forEach.call(buttons, label);
      });
    });
  });
})();
