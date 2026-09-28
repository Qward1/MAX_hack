import { createContext, useContext, useEffect, useState } from "react";
import { RESOURCE_UPDATED_EVENT } from "../shared/api/useResource";

/** Вошедший сотрудник: «Выйти» живёт в шапке кабинета, а не отдельной полосой. */
export type EmployeeSessionInfo = { logout: () => void; busy: boolean };
export const EmployeeSessionContext = createContext<EmployeeSessionInfo | null>(null);

const TIME = new Intl.DateTimeFormat("ru", { hour: "2-digit", minute: "2-digit" });

/** Время последнего обновления данных экрана — тихой подписью (F1 §2.3). */
export function useLastUpdated(): number | null {
  const [at, setAt] = useState<number | null>(null);
  useEffect(() => {
    const updated = (event: Event) => setAt((event as CustomEvent<number>).detail);
    window.addEventListener(RESOURCE_UPDATED_EVENT, updated);
    return () => window.removeEventListener(RESOURCE_UPDATED_EVENT, updated);
  }, []);
  return at;
}

/**
 * Шапка кабинета (U-08): бренд и организация слева; время обновления,
 * «Обновить», имя и роль сотрудника и «Выйти» справа. На телефоне её место
 * занимает мобильная шапка с листом «Разделы».
 */
export function AdminHeader({
  home,
  org,
  user,
  role,
  onRefresh,
  navigate,
}: {
  home: string;
  org: string;
  user?: string;
  role?: string;
  onRefresh: () => void;
  navigate?: (href: string) => void;
}) {
  const session = useContext(EmployeeSessionContext);
  const updated = useLastUpdated();
  return (
    <header className="admin-topbar">
      <a
        className="admin-topbar-brand"
        href={home}
        onClick={(event) => {
          if (!navigate || event.ctrlKey || event.metaKey || event.shiftKey) return;
          event.preventDefault();
          navigate(home);
        }}
      >
        <strong>ДомСигнал</strong>
        <span className="admin-topbar-org">{org}</span>
      </a>
      {updated && <span className="admin-updated">Обновлено в {TIME.format(updated)}</span>}
      <button type="button" className="ds-btn ds-btn-tertiary" onClick={onRefresh}>
        <span aria-hidden="true">↻</span> Обновить
      </button>
      {user && (
        <span className="admin-topbar-user">
          <strong>{user}</strong>
          {role && <span>{role}</span>}
        </span>
      )}
      {session && (
        <button type="button" className="ds-btn ds-btn-secondary" disabled={session.busy} onClick={session.logout}>
          Выйти
        </button>
      )}
    </header>
  );
}
