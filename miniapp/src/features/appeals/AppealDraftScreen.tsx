import { useCallback, useEffect, useId, useRef, useState } from "react";
import {
  type AppealDraftView,
  type DomSignalApi,
  problemStatus,
  retryable,
} from "../../shared/api/client";
import { maxBridge, safeUrl } from "../../shared/max/bridge";
import { Button, LinkButton } from "../../shared/ui/Button";
import { formatDay, formatWhen } from "../../shared/ui/format";
import { ConfirmDialog, InfoRow, Notice, SourceChip } from "../../shared/ui/semantic";
import { SourceLink } from "../../shared/ui/SourceLink";
import { actionLabels, knownActions } from "../incidents/presentation";

/** Порядок закреплён продуктом: сначала текст в буфер, потом сервис, потом отметка. */
const ACTION_ORDER = ["copy_draft", "open_official_channel", "mark_filed"] as const;

const AI_NOTE = "Абзац описания подготовлен с помощью ИИ — проверьте перед отправкой.";
const COPY_FALLBACK = "Выделите и скопируйте текст вручную.";
const COPY_DONE = "Текст скопирован.";
const FILED_NOTE =
  "Вы отметили, что отправили обращение. ДомСигнал не подтверждает регистрацию во внешней системе.";
const CONFLICT_NOTE = "Черновик изменился. Ваш текст сохранён на экране.";
const UNVERIFIED_CHANNEL = "Официальный сервис ещё не проверен в справочнике.";
export const SELF_FILING_NOTE = "ДомСигнал не отправляет обращения за вас — вы отправляете его сами.";
/** Буфер обмена webview может не ответить вовсе: ждём не дольше. */
const CLIPBOARD_TIMEOUT_MS = 1500;

async function writeClipboard(value: string): Promise<boolean> {
  if (!navigator.clipboard?.writeText) return false;
  let timer: number | undefined;
  try {
    await Promise.race([
      navigator.clipboard.writeText(value),
      new Promise((_resolve, reject) => {
        timer = window.setTimeout(() => reject(new Error("clipboard timeout")), CLIPBOARD_TIMEOUT_MS);
      }),
    ]);
    return true;
  } catch {
    return false;
  } finally {
    window.clearTimeout(timer);
  }
}

function saveError(error: unknown): string {
  const status = problemStatus(error);
  if (status === 401) return "Не удалось сохранить: сессия MAX истекла. Текст остался на экране — скопируйте его, затем откройте мини-приложение снова.";
  if (status === 403 || status === 404) return "Не удалось сохранить: черновик больше недоступен. Текст остался на экране — скопируйте его.";
  if (retryable(error)) return "Не удалось сохранить. Проверьте интернет и попробуйте ещё раз. Текст остался на экране.";
  return "Не удалось сохранить. Обновите страницу. Текст остался на экране — скопируйте его перед обновлением.";
}

export function AppealDraftScreen({
  draft,
  client,
  onLoaded,
  busy = false,
}: {
  draft: AppealDraftView;
  client: DomSignalApi;
  onLoaded: (next: AppealDraftView) => void;
  busy?: boolean;
}) {
  const id = useId();
  const area = useRef<HTMLTextAreaElement | null>(null);
  const [text, setText] = useState(draft.text);
  const [reference, setReference] = useState("");
  const [copy, setCopy] = useState<string | null>(null);
  const [conflict, setConflict] = useState<AppealDraftView | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [saving, setSaving] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const pending = useRef(false);
  const filed = draft.filed_at !== null && draft.filed_at !== undefined;
  const dirty = !filed && text !== draft.text;
  const actions = knownActions(draft.allowed_actions);
  const descriptor = (code: string) => actions.find((item) => item.code === code);
  const channel = draft.channel;
  const url = safeUrl(channel?.url);
  const verified = formatDay(channel?.verified_at);
  const needsCheck = Boolean(channel && (channel.stale || channel.verification_status !== "verified"));

  // Несохранённая правка — MAX предупредит при закрытии мини-приложения.
  useEffect(() => {
    maxBridge.closingConfirmation(dirty);
    return () => maxBridge.closingConfirmation(false);
  }, [dirty]);

  const guard = useCallback(
    async (run: () => Promise<AppealDraftView>, done?: () => void) => {
      if (pending.current) return;
      pending.current = true;
      setSaving(true);
      setError(null);
      try {
        onLoaded(await run());
        setConflict(null);
        done?.();
      } catch (failure) {
        setError(failure);
        maxBridge.haptic("error");
        if (problemStatus(failure) === 409) {
          // Устаревшая версия не затирает ввод: житель видит обе и решает сам.
          try {
            setConflict(await client.appealDraft(draft.id));
          } catch {
            /* Свежая версия придёт при следующем обновлении экрана. */
          }
        }
      } finally {
        pending.current = false;
        setSaving(false);
      }
    },
    [client, draft.id, onLoaded],
  );

  async function copyText() {
    setCopy(null);
    if (await writeClipboard(text)) {
      setCopy(COPY_DONE);
      return;
    }
    // Отказ или молчание буфера обмена — обычное состояние, а не ошибка:
    // выделяем текст и пробуем старый способ копирования.
    area.current?.focus();
    area.current?.select();
    let copied = false;
    try {
      copied = document.execCommand("copy");
    } catch {
      copied = false;
    }
    setCopy(copied ? COPY_DONE : COPY_FALLBACK);
  }

  const saved = formatWhen(draft.updated_at);
  return (
    <>
      <section className="ds-section draft-recipient" aria-labelledby={`${id}-to`}>
        <h2 id={`${id}-to`}>Куда отправить</h2>
        <dl className="ds-kv">
          <InfoRow label="Адресат">{draft.organization_name ?? "Не назван в справочнике"}</InfoRow>
          <InfoRow label="Официальный сервис">{channel?.label ?? "Проверенного сервиса пока нет"}</InfoRow>
          {verified && <InfoRow label="Проверено">{verified}</InfoRow>}
        </dl>
        {needsCheck && (
          <Notice tone="warning" role="note">
            <p>Сведения об официальном сервисе требуют сверки.</p>
          </Notice>
        )}
        {!channel && <p className="ds-subtle">{UNVERIFIED_CHANNEL}</p>}
        {(channel?.facts ?? []).length > 0 && (
          <details className="ds-disclosure draft-channel-facts">
            <summary>Что известно об официальном сервисе</summary>
            <ul className="ds-bullets ds-disclosure-body">
              {(channel?.facts ?? []).map((fact) => (
                <li key={fact.text}>
                  <span className="ds-prose">{fact.text}</span>
                  <SourceLink url={fact.source_url} title={fact.source_title} />
                </li>
              ))}
            </ul>
          </details>
        )}
        <SourceChip source={draft.provenance} />
      </section>

      <section className="ds-section draft-editor" aria-labelledby={`${id}-text-title`}>
        <h2 id={`${id}-text-title`}>Текст обращения</h2>
        {draft.ai_assisted && (
          <Notice tone="warning" role="note">
            <p>{AI_NOTE}</p>
          </Notice>
        )}
        <div className="ds-field">
          <label htmlFor={`${id}-text`}>Обращение</label>
          <p id={`${id}-hint`} className="ds-hint">
            В тексте только то, что нужно вставить в форму официального сервиса. Правку сохраните перед копированием.
          </p>
          <textarea
            id={`${id}-text`}
            ref={area}
            value={text}
            readOnly={filed || busy}
            aria-describedby={`${id}-hint ${id}-saved`}
            rows={12}
            onChange={(event) => {
              setText(event.target.value);
              setCopy(null);
            }}
          />
        </div>
        <p id={`${id}-saved`} className="ds-meta" role="status">
          {dirty ? "Есть несохранённая правка." : `Сохранено${saved ? ` ${saved}` : ""}.`}
        </p>
        {!filed && (
          <Button
            disabled={busy || text.trim().length === 0 || !dirty}
            loading={saving}
            loadingLabel="Сохраняем…"
            onClick={() => void guard(() => client.saveAppealDraft(draft.id, { text, version: draft.version }))}
          >
            Сохранить правку
          </Button>
        )}
        {conflict && (
          <Notice tone="warning" role="alert" className="draft-conflict">
            <p className="ds-notice-title">{CONFLICT_NOTE}</p>
            <p>Версия на сервере:</p>
            <p className="ds-prose">{conflict.text}</p>
            <Button
              onClick={() => {
                setText(conflict.text);
                onLoaded(conflict);
                setConflict(null);
              }}
            >
              Взять версию с сервера
            </Button>
            <p className="ds-subtle">Или скопируйте свой текст и сохраните его ещё раз.</p>
          </Notice>
        )}
        {Boolean(error) && problemStatus(error) !== 409 && !confirming && (
          <Notice tone="danger" role="alert">
            <p>{saveError(error)}</p>
          </Notice>
        )}
      </section>

      <section className="ds-section draft-actions" aria-labelledby={`${id}-next`}>
        <h2 id={`${id}-next`}>Что сделать</h2>
        <p className="ds-subtle">{SELF_FILING_NOTE}</p>
        <div className="ds-stack">
          {ACTION_ORDER.map((code) => {
            const action = descriptor(code);
            if (!action) return null;
            if (code === "copy_draft")
              return (
                <div key={code} className="ds-action ds-action-stretched">
                  <Button
                    variant={filed ? "secondary" : "primary"}
                    stretched
                    disabled={!action.enabled}
                    reason={action.enabled ? null : action.reason}
                    onClick={() => void copyText()}
                  >
                    {actionLabels.copy_draft}
                  </Button>
                  {copy && (
                    <p role="status" className="ds-meta">
                      {copy}
                    </p>
                  )}
                </div>
              );
            if (code === "open_official_channel")
              return (
                <div key={code} className="ds-action ds-action-stretched">
                  {action.enabled && url ? (
                    <LinkButton
                      stretched
                      href={url}
                      target="_blank"
                      rel="noopener noreferrer"
                      onClick={(event) => {
                        if (maxBridge.openLink(url)) event.preventDefault();
                      }}
                    >
                      {actionLabels.open_official_channel}
                    </LinkButton>
                  ) : (
                    <Button stretched disabled reason={action.reason ?? "Ссылки на официальный сервис пока нет."}>
                      {actionLabels.open_official_channel}
                    </Button>
                  )}
                  {action.enabled && url && action.reason && <p className="ds-reason">{action.reason}</p>}
                  {!url && channel?.entry_hint && <p className="ds-meta">Вход: {channel.entry_hint}</p>}
                </div>
              );
            return (
              <Button
                key={code}
                stretched
                disabled={busy || saving || !action.enabled}
                reason={action.enabled ? null : action.reason}
                onClick={() => {
                  setError(null);
                  setConfirming(true);
                }}
              >
                {actionLabels.mark_filed}
              </Button>
            );
          })}
        </div>
        {filed && (
          <Notice tone="neutral" role="status">
            <p>
              {FILED_NOTE}
              {draft.filed_reference ? ` Ваш номер: ${draft.filed_reference}.` : ""}
            </p>
          </Notice>
        )}
      </section>

      {confirming && (
        <ConfirmDialog
          title="Отметить обращение как отправленное?"
          confirmLabel="Да, я отправил(а)"
          busy={saving}
          busyLabel="Сохраняем отметку…"
          onCancel={() => setConfirming(false)}
          onConfirm={() =>
            void guard(
              () => client.markAppealFiled(draft.id, reference.trim() || null),
              () => {
                setConfirming(false);
                maxBridge.haptic("success");
              },
            )
          }
        >
          <p>
            Отметьте, только если вы уже отправили текст в официальном сервисе. ДомСигнал не проверяет, зарегистрировано
            ли обращение там. Отметку потом не изменить.
          </p>
          <div className="ds-field">
            <label htmlFor={`${id}-reference`}>Номер обращения, если сервис его выдал</label>
            <input
              id={`${id}-reference`}
              value={reference}
              maxLength={200}
              autoComplete="off"
              onChange={(event) => setReference(event.target.value)}
            />
          </div>
          {Boolean(error) && (
            <Notice tone="danger" role="alert">
              <p>{problemStatus(error) === 409 ? "Черновик изменился. Закройте окно и проверьте текст." : saveError(error).replace("сохранить", "сохранить отметку")}</p>
            </Notice>
          )}
        </ConfirmDialog>
      )}
    </>
  );
}
