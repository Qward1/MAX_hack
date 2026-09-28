import type { ReactNode } from "react";

/**
 * Несколько контурных значков для навигации. Значок всегда рядом с подписью
 * и скрыт от экранного диктора: смысл несёт текст.
 */
function Icon({ children }: { children: ReactNode }) {
  return (
    <svg
      className="ds-icon"
      viewBox="0 0 24 24"
      width="22"
      height="22"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {children}
    </svg>
  );
}

export const IconProblems = () => (
  <Icon>
    <path d="M5 5h14M5 12h14M5 19h9" />
  </Icon>
);
export const IconRequests = () => (
  <Icon>
    <path d="M4 5h16v11H9l-5 4z" />
    <path d="M8 9.5h8M8 12.5h5" />
  </Icon>
);
export const IconNews = () => (
  <Icon>
    <path d="M4 10v4h3l6 4V6L7 10z" />
    <path d="M16.5 9a4 4 0 0 1 0 6" />
  </Icon>
);
export const IconHouse = () => (
  <Icon>
    <path d="M4 11 12 4l8 7" />
    <path d="M6 9.5V20h12V9.5" />
    <path d="M10 20v-5h4v5" />
  </Icon>
);
export const IconMenu = () => (
  <Icon>
    <path d="M4 7h16M4 12h16M4 17h16" />
  </Icon>
);
export const IconClose = () => (
  <Icon>
    <path d="M6 6l12 12M18 6 6 18" />
  </Icon>
);
/** Выбранный вариант списка. */
export const IconCheck = () => (
  <Icon>
    <path d="M5 12.5 10 17.5 19 7" />
  </Icon>
);
/** Переход на внешний сайт: открывается отдельно, вне приложения. */
export const IconExternal = () => (
  <Icon>
    <path d="M9 5H5v14h14v-4" />
    <path d="M13 5h6v6M19 5l-8 8" />
  </Icon>
);
export const IconPeople = () => (
  <Icon>
    <circle cx="9" cy="8" r="3.2" />
    <path d="M3.5 19c.6-3.2 2.9-5 5.5-5s4.9 1.8 5.5 5" />
    <circle cx="17" cy="9" r="2.4" />
    <path d="M16 13.8c2.2.2 3.9 1.8 4.5 4.2" />
  </Icon>
);
export const IconInfo = () => (
  <Icon>
    <circle cx="12" cy="12" r="8.5" />
    <path d="M12 11v5.5M12 7.8v.2" />
  </Icon>
);
export const IconChat = () => (
  <Icon>
    <path d="M4 6.5A2.5 2.5 0 0 1 6.5 4h11A2.5 2.5 0 0 1 20 6.5v7a2.5 2.5 0 0 1-2.5 2.5H10l-4.5 4v-4A2.5 2.5 0 0 1 4 13.5z" />
  </Icon>
);
export const IconClock = () => (
  <Icon>
    <circle cx="12" cy="12" r="8.5" />
    <path d="M12 7.5V12l3 2" />
  </Icon>
);
