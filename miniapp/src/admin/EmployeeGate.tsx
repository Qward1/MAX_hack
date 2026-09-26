import { useEffect, useRef, useState, type ReactNode, type FormEvent } from "react";
import { ApiProblem } from "../shared/api/client";
import { ticketClient as client } from "../shared/api/tickets";
import type { components } from "../shared/api/schema";

type State = components["schemas"]["EmployeeSession"];
type Enrollment = components["schemas"]["EmployeeEnrollment"];

type Preview = { title: string; detail: string };

/**
 * Что случилось при входе и что делать — словами для человека. Неверный
 * логин и пароль не различаем (это не подсказка взломщику), код — отдельно.
 */
export function loginError(error: unknown, step: string | undefined, recovery: boolean): string {
  if (!(error instanceof ApiProblem)) return "Не удалось связаться с сервером. Проверьте интернет и повторите.";
  const { status, detail } = error.problem;
  if (status === 429) return "Слишком много попыток. Подождите несколько минут и повторите вход.";
  if (status === 401 && step === "login")
    return "Логин или пароль не подошли. Проверьте раскладку клавиатуры и Caps Lock.";
  if (status === 401 && (step === "mfa_challenge" || step === "mfa_enroll"))
    return recovery
      ? "Код восстановления не подошёл. Каждый код действует один раз."
      : "Код не подошёл. Введите текущий код из приложения — он меняется каждые 30 секунд.";
  if (status === 422) return "Проверьте заполнение полей.";
  // Правило сервиса уже сказано по-русски («Пароль: минимум 12 символов…») — показать его.
  if (/[а-яё]/i.test(detail ?? "")) return detail;
  return "Не удалось выполнить вход. Обновите страницу и повторите.";
}

/**
 * Вход сотрудника (пароль + TOTP, A-10). Режимы D2: единый вход `/login`,
 * регистрация по открытой ссылке УК (`joinCode`) и новый пароль по
 * одноразовой ссылке сброса (`resetToken`).
 */
export function EmployeeGate({ children, invitationToken, platform = false, unified = false, joinCode, resetToken }: {
  children: ReactNode; invitationToken?: string; platform?: boolean; unified?: boolean; joinCode?: string; resetToken?: string;
}) {
  const [signup, setSignup] = useState(Boolean(invitationToken));
  const [preview, setPreview] = useState<Preview | null>(null);
  const [linkError, setLinkError] = useState("");
  const linkMode = joinCode ? "join" : resetToken ? "reset" : null;
  const [state, setState] = useState<State | null>(null);
  const [enrollment, setEnrollment] = useState<Enrollment | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [recovery, setRecovery] = useState(false);
  const [forbidden, setForbidden] = useState(false);
  const errorRef = useRef<HTMLParagraphElement>(null);
  // Ошибка входа названа текстом у формы; фокус — на неё, введённое не стирается.
  useEffect(() => {
    if (error) errorRef.current?.focus();
  }, [error]);
  // Вход сотрудника УК на странице платформы (живая проверка D3): не тупик
  // «доступ отозван», а переход в свой кабинет — по ролям с сервера.
  const [companyCabinet, setCompanyCabinet] = useState(false);
  const [fixture, setFixture] = useState(false);
  const [revision, setRevision] = useState(0);
  const apply = (next: State) => {
    setState(next);
    setEnrollment(null);
    if (next.stage !== "mfa_challenge") setRecovery(false);
    if (next.stage === "login" && linkMode && !preview) void loadPreview();
    if (next.stage === "login" && !invitationToken && !linkMode && !platform && !unified && window.location.pathname === "/admin/") window.history.replaceState(null, "", "/admin/login");
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
      } catch { if (active) setError("Не удалось проверить вход. Проверьте интернет и обновите страницу."); }
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
  useEffect(() => {
    if (!forbidden || !platform) return;
    let active = true;
    client.request<components["schemas"]["EmployeeDestinations"]>("/api/v1/auth/employee/destinations")
      .then(result => { if (active) setCompanyCabinet(!result.platform && result.companies.length > 0); })
      .catch(() => {});
    return () => { active = false; };
  }, [forbidden, platform]);
  async function loadPreview() {
    try {
      if (joinCode) {
        const result = await client.request<components["schemas"]["JoinPreview"]>("/api/v1/auth/employee/join/preview",
          { method: "POST", body: JSON.stringify({ code: joinCode }) });
        setPreview({ title: `Регистрация в «${result.company_name}»`,
          detail: "Вы станете оператором этой управляющей компании и увидите заявки её домов. Понадобится приложение-аутентификатор (TOTP)." });
      } else if (resetToken) {
        const result = await client.request<components["schemas"]["CredentialResetPreview"]>("/api/v1/auth/employee/credential-reset/preview",
          { method: "POST", body: JSON.stringify({ token: resetToken }) });
        setPreview({ title: "Новый пароль", detail: `Логин: ${result.login_name}. ${result.kind === "password_mfa"
          ? "После пароля заново подключите приложение-аутентификатор."
          : "После пароля подтвердите вход кодом из прежнего приложения-аутентификатора."}` });
      }
    } catch (e) { setLinkError(e instanceof Error ? e.message : "Ссылка недействительна или устарела."); }
  }
  const logout = async () => {
    setBusy(true); setError("");
    try {
      await client.employeeLogout();
      if (!invitationToken) window.history.replaceState(null, "", platform ? "/platform-admin/" : "/admin/login");
      setState(null); setForbidden(false); setEnrollment(null); setRevision(v => v + 1);
      const channel = new BroadcastChannel("employee-auth"); channel.postMessage("logout"); channel.close();
      apply(await client.employeeSession());
    } catch { setError("Не удалось выйти. Проверьте интернет и повторите."); }
    finally { setBusy(false); }
  };
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    setBusy(true); setError("");
    try {
      const step = state?.stage;
      const path = step === "login" ? (linkMode === "join" ? "join/register" : linkMode === "reset" ? "credential-reset/complete"
        : signup && invitationToken ? "invitations/register" : "login") : step === "password_change" ? "password/change" :
        step === "mfa_enroll" ? "mfa/verify" : recovery ? "recovery" : "mfa/challenge";
      const payload = step === "login" ? (linkMode === "reset" ? { token: resetToken, password: data.get("password") }
        : linkMode === "join" ? { code: joinCode, display_name: data.get("display_name"), login_name: data.get("login"), password: data.get("password") }
        : { login_name: data.get("login"), password: data.get("password"), ...(signup && invitationToken ? { token: invitationToken, display_name: data.get("display_name") } : {}) }) :
        step === "password_change" ? { password: data.get("password") } : { code: data.get("code") };
      const next = await client.employeeStep(path, payload);
      form.reset(); apply(next);
    } catch (e) {
      setError(loginError(e, state?.stage, recovery));
    }
    finally { setBusy(false); }
  };
  if (fixture) return children;
  if (state?.stage === "authenticated" && !state.recovery_codes?.length) return (
    <div key={revision}>
      <div className="employee-session-bar"><span>ДомСигнал · кабинет сотрудника</span>
        <button className="ds-btn ds-btn-secondary" disabled={busy} onClick={() => void logout()}>Выйти</button>
      </div>
      {error && <p role="alert" className="ds-notice ds-tone-danger">{error}</p>}
      {forbidden ? <main className="auth-layout"><section className="auth-card">{companyCabinet ? <>
        <h1>Это вход для управления платформой</h1>
        <p>Вы вошли как сотрудник управляющей компании — ваш кабинет отдельный.</p>
        <a className="ticket-button" href="/admin/">Открыть кабинет управляющей компании</a>
      </> : <><h1>Доступ отозван или ограничен</h1>
        <p>Рабочие данные скрыты. Доступ к домам выдаёт администратор вашей управляющей компании — уточните назначение у него.</p>
        <button className="ds-btn ds-btn-primary" onClick={() => window.location.reload()}>Проверить доступ</button>
      </>}</section></main> : children}
    </div>
  );
  return <main className="auth-layout"><section className="auth-card">
    <a className="admin-brand" href="/admin/">ДомСигнал<span>Кабинет сотрудника</span></a>
    {!state ? <><h1>Проверяем вход…</h1>{error && <p role="alert" className="ds-notice ds-tone-danger">{error}</p>}</> :
      state.recovery_codes?.length ? <>
        <h1>Сохраните коды восстановления</h1>
        <p>Они показываются один раз. Каждый код заменяет второй фактор при входе с паролем.
          Сохраните их в менеджере паролей.</p>
        <ul className="recovery-codes">{state.recovery_codes.map(code => <li key={code}><code>{code}</code></li>)}</ul>
        <button className="ticket-button" onClick={() => { if ((invitationToken && signup) || linkMode) window.location.assign("/admin/"); else setState({ ...state, recovery_codes: [] }); }}>Коды сохранены — открыть кабинет</button>
      </> : <form onSubmit={submit} className="ticket-form" key={`${state.stage}:${recovery}`}>
        <h1>{state.stage === "login" ? (linkMode ? (preview?.title ?? (linkError ? "Ссылка недействительна" : "Проверяем ссылку…"))
          : signup && invitationToken ? "Принять приглашение" : platform ? "Вход в управление платформой" : unified ? "Вход в кабинет" : "Вход сотрудника") : state.stage === "password_change" ? "Создайте свой пароль" :
          state.stage === "mfa_enroll" ? "Подключите аутентификатор" : "Подтвердите вход"}</h1>
        {state.stage === "login" && unified && <p className="ds-subtle">Для сотрудников управляющих компаний и платформы. После пароля понадобится код из приложения-аутентификатора.</p>}
        {state.stage === "login" && linkMode && preview && <p>{preview.detail}</p>}
        {state.stage === "login" && linkMode && linkError && <><p role="alert">{linkError}</p>
          <p>{linkMode === "join" ? "Попросите ссылку у платформы или администратора УК." : "Попросите администратора УК выдать новую ссылку."}</p>
          <a className="ticket-button secondary" href="/login">Перейти ко входу</a></>}
        {state.stage === "login" && invitationToken && <><p>Новый сотрудник принимает приглашение после настройки пароля и MFA.</p><button type="button" className="ticket-button secondary" onClick={() => setSignup(!signup)}>{signup ? "У меня уже есть аккаунт" : "Создать аккаунт сотрудника"}</button>{signup && <label>Ваше имя<input name="display_name" required minLength={2} maxLength={200} /></label>}</>}
        {state.stage === "login" && linkMode === "join" && preview && <label>Ваше имя<input name="display_name" required minLength={2} maxLength={200} autoComplete="name" /></label>}
        {state.stage === "login" && linkMode !== "reset" && (!linkMode || preview) && <label>Логин<input name="login" autoComplete="username" autoCapitalize="none" spellCheck={false} required minLength={linkMode ? 3 : 1} maxLength={100}
          aria-invalid={Boolean(error) || undefined} aria-describedby={error ? "login-error" : undefined} /></label>}
        {(["login", "password_change"].includes(state.stage) && (!linkMode || preview || state.stage !== "login")) && <label>{state.stage === "login" && !linkMode ? "Пароль" : "Новый пароль"}
          <input name="password" type="password" autoComplete={state.stage === "login" && !signup && !linkMode ? "current-password" : "new-password"}
            minLength={state.stage === "password_change" || signup || linkMode ? 12 : 1} maxLength={1024} required
            aria-invalid={Boolean(error) || undefined}
            aria-describedby={[state.stage !== "login" || linkMode ? "password-hint" : "", error ? "login-error" : ""].filter(Boolean).join(" ") || undefined} /></label>}
        {(state.stage === "password_change" || (state.stage === "login" && linkMode && preview)) && <p id="password-hint" className="ds-hint">Минимум 12 символов. Удобно взять фразу из нескольких слов.</p>}
        {state.stage === "mfa_enroll" && <>
          <p>Откройте приложение-аутентификатор (Google Authenticator, Яндекс Ключ, Microsoft Authenticator или другое) и добавьте аккаунт по QR-коду.</p>
          {!enrollment ? <button type="button" className="ticket-button secondary" disabled={busy} onClick={async () => {
            setBusy(true); setError("");
            try { setEnrollment(await client.employeeEnroll()); } catch { setError("Не удалось подготовить MFA"); }
            finally { setBusy(false); }
          }}>Показать QR-код</button> : <>
            <img className="auth-qr" alt="QR-код для подключения аутентификатора" src={`data:image/svg+xml,${encodeURIComponent(enrollment.qr_svg)}`} />
            <p>Если камера недоступна, введите ключ вручную: <code className="manual-secret">{enrollment.secret}</code></p>
          </>}
        </>}
        {["mfa_enroll", "mfa_challenge"].includes(state.stage) && <label>{recovery ? "Код восстановления" : "Код из приложения"}
          <input name="code" autoComplete="one-time-code" inputMode={recovery ? "text" : "numeric"}
            pattern={recovery ? undefined : "[0-9]{6}"} maxLength={recovery ? 64 : 6} required
            aria-invalid={Boolean(error) || undefined} aria-describedby={error ? "code-hint login-error" : "code-hint"} /></label>}
        {["mfa_enroll", "mfa_challenge"].includes(state.stage) && <p id="code-hint" className="ds-hint">{recovery
          ? "Один из кодов, которые вы сохранили при подключении аутентификатора."
          : "6 цифр из приложения-аутентификатора."}</p>}
        {error && <p id="login-error" ref={errorRef} tabIndex={-1} role="alert" className="ds-error">{error}</p>}
        {!(state.stage === "login" && linkMode && !preview) && <button className="ticket-button" type="submit" disabled={busy || (state.stage === "mfa_enroll" && !enrollment)}>
          {busy ? "Проверяем…" : state.stage === "login" ? (linkMode === "join" ? "Зарегистрироваться и настроить MFA" : linkMode === "reset" ? "Сохранить пароль"
            : signup && invitationToken ? "Создать аккаунт и настроить MFA" : "Войти") : "Продолжить"}</button>}
        {state.stage === "mfa_challenge" && <button type="button" className="ticket-button secondary" onClick={() => setRecovery(!recovery)}>
          {recovery ? "Ввести код аутентификатора" : "Использовать код восстановления"}</button>}
        {state.stage !== "login" && <button type="button" className="ticket-button secondary" disabled={busy} onClick={() => void logout()}>Начать вход заново</button>}
      </form>}
  </section></main>;
}
