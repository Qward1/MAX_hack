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
