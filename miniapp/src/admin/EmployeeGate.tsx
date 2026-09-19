import { useEffect, useState, type ReactNode, type FormEvent } from "react";
import { ticketClient as client } from "../shared/api/tickets";
import type { components } from "../shared/api/schema";

type State = components["schemas"]["EmployeeSession"];
type Enrollment = components["schemas"]["EmployeeEnrollment"];

export function EmployeeGate({ children }: { children: ReactNode }) {
  const [state, setState] = useState<State | null>(null);
  const [enrollment, setEnrollment] = useState<Enrollment | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [recovery, setRecovery] = useState(false);
  const [forbidden, setForbidden] = useState(false);
  const [fixture, setFixture] = useState(false);
  const [revision, setRevision] = useState(0);
  const apply = (next: State) => {
    setState(next);
    setEnrollment(null);
    if (next.stage !== "mfa_challenge") setRecovery(false);
    if (next.stage === "login") window.history.replaceState(null, "", "/admin/login");
    if (next.stage === "authenticated" && window.location.pathname === "/admin/login")
      window.history.replaceState(null, "", "/admin/");
  };
  useEffect(() => {
    let active = true;
    const restore = async () => {
      try {
        const caps = await client.capabilities();
        if (!active) return;
        if (caps.environment !== "production" && caps.features.test_auth &&
            new URLSearchParams(window.location.search).has("test_actor")) {
          setFixture(true); return;
        }
        const next = await client.employeeSession();
        if (active) apply(next);
      } catch { if (active) setError("Не удалось проверить вход. Обновите страницу."); }
    };
    void restore();
    const lost = (event: Event) => {
      setRevision(v => v + 1); // Unmount all private queries and pending mutations.
      if ((event as CustomEvent<number>).detail === 403) setForbidden(true);
      else { setState(null); void restore(); }
    };
    window.addEventListener("employee-access-lost", lost);
    const channel = typeof BroadcastChannel !== "undefined" ? new BroadcastChannel("employee-auth") : null;
    if (channel) channel.onmessage = () => { setState(null); setRevision(v => v + 1); void restore(); };
    return () => { active = false; channel?.close(); window.removeEventListener("employee-access-lost", lost); };
  }, []);
  const logout = async () => {
    setBusy(true); setError("");
    try {
      await client.employeeLogout();
      setState(null); setForbidden(false); setEnrollment(null); setRevision(v => v + 1);
      const channel = new BroadcastChannel("employee-auth"); channel.postMessage("logout"); channel.close();
      apply(await client.employeeSession());
    } catch { setError("Не удалось завершить сессию. Повторите выход."); }
    finally { setBusy(false); }
  };
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    setBusy(true); setError("");
    try {
      const step = state?.stage;
      const path = step === "login" ? "login" : step === "password_change" ? "password/change" :
        step === "mfa_enroll" ? "mfa/verify" : recovery ? "recovery" : "mfa/challenge";
      const payload = step === "login" ? { login_name: data.get("login"), password: data.get("password") } :
        step === "password_change" ? { password: data.get("password") } : { code: data.get("code") };
      const next = await client.employeeStep(path, payload);
      form.reset(); apply(next);
    } catch (e) { setError(e instanceof Error ? e.message : "Не удалось выполнить вход"); }
    finally { setBusy(false); }
  };
  if (fixture) return children;
  if (state?.stage === "authenticated" && !state.recovery_codes?.length) return (
    <div key={revision}>
      <div className="employee-session-bar"><span>Кабинет сотрудника</span>
        <button className="ticket-button secondary" disabled={busy} onClick={() => void logout()}>Выйти</button>
      </div>
      {error && <p role="alert">{error}</p>}
      {forbidden ? <main className="auth-card"><h1>Доступ отозван или ограничен</h1>
        <p>Рабочие данные скрыты. Уточните назначение у администратора УК.</p>
        <button className="ticket-button" onClick={() => window.location.reload()}>Проверить доступ</button>
      </main> : children}
    </div>
  );
  return <main className="auth-layout"><section className="auth-card">
    <a className="admin-brand" href="/admin/">ДомСигнал<span>Кабинет сотрудника</span></a>
    {!state ? <><h1>Проверяем вход…</h1>{error && <p role="alert">{error}</p>}</> :
      state.recovery_codes?.length ? <>
        <h1>Сохраните коды восстановления</h1>
        <p>Они показываются один раз. Каждый код заменяет второй фактор при входе с паролем.
          Сохраните их в менеджере паролей.</p>
        <ul className="recovery-codes">{state.recovery_codes.map(code => <li key={code}><code>{code}</code></li>)}</ul>
        <button className="ticket-button" onClick={() => setState({ ...state, recovery_codes: [] })}>Коды сохранены — открыть кабинет</button>
      </> : <form onSubmit={submit} className="ticket-form" key={`${state.stage}:${recovery}`}>
        <h1>{state.stage === "login" ? "Вход сотрудника" : state.stage === "password_change" ? "Создайте свой пароль" :
          state.stage === "mfa_enroll" ? "Подключите аутентификатор" : "Подтвердите вход"}</h1>
        {state.stage === "login" && <label>Логин<input name="login" autoComplete="username" autoCapitalize="none" required maxLength={100} /></label>}
        {["login", "password_change"].includes(state.stage) && <label>{state.stage === "login" ? "Пароль" : "Новый пароль"}
          <input name="password" type="password" autoComplete={state.stage === "login" ? "current-password" : "new-password"}
            minLength={state.stage === "password_change" ? 12 : 1} maxLength={1024} required /></label>}
        {state.stage === "password_change" && <p>Минимум 12 символов. Используйте длинный уникальный пароль.</p>}
        {state.stage === "mfa_enroll" && <>
          <p>Добавьте аккаунт в Google Authenticator, Microsoft Authenticator или другое приложение TOTP.</p>
          {!enrollment ? <button type="button" className="ticket-button secondary" disabled={busy} onClick={async () => {
            setBusy(true); setError("");
            try { setEnrollment(await client.employeeEnroll()); } catch { setError("Не удалось подготовить MFA"); }
            finally { setBusy(false); }
          }}>Показать QR-код</button> : <>
            <img className="auth-qr" alt="QR-код для подключения аутентификатора" src={`data:image/svg+xml,${encodeURIComponent(enrollment.qr_svg)}`} />
            <p>Ручной ключ: <code className="manual-secret">{enrollment.secret}</code></p>
          </>}
        </>}
        {["mfa_enroll", "mfa_challenge"].includes(state.stage) && <label>{recovery ? "Код восстановления" : "Код из приложения"}
          <input name="code" autoComplete="one-time-code" inputMode={recovery ? "text" : "numeric"}
            pattern={recovery ? undefined : "[0-9]{6}"} maxLength={recovery ? 64 : 6} required /></label>}
        {error && <p role="alert">{error}</p>}
        <button className="ticket-button" type="submit" disabled={busy || (state.stage === "mfa_enroll" && !enrollment)}>
          {busy ? "Проверяем…" : state.stage === "login" ? "Войти" : "Продолжить"}</button>
        {state.stage === "mfa_challenge" && <button type="button" className="ticket-button secondary" onClick={() => setRecovery(!recovery)}>
          {recovery ? "Ввести код аутентификатора" : "Использовать код восстановления"}</button>}
        {state.stage !== "login" && <button type="button" className="ticket-button secondary" disabled={busy} onClick={() => void logout()}>Начать вход заново</button>}
      </form>}
  </section></main>;
}
