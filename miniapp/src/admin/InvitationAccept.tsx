import { useState } from "react";
import { Feedback, Title, useAction, type Schema } from "./administration";

export function InvitationAccept({ token }: { token: string }) {
  const [invite, setInvite] = useState<Schema["InvitationView"] | null>(null);
  const [accepted, setAccepted] = useState(false);
  const action = useAction();
  return <main className="auth-layout"><section className="auth-card">
    <Title>{accepted ? "Приглашение принято" : "Присоединиться к управляющей компании"}</Title>
    <Feedback error={action.error} />
    {!invite ? <><p>Приглашение будет закреплено за аккаунтом, в который вы вошли.</p>
      <button className="ticket-button" disabled={action.busy} onClick={async () => {
        const result = await action.run<Schema["InvitationView"]>("/api/v1/auth/employee/invitations/claim", { token });
        if (result) setInvite(result);
      }}>Открыть приглашение</button></> : !accepted ? <>
        <p>Роль: {invite.organization_role === "company_admin" ? "Администратор УК" : "Оператор"}.</p>
        <p>Подтвердите вступление в организацию.</p>
        <button className="ticket-button" disabled={action.busy} onClick={async () => {
          if (await action.run("/api/v1/auth/employee/invitations/accept", { token })) setAccepted(true);
        }}>Принять приглашение</button></> : <p>Ваш доступ будет определён назначениями в организации.</p>}
    <p><a href="/admin/">Открыть кабинет</a></p>
  </section></main>;
}
