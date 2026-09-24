import { Button, Flex, Panel, Textarea, Typography } from "@maxhub/max-ui";
import { useCallback, useId, useRef, useState } from "react";
import {
  ApiProblem,
  type AppealDraftView,
  type DomSignalApi,
  problemStatus,
  retryable,
} from "../../shared/api/client";
import { maxBridge, safeUrl } from "../../shared/max/bridge";
import { SourceChip } from "../../shared/ui/semantic";
import { SourceLink } from "../../shared/ui/SourceLink";
import { actionLabels, formatDate, formatDay, knownActions } from "../incidents/presentation";

/** Порядок закреплён продуктом: сначала текст в буфер, потом сервис, потом отметка. */
const ACTION_ORDER = ["copy_draft", "open_official_channel", "mark_filed"] as const;

const AI_NOTE = "Абзац описания подготовлен с помощью ИИ — проверьте перед отправкой.";
const COPY_FALLBACK = "Выделите и скопируйте текст вручную.";
const COPY_DONE = "Текст скопирован.";
const FILED_NOTE =
  "Вы отметили, что отправили обращение. ДомСигнал не подтверждает регистрацию во внешней системе.";
const CONFLICT_NOTE = "Черновик изменился. Ваш текст сохранён на экране.";
const UNVERIFIED_CHANNEL = "Канал ещё не проверен в справочнике.";
const SELF_FILING_NOTE = "ДомСигнал не отправляет обращения за вас — вы отправляете его сами.";
const TEXT_HINT = "Текст можно поправить перед отправкой — сохраните правку.";
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
  const pending = useRef(false);
  const filed = draft.filed_at !== null;
  const actions = knownActions(draft.allowed_actions);
  const descriptor = (code: string) => actions.find((item) => item.code === code);
  const channel = draft.channel;
  const url = safeUrl(channel?.url);
  const verified = formatDay(channel?.verified_at);
  const needsCheck = Boolean(
    channel && (channel.stale || channel.verification_status !== "verified"),
  );

  const guard = useCallback(async (run: () => Promise<AppealDraftView>) => {
    if (pending.current) return;
    pending.current = true;
    setSaving(true);
    setError(null);
    try {
      onLoaded(await run());
      setConflict(null);
    } catch (failure) {
      setError(failure);
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
  }, [client, draft.id, onLoaded]);

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

  return (
    <>
      <Panel className="detail-section draft-recipient">
        <Typography.Title asChild>
          <h2>Куда отправлять</h2>
        </Typography.Title>
        <dl>
          <div className="info-row">
            <dt>Адресат</dt>
            <dd>{draft.organization_name ?? "Не назван в справочнике"}</dd>
          </div>
          <div className="info-row">
            <dt>Официальный канал</dt>
            <dd>{channel?.label ?? "Проверенного канала пока нет"}</dd>
          </div>
        </dl>
        {verified && <p className="muted">Проверено: {verified}</p>}
        {needsCheck && (
          <p className="honesty-note" role="note">
            Сведения о канале требуют сверки.
          </p>
        )}
        {!channel && <p className="muted">{UNVERIFIED_CHANNEL}</p>}
        <SourceChip source={draft.provenance} />
      </Panel>

      {(channel?.facts ?? []).length > 0 && (
        <Panel className="detail-section draft-channel-facts">
          <Typography.Title asChild>
            <h2>Что известно о канале</h2>
          </Typography.Title>
          <ul>
            {(channel?.facts ?? []).map((fact) => (
              <li key={fact.text}>
                <span className="full-text">{fact.text}</span>
                <SourceLink url={fact.source_url} title={fact.source_title} />
              </li>
            ))}
          </ul>
        </Panel>
      )}

      <Panel className="detail-section draft-editor">
        <Typography.Title asChild>
          <h2>Текст обращения</h2>
        </Typography.Title>
        {draft.ai_assisted && (
          <p className="honesty-note" role="note">
            {AI_NOTE}
          </p>
        )}
        <p className="muted">{TEXT_HINT}</p>
        <label htmlFor={`${id}-text`}>Обращение</label>
        <Textarea
          id={`${id}-text`}
          ref={area}
          value={text}
          disabled={filed || busy}
          rows={12}
          onChange={(event) => {
            setText(event.target.value);
            setCopy(null);
          }}
        />
        <p className="muted">
          Версия {draft.version} · сохранено {formatDate(draft.updated_at) ?? "—"}
        </p>
        {!filed && (
          <Button
            variant="secondary"
            disabled={saving || busy || text.trim().length === 0 || text === draft.text}
            onClick={() =>
              void guard(() =>
                client.saveAppealDraft(draft.id, { text, version: draft.version }),
              )
            }
          >
            {saving ? "Сохраняем…" : "Сохранить правку"}
          </Button>
        )}
        {conflict && (
          <Panel className="draft-conflict" role="alert">
            <Typography.Text variant="body-strong">{CONFLICT_NOTE}</Typography.Text>
            <p className="full-text">{conflict.text}</p>
            <Button
              variant="secondary"
              onClick={() => {
                setText(conflict.text);
                onLoaded(conflict);
                setConflict(null);
              }}
            >
              Взять версию с сервера
            </Button>
          </Panel>
        )}
        {Boolean(error) && problemStatus(error) !== 409 && (
          <p role="alert">
            Не удалось сохранить правку. Текст остался на экране.{" "}
            {retryable(error) ? "Попробуйте ещё раз." : "Обновите данные и проверьте доступ."}
          </p>
        )}
        {error instanceof ApiProblem && problemStatus(error) === 409 && (
          <p role="status" className="muted">
            Обновите текст и сохраните ещё раз.
          </p>
        )}
      </Panel>

      <Panel className="next-action draft-actions" aria-labelledby={`${id}-next`}>
        <Typography.Text variant="label-strong" className="eyebrow">
          Следующий шаг
        </Typography.Text>
        <Typography.Title asChild>
          <h2 id={`${id}-next`}>Что делать сейчас</h2>
        </Typography.Title>
        <p className="muted">{SELF_FILING_NOTE}</p>
        <Flex direction="column" gap={12}>
          {ACTION_ORDER.map((code) => {
            const action = descriptor(code);
            if (!action) return null;
            const reasonId = action.reason ? `${id}-${code}-reason` : undefined;
            const reason = action.reason && (
              <p id={reasonId} className="muted action-reason">
                {action.reason}
              </p>
            );
            if (code === "copy_draft")
              return (
                <div key={code}>
                  <Button
                    stretched
                    disabled={!action.enabled}
                    aria-describedby={reasonId}
                    onClick={() => void copyText()}
                  >
                    {actionLabels.copy_draft}
                  </Button>
                  {reason}
                  {copy && (
                    <p role="status" className="muted">
                      {copy}
                    </p>
                  )}
                </div>
              );
            if (code === "open_official_channel")
              return (
                <div key={code}>
                  {action.enabled && url ? (
                    <Button asChild stretched>
                      <a
                        href={url}
                        target="_blank"
                        rel="noopener noreferrer"
                        onClick={(event) => {
                          if (maxBridge.openLink(url)) event.preventDefault();
                        }}
                      >
                        {actionLabels.open_official_channel} ↗
                      </a>
                    </Button>
                  ) : (
                    <Button stretched disabled aria-describedby={reasonId}>
                      {actionLabels.open_official_channel}
                    </Button>
                  )}
                  {reason}
                  {!url && channel?.entry_hint && (
                    <p className="muted">Вход: {channel.entry_hint}</p>
                  )}
                </div>
              );
            return (
              <div key={code}>
                <label className="draft-reference" htmlFor={`${id}-reference`}>
                  Номер обращения, если он есть
                  <input
                    id={`${id}-reference`}
                    value={reference}
                    disabled={busy || !action.enabled}
                    maxLength={200}
                    onChange={(event) => setReference(event.target.value)}
                  />
                </label>
                <Button
                  stretched
                  disabled={busy || saving || !action.enabled}
                  aria-describedby={reasonId}
                  onClick={() =>
                    void guard(() =>
                      client.markAppealFiled(draft.id, reference.trim() || null),
                    )
                  }
                >
                  {actionLabels.mark_filed}
                </Button>
                {reason}
              </div>
            );
          })}
        </Flex>
        {filed && (
          <p className="honesty-note" role="status">
            {FILED_NOTE}
            {draft.filed_reference ? ` Ваш номер: ${draft.filed_reference}.` : ""}
          </p>
        )}
      </Panel>
    </>
  );
}
