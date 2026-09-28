import { useTheme } from "../theme";
import { IconMoon, IconSun } from "./icons";

/**
 * Переключатель «светлая / тёмная тема» для шапки любой поверхности.
 * Подпись называет действие: в светлой теме — «Включить тёмную тему».
 * `labelled` — кнопка с видимой подписью (лист «Разделы» на телефоне).
 */
export function ThemeToggle({ className = "", labelled = false }: { className?: string; labelled?: boolean }) {
  const { theme, toggle } = useTheme();
  const dark = theme === "dark";
  const label = dark ? "Включить светлую тему" : "Включить тёмную тему";
  const icon = dark ? <IconSun /> : <IconMoon />;
  if (labelled) {
    return (
      <button type="button" className={`ds-btn ds-btn-secondary ds-theme-toggle ${className}`.trim()} onClick={toggle}>
        {icon}
        {label}
      </button>
    );
  }
  return (
    <button
      type="button"
      className={`ds-icon-button ds-theme-toggle ${className}`.trim()}
      aria-label={label}
      title={label}
      onClick={toggle}
    >
      {icon}
    </button>
  );
}
