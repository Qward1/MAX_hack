import { useState } from "react";
import { adminClient, Feedback, Title, useAction, useRead, type Schema } from "./administration";

/** Выйти и открыть ту же ссылку: вход сменится формой нового аккаунта сотрудника. */
async function separateAccount() {
  try { await adminClient.employeeLogout(); } catch { /* сессия уже завершена */ }
  if (typeof BroadcastChannel !== "undefined") {
    const channel = new BroadcastChannel("employee-auth"); channel.postMessage("logout"); channel.close();
  }
  window.location.reload();
}

export function InvitationAccept({ token }: { token: string }) {
  const [invite, setInvite] = useState<Schema["InvitationView"] | null>(null);
  const [accepted, setAccepted] = useState(false);
  const action = useAction();
  const who = useRead<Schema["EmployeeDestinations"]>("/api/v1/auth/employee/destinations");
  // Роли платформы и УК разделены (сервер отвечает platform_account_invitation).
  const platform = who.data?.platform === true || action.code === "platform_account_invitation";
  const separate = <button className="ticket-button secondary" disabled={action.busy} onClick={() => void separateAccount()}>
    {platform ? "Выйти и создать аккаунт сотрудника" : "Создать отдельный аккаунт"}</button>;
  return <main className="auth-layout"><section className="auth-card">
    <Title>{accepted ? "Приглашение принято" : "Присоединиться к управляющей компании"}</Title>
    {platform && !accepted ? <>
      <p>Вы вошли как администратор платформы. Приглашение УК принимает отдельный аккаунт сотрудника — со своим логином, паролем и приложением-аутентификатором.</p>
      <p className="muted">Вход администратора платформы в этом браузере завершится. Можно также открыть ссылку в другом браузере или приватном окне.</p>
      <div className="button-row">{separate}</div></> : <>
    <Feedback error={action.error} />
    {!invite ? <><p>Вы уже вошли в кабинет сотрудника. Приглашение можно закрепить за этим аккаунтом или создать для него отдельный аккаунт.</p>
      <div className="button-row"><button className="ticket-button" disabled={action.busy || who.loading} onClick={async () => {
        const result = await action.run<Schema["InvitationView"]>("/api/v1/auth/employee/invitations/claim", { token });
        if (result) setInvite(result);
      }}>Принять этим аккаунтом</button>{separate}</div></> : !accepted ? <>
        <p>Роль: {invite.organization_role === "company_admin" ? "Администратор УК" : "Оператор"}.</p>
        <p>Подтвердите вступление в организацию.</p>
        <button className="ticket-button" disabled={action.busy} onClick={async () => {
          if (await action.run("/api/v1/auth/employee/invitations/accept", { token })) setAccepted(true);
        }}>Принять приглашение</button></> : <p>Ваш доступ будет определён назначениями в организации.</p>}
    <p><a href="/admin/">Открыть кабинет</a></p></>}
  </section></main>;
}
