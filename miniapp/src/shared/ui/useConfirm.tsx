import { type ReactNode, useCallback, useState } from "react";
import { ConfirmDialog } from "./semantic";

/**
 * Подтверждение перед необратимым действием (F-18): удалить, отменить,
 * отозвать, отклонить, закрыть опрос, снять назначение. Кнопка открывает
 * диалог с последствием словами; действие выполняется только по
 * «Подтвердить…», Esc и «Отмена» закрывают без изменений.
 */
export type ConfirmRequest = {
  title: string;
  body?: ReactNode;
  confirmLabel: string;
  tone?: "primary" | "danger";
  run: () => unknown;
};

export function useConfirm() {
  const [request, setRequest] = useState<ConfirmRequest | null>(null);
  const [busy, setBusy] = useState(false);
  const ask = useCallback((next: ConfirmRequest) => setRequest(next), []);
  const dialog = request ? (
    <ConfirmDialog
      title={request.title}
      confirmLabel={request.confirmLabel}
      tone={request.tone ?? "danger"}
      busy={busy}
      busyLabel="Выполняем…"
      onCancel={() => setRequest(null)}
      onConfirm={async () => {
        setBusy(true);
        try {
          await request.run();
        } finally {
          setBusy(false);
          setRequest(null);
        }
      }}
    >
      {typeof request.body === "string" ? <p>{request.body}</p> : request.body}
    </ConfirmDialog>
  ) : null;
  return { ask, dialog };
}
