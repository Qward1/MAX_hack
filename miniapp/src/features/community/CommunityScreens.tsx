import { type ReactNode, useCallback, useId, useState } from "react";
import { ApiProblem, problemStatus, retryable } from "../../shared/api/client";
import type { ActivityItem, AnnouncementItem, CommunityApi, PollView, VerifiedSource } from "../../shared/api/community";
import { PAGE_SIZE } from "../../shared/api/community";
import { useResource } from "../../shared/api/useResource";
import { maxBridge, safeUrl } from "../../shared/max/bridge";
import { Button } from "../../shared/ui/Button";
import { countLabel, formatDay, formatWhen } from "../../shared/ui/format";
import { ConfirmDialog, InfoRow, Notice, StatePanel, StatusTag } from "../../shared/ui/semantic";

export type CommunityView = "home" | "news" | "poll" | "works" | "mine" | "reception";

/** Куда ведёт экран сообщества. Адреса собирает приложение (`routeUrl`). */
export type CommunityLinks = {
  board: (houseId?: string) => string;
  view: (view: CommunityView, extra?: { house?: string; poll?: string }) => string;
  incident: (houseId: string, incidentId: string) => string;
  card: (houseId: string, outcomeId: string) => string;
  draft: (houseId: string, draftId: string) => string;
  report: (houseId: string) => string;
  navigate: (href: string) => void;
};

/** Ссылка во внешний сервис: только http(s), в MAX — через мост. */
function ExternalLink({ href, children }: { href: string; children: ReactNode }) {
  const url = safeUrl(href);
  if (!url) return <>{children}</>;
  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      onClick={(event) => {
        if (maxBridge.openLink(url)) event.preventDefault();
      }}
    >
      {children} ↗
    </a>
  );
}

/** Ссылка внутри приложения: без перезагрузки, с обычным открытием в новой вкладке. */
function AppLink({ href, navigate, className, children }: { href: string; navigate: (href: string) => void; className?: string; children: ReactNode }) {
  return (
    <a
      className={className}
      href={href}
      onClick={(event) => {
        if (event.ctrlKey || event.metaKey || event.shiftKey || event.button !== 0) return;
        event.preventDefault();
        navigate(href);
      }}
    >
      {children}
    </a>
  );
}

function Source({ source }: { source: VerifiedSource }) {
  const checked = formatDay(source.verified_at);
  return (
    <p className="ds-meta">
      Источник: {source.url ? <ExternalLink href={source.url}>{source.title}</ExternalLink> : source.title}
      {checked && `, проверено ${checked}`}
    </p>
  );
}

function problemText(error: unknown, subject: string): { title: string; detail: string } {
  const status = problemStatus(error);
  if (status === 403)
    return {
      title: "Раздел доступен жителям дома",
      detail: "Откройте ДомСигнал кнопкой из вашего домового чата или выберите дом с открытым доступом.",
    };
  if (status === 404) return { title: `Не нашли ${subject}`, detail: "Возможно, ссылка устарела. Вернитесь назад." };
  if (status === 401)
    return { title: "Сессия MAX истекла", detail: "Закройте мини-приложение и откройте его снова в MAX." };
  if (status === 429) return { title: "Слишком много запросов", detail: "Подождите минуту и попробуйте ещё раз." };
  return { title: `Не удалось загрузить ${subject}`, detail: "Проверьте интернет и попробуйте ещё раз." };
}

function Failure({ error, subject, onRetry }: { error: unknown; subject: string; onRetry: () => void }) {
  const text = problemText(error, subject);
  return (
    <StatePanel
      kind="error"
      title={text.title}
      detail={text.detail}
      action={retryable(error) ? "Повторить" : undefined}
      onAction={onRetry}
    />
  );
}

function actionError(error: unknown): string {
  if (error instanceof ApiProblem) {
    if (error.problem.code === "poll_closed") return "Опрос уже закрыт — голос не принят.";
    if (error.problem.code === "slot_full") return error.problem.detail;
    if (error.problem.status === 403) return "Это доступно только жителям дома.";
    if (error.problem.status === 422) return "Проверьте выбор и попробуйте ещё раз.";
  }
  return "Не получилось. Проверьте интернет и попробуйте ещё раз.";
}

/** Номер телефона внутри строки памятки — ссылкой `tel:`. */
function WithPhone({ text, phone }: { text: string; phone?: string | null }) {
  if (!phone || !text.includes(phone)) return <>{text}</>;
  const [before, ...rest] = text.split(phone);
  return (
    <>
      {before}
      <a href={`tel:${phone}`}>{phone}</a>
      {rest.join(phone)}
    </>
  );
}

// ------------------------------------------------------------------ «Мой дом»

export function MyHouseScreen({ api, houseId, links }: { api: CommunityApi; houseId: string; links: CommunityLinks }) {
  const load = useCallback((signal: AbortSignal) => api.houseOverview(houseId, signal), [api, houseId]);
  const resource = useResource(`overview:${houseId}`, load);
  if (resource.error && !resource.data)
    return <Failure error={resource.error} subject="сведения о доме" onRetry={resource.refresh} />;
  if (!resource.data) return <StatePanel title="Загружаем сведения о доме" loading />;
  const house = resource.data;
  const company = house.company;
  const facts = [
    house.entrance_count ? countLabel(house.entrance_count, ["подъезд", "подъезда", "подъездов"]) : null,
    house.floor_count ? countLabel(house.floor_count, ["этаж", "этажа", "этажей"]) : null,
  ].filter(Boolean);
  const contacts: [string, ReactNode][] = company
    ? (
        [
          [
            "Аварийно-диспетчерская служба",
            company.dispatcher_phone && <a href={`tel:${company.dispatcher_phone}`}>{company.dispatcher_phone}</a>,
          ],
          ["Телефон", company.phone && <a href={`tel:${company.phone}`}>{company.phone}</a>],
          ["Почта", company.email && <a href={`mailto:${company.email}`}>{company.email}</a>],
          ["Часы работы", company.office_hours],
          ["Часы приёма", company.reception_hours],
          ["Адрес офиса", company.office_address],
          ["Сайт", company.website && <ExternalLink href={company.website}>{company.website}</ExternalLink>],
        ] as [string, ReactNode][]
      ).filter(([, value]) => Boolean(value))
    : [];
  const steps = house.accident_steps ?? [];
  const emergency = house.emergency ?? [];
  const companyUpdated = formatDay(company?.updated_at);
  const factsUpdated = formatDay(house.facts_updated_at);
  return (
    <>
      {(steps.length > 0 || emergency.length > 0) && (
        <section className="ds-safety" id="emergency" aria-labelledby="emergency-title">
          <h2 id="emergency-title">Если авария</h2>
          {steps.length > 0 && (
            <ol className="ds-bullets">
              {steps.map((step) => (
                <li key={step.text}>
                  <p>
                    <WithPhone text={step.text} phone={step.phone} />
                  </p>
                  {step.source && <Source source={step.source} />}
                </li>
              ))}
            </ol>
          )}
          {emergency.length > 0 && (
            <ul className="ds-bullets">
              {emergency.map((item) => (
                <li key={`${item.title}-${item.phone}`}>
                  <p>
                    <strong>{item.title}</strong>
                    {item.phone && !item.title.includes(item.phone) && (
                      <>
                        {" — "}
                        <a href={`tel:${item.phone}`}>{item.phone}</a>
                      </>
                    )}
                  </p>
                  {(item.lines ?? []).map((line) => (
                    <p key={line} className="ds-subtle">
                      {line}
                    </p>
                  ))}
                  <Source source={item.source} />
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
      <section className="ds-section" aria-labelledby="company-title">
        <h2 id="company-title">Управляющая компания</h2>
        {company ? (
          <>
            <p className="ds-strong">{company.name}</p>
            {contacts.length ? (
              <>
                <dl className="ds-kv">
                  {contacts.map(([label, value]) => (
                    <InfoRow key={label} label={label}>
                      {value}
                    </InfoRow>
                  ))}
                </dl>
                <p className="ds-meta">
                  По данным управляющей компании{companyUpdated && `, обновлено ${companyUpdated}`}. ДомСигнал эти
                  сведения не проверяет.
                </p>
              </>
            ) : (
              <p className="ds-subtle">Управляющая компания пока не заполнила контакты.</p>
            )}
            {house.reception_available && (
              <div>
                <Button onClick={() => links.navigate(links.view("reception", { house: houseId }))}>
                  Записаться на приём
                </Button>
              </div>
            )}
          </>
        ) : (
          <p className="ds-subtle">К дому не подключена управляющая компания.</p>
        )}
      </section>
      <section className="ds-section" aria-labelledby="house-title">
        <h2 id="house-title">Дом</h2>
        <dl className="ds-kv">
          <InfoRow label="Адрес">{house.address}</InfoRow>
          {facts.length > 0 && (
            <InfoRow label="Подъезды и этажи">
              {facts.join(", ")}
              <span className="ds-meta"> — по данным управляющей компании{factsUpdated && `, ${factsUpdated}`}</span>
            </InfoRow>
          )}
          <InfoRow label="Домовой чат">
            {house.chat.connected
              ? house.chat.reading_enabled
                ? "Подключён. Бот читает сообщения, чтобы замечать проблемы"
                : "Подключён. Бот отвечает на команду /report"
              : "Не подключён"}
          </InfoRow>
        </dl>
        <AppLink className="ds-link-button" href={links.view("works", { house: houseId })} navigate={links.navigate}>
          Что сделано в доме за последние месяцы
        </AppLink>
      </section>
      <section className="ds-section" aria-labelledby="channels-title">
        <h2 id="channels-title">Официальные сервисы региона</h2>
        {(house.channels ?? []).length ? (
          <ul className="ds-bullets">
            {(house.channels ?? []).map((channel) => (
              <li key={channel.id}>
                <p>
                  <strong>{channel.url ? <ExternalLink href={channel.url}>{channel.label}</ExternalLink> : channel.label}</strong>
                  {channel.phone && (
                    <>
                      {" — "}
                      <a href={`tel:${channel.phone}`}>{channel.phone}</a>
                    </>
                  )}
                </p>
                <Source source={channel.source} />
              </li>
            ))}
          </ul>
        ) : (
          <p className="ds-subtle">Проверенных сервисов для региона дома пока нет в справочнике.</p>
        )}
      </section>
    </>
  );
}

// ------------------------------------------------------------------ объявления

export function AnnouncementsScreen({ api, houseId, links }: { api: CommunityApi; houseId: string; links: CommunityLinks }) {
  const [offset, setOffset] = useState(0);
  const load = useCallback((signal: AbortSignal) => api.announcements(houseId, offset, signal), [api, houseId, offset]);
  const resource = useResource(`news:${houseId}:${offset}`, load);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  if (resource.error && !resource.data)
    return <Failure error={resource.error} subject="объявления" onRetry={resource.refresh} />;
  if (!resource.data) return <StatePanel title="Загружаем объявления" loading />;
  const list = resource.data;
  async function toggle() {
    setSaving(true);
    setMessage(null);
    try {
      const result = await api.setPreferences(!list.broadcast_opt_out);
      setMessage(
        result.broadcast_opt_out
          ? "Рассылки больше не придут в личные сообщения. Объявления остаются здесь и в домовом чате."
          : "Рассылки снова будут приходить в личные сообщения.",
      );
      resource.refresh();
    } catch (error) {
      setMessage(actionError(error));
    } finally {
      setSaving(false);
    }
  }
  return (
    <>
      {list.items.length ? (
        <ul className="ds-list" aria-label="Объявления дома">
          {list.items.map((item) => (
            <li key={item.id}>
              <Announcement item={item} houseId={houseId} links={links} />
            </li>
          ))}
        </ul>
      ) : (
        <StatePanel
          title="Объявлений пока нет"
          detail="Здесь появятся объявления и опросы управляющей компании для вашего дома."
        />
      )}
      <Pager offset={offset} total={list.page.total} shown={list.items.length} onPage={setOffset} />
      <section className="ds-section" aria-labelledby="dm-title">
        <h2 id="dm-title">Рассылки в личные сообщения</h2>
        <p>
          Сейчас: <strong>{list.broadcast_opt_out ? "не получаю" : "получаю"}</strong>
        </p>
        <div>
          <Button loading={saving} loadingLabel="Сохраняем…" onClick={() => void toggle()}>
            {list.broadcast_opt_out ? "Получать рассылки" : "Не получать рассылки"}
          </Button>
        </div>
        {message && (
          <p role="status" className="ds-meta">
            {message}
          </p>
        )}
      </section>
    </>
  );
}

function Announcement({ item, houseId, links }: { item: AnnouncementItem; houseId: string; links: CommunityLinks }) {
  const kind =
    item.kind === "poll" ? "Опрос" : (item.topic_label ?? (item.kind === "mailing" ? "Рассылка" : "Объявление"));
  return (
    <article className="ds-row">
      <p className="ds-meta">
        {kind} · <time dateTime={item.sent_at}>{formatWhen(item.sent_at)}</time>
        {item.edited_at && ` · изменено ${formatWhen(item.edited_at)}`}
      </p>
      <h3>{item.title}</h3>
      {item.body && <LongText text={item.body} />}
      <p className="ds-meta">{item.sender}</p>
      {item.poll && (
        <div className="ds-actions">
          <Button
            variant={item.poll.closed || item.poll.voted ? "secondary" : "primary"}
            onClick={() => links.navigate(links.view("poll", { house: houseId, poll: item.poll!.poll_id }))}
          >
            {item.poll.closed ? "Итоги опроса" : item.poll.voted ? "Изменить голос" : "Проголосовать"}
          </Button>
          <span className="ds-meta">
            {item.poll.closed ? "Опрос закрыт" : `До ${formatWhen(item.poll.closes_at)}`},{" "}
            {countLabel(item.poll.voters, ["голос", "голоса", "голосов"])}
          </span>
        </div>
      )}
    </article>
  );
}

/** Длинный текст свёрнут до нескольких строк; «Показать полностью» раскрывает его. */
function LongText({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const long = text.length > 420;
  return (
    <>
      <p className={long && !open ? "ds-prose ds-clamp" : "ds-prose"}>{text}</p>
      {long && (
        <button type="button" className="ds-link-button" aria-expanded={open} onClick={() => setOpen(!open)}>
          {open ? "Свернуть" : "Показать полностью"}
        </button>
      )}
    </>
  );
}

function Pager({ offset, total, shown, onPage }: { offset: number; total: number; shown: number; onPage: (offset: number) => void }) {
  if (total <= PAGE_SIZE && offset === 0) return null;
  return (
    <nav className="pagination" aria-label="Страницы списка">
      <Button disabled={offset === 0} onClick={() => onPage(Math.max(0, offset - PAGE_SIZE))}>
        Предыдущие
      </Button>
      <span className="ds-meta">
        {offset + 1}–{offset + shown} из {total}
      </span>
      <Button disabled={offset + shown >= total} onClick={() => onPage(offset + PAGE_SIZE)}>
        Следующие
      </Button>
    </nav>
  );
}

// ------------------------------------------------------------------------ опрос

export function PollScreen({
  api,
  pollId,
}: {
  api: CommunityApi;
  pollId: string;
  houseId?: string;
  links: CommunityLinks;
}) {
  const load = useCallback((signal: AbortSignal) => api.poll(pollId, signal), [api, pollId]);
  const resource = useResource(`poll:${pollId}`, load);
  const [chosen, setChosen] = useState<string[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ text: string; ok: boolean } | null>(null);
  const [result, setResult] = useState<PollView | null>(null);
  if (resource.error && !resource.data) return <Failure error={resource.error} subject="опрос" onRetry={resource.refresh} />;
  if (!resource.data) return <StatePanel title="Загружаем опрос" loading />;
  const poll = result ?? resource.data;
  const mine = poll.my_choice ?? [];
  const selected = chosen ?? mine;
  const toggle = (option: string) =>
    setChosen(
      poll.multiple
        ? selected.includes(option)
          ? selected.filter((item) => item !== option)
          : [...selected, option]
        : [option],
    );
  async function submit() {
    setBusy(true);
    setMessage(null);
    try {
      const updated = await api.vote(poll.id, selected);
      setResult(updated);
      setChosen(null);
      setMessage({ text: "Голос учтён. До закрытия опроса его можно изменить.", ok: true });
      maxBridge.haptic("success");
    } catch (error) {
      setMessage({ text: actionError(error), ok: false });
      if (error instanceof ApiProblem && error.problem.code === "poll_closed") resource.refresh();
    } finally {
      setBusy(false);
    }
  }
  const changed =
    selected.length > 0 && (selected.length !== mine.length || selected.some((item) => !mine.includes(item)));
  return (
    <section className="ds-section" aria-labelledby="poll-question">
      <h2 id="poll-question">{poll.question}</h2>
      <p className="ds-meta">
        {poll.sender} · {poll.closed ? "опрос закрыт" : `голосование до ${formatWhen(poll.closes_at)}`}
      </p>
      <Notice tone="neutral">
        <p>{poll.disclaimer}</p>
      </Notice>
      <fieldset className="poll-options" disabled={!poll.can_vote || busy}>
        <legend>{poll.multiple ? "Можно выбрать несколько вариантов" : "Выберите один вариант"}</legend>
        {poll.options.map((option) => {
          const percent = Math.round(option.share * 100);
          return (
            <label key={option.id} className="poll-option">
              <input
                type={poll.multiple ? "checkbox" : "radio"}
                name="poll-option"
                checked={selected.includes(option.id)}
                onChange={() => toggle(option.id)}
              />
              <span>{option.label}</span>
              <span className="poll-count">
                {countLabel(option.votes, ["голос", "голоса", "голосов"])}, {percent}%
              </span>
              <span className="result-bar" aria-hidden="true">
                <span style={{ width: `${percent}%` }} />
              </span>
            </label>
          );
        })}
      </fieldset>
      <p className="ds-meta">
        Проголосовали: {countLabel(poll.voters, ["житель", "жителя", "жителей"])}. Итоги — только числа, без имён.
      </p>
      {poll.reason && <p className="ds-subtle">{poll.reason}</p>}
      {poll.can_vote && mine.length > 0 && !changed && (
        <p className="ds-subtle">Ваш голос учтён. Чтобы изменить его, выберите другой вариант.</p>
      )}
      {poll.can_vote && (
        <div>
          <Button variant="primary" disabled={!changed} loading={busy} loadingLabel="Сохраняем…" onClick={() => void submit()}>
            {mine.length ? "Изменить голос" : "Проголосовать"}
          </Button>
        </div>
      )}
      {message && (
        <Notice tone={message.ok ? "success" : "danger"} role={message.ok ? "status" : "alert"}>
          <p>{message.text}</p>
        </Notice>
      )}
    </section>
  );
}

// ---------------------------------------------------------- выполненные работы

export function WorksScreen({ api, houseId, links }: { api: CommunityApi; houseId: string; links: CommunityLinks }) {
  const [days, setDays] = useState<30 | 90>(30);
  const [offset, setOffset] = useState(0);
  const load = useCallback(
    (signal: AbortSignal) => api.completedWorks(houseId, days, offset, signal),
    [api, houseId, days, offset],
  );
  const resource = useResource(`works:${houseId}:${days}:${offset}`, load);
  const periods = (
    <div className="segmented" role="group" aria-label="Период">
      {([30, 90] as const).map((value) => (
        <button
          key={value}
          type="button"
          className="ds-btn ds-btn-secondary"
          aria-pressed={days === value}
          onClick={() => {
            setDays(value);
            setOffset(0);
          }}
        >
          За {value} дней
        </button>
      ))}
    </div>
  );
  if (resource.error && !resource.data)
    return (
      <>
        {periods}
        <Failure error={resource.error} subject="выполненные работы" onRetry={resource.refresh} />
      </>
    );
  if (!resource.data)
    return (
      <>
        {periods}
        <StatePanel title="Загружаем выполненные работы" loading />
      </>
    );
  const list = resource.data;
  return (
    <>
      {periods}
      {list.items.length ? (
        <ul className="ds-list" aria-label="Выполненные работы">
          {list.items.map((item) => (
            <li key={item.attempt_id}>
              <AppLink className="ds-row" href={links.incident(houseId, item.incident_id)} navigate={links.navigate}>
                <span className="ds-row-head">
                  <span className="ds-row-title">
                    {item.category_title}
                    {item.entrance && `, подъезд ${item.entrance}`}
                  </span>
                  <StatusTag
                    entry={
                      item.outcome === "confirmed"
                        ? { label: "Жители подтвердили", tone: "success" }
                        : { label: "Возвращено в работу", tone: "warning" }
                    }
                  />
                </span>
                <span className="ds-row-text">{item.public_description}</span>
                <span className="ds-meta">
                  Исполнитель сообщил {formatWhen(item.reported_at)}
                  {item.outcome_at && `, жители проверили ${formatWhen(item.outcome_at)}`}
                </span>
              </AppLink>
            </li>
          ))}
        </ul>
      ) : (
        <StatePanel
          title={`За ${days} дней выполненных работ нет`}
          detail="Здесь появятся работы, о которых сообщил исполнитель, и итог проверки жителями."
        />
      )}
      <Pager offset={offset} total={list.page.total} shown={list.items.length} onPage={setOffset} />
    </>
  );
}

// -------------------------------------------------------------- «Мои обращения»

const kindLabels: Record<ActivityItem["kind"], string> = {
  report: "Ваше сообщение о проблеме",
  joined: "«Меня тоже касается»",
  route_card: "Куда обратиться",
  appeal_draft: "Черновик обращения",
};

function activityHref(item: ActivityItem, links: CommunityLinks): string | null {
  if ((item.kind === "report" || item.kind === "joined") && item.incident_id)
    return links.incident(item.house_id, item.incident_id);
  if (item.kind === "appeal_draft" && item.appeal_draft_id) return links.draft(item.house_id, item.appeal_draft_id);
  if (item.route_outcome_id) return links.card(item.house_id, item.route_outcome_id);
  return null;
}

function ActivityRow({ item, links, showAddress }: { item: ActivityItem; links: CommunityLinks; showAddress: boolean }) {
  const href = activityHref(item, links);
  // Название уже может начинаться с вида записи («Черновик обращения · …») — не повторяем.
  const kind = item.title.startsWith(kindLabels[item.kind]) ? null : kindLabels[item.kind];
  const body = (
    <>
      <span className="ds-meta">
        {kind && `${kind} · `}
        <time dateTime={item.occurred_at}>{formatWhen(item.occurred_at)}</time>
      </span>
      <span className="ds-row-head">
        <span className="ds-row-title">
          {item.title}
          {item.ticket_number && ` · ${item.ticket_number}`}
        </span>
      </span>
      <span>{item.status_label}</span>
      {item.filed_at && (
        <span className="ds-meta">
          Вы отметили отправку {formatWhen(item.filed_at)}. ДомСигнал не подтверждает регистрацию во внешней системе.
        </span>
      )}
      {showAddress && <span className="ds-meta">{item.house_address}</span>}
    </>
  );
  return href ? (
    <AppLink className="ds-row" href={href} navigate={links.navigate}>
      {body}
    </AppLink>
  ) : (
    <div className="ds-row">{body}</div>
  );
}

export function MyActivityScreen({ api, houseId, links }: { api: CommunityApi; houseId?: string; links: CommunityLinks }) {
  const [offset, setOffset] = useState(0);
  const load = useCallback((signal: AbortSignal) => api.myActivity(offset, signal), [api, offset]);
  const resource = useResource(`mine:${offset}`, load);
  if (resource.error && !resource.data)
    return <Failure error={resource.error} subject="ваши обращения" onRetry={resource.refresh} />;
  if (!resource.data) return <StatePanel title="Загружаем ваши обращения" loading />;
  const list = resource.data;
  const manyHouses = new Set(list.items.map((item) => item.house_id)).size > 1;
  return (
    <>
      {list.items.length ? (
        <ul className="ds-list" aria-label="Мои обращения">
          {list.items.map((item) => (
            <li key={`${item.kind}-${item.id}`}>
              <ActivityRow item={item} links={links} showAddress={manyHouses} />
            </li>
          ))}
        </ul>
      ) : (
        <StatePanel
          title="Здесь появятся ваши обращения"
          detail="Ваши сообщения о проблемах, черновики обращений и проблемы, где вы отметили «Меня тоже касается»."
          action={houseId ? "Сообщить о проблеме" : undefined}
          onAction={houseId ? () => links.navigate(links.report(houseId)) : undefined}
        />
      )}
      <Pager offset={offset} total={list.page.total} shown={list.items.length} onPage={setOffset} />
    </>
  );
}

/** Главный экран: три последних обращения жителя в этом доме и путь ко всем. */
export function RecentActivity({ api, houseId, links }: { api: CommunityApi; houseId: string; links: CommunityLinks }) {
  const titleId = useId();
  const load = useCallback((signal: AbortSignal) => api.myActivity(0, signal), [api]);
  const resource = useResource(`recent:${houseId}`, load);
  if (resource.error && !resource.data)
    return (
      <section className="ds-group" aria-labelledby={titleId}>
        <h2 id={titleId}>Ваши обращения</h2>
        <p className="ds-subtle">Не удалось загрузить ваши обращения.</p>
        {retryable(resource.error) && (
          <div>
            <Button small onClick={resource.refresh}>
              Повторить<span className="ds-visually-hidden"> загрузку обращений</span>
            </Button>
          </div>
        )}
      </section>
    );
  const items = (resource.data?.items ?? []).filter((item) => item.house_id === houseId).slice(0, 3);
  if (!items.length) return null;
  return (
    <section className="ds-group" aria-labelledby={titleId}>
      <div className="ds-group-head">
        <h2 id={titleId}>Ваши обращения</h2>
        <AppLink className="ds-link-button" href={links.view("mine", { house: houseId })} navigate={links.navigate}>
          Все обращения
        </AppLink>
      </div>
      <ul className="ds-list">
        {items.map((item) => (
          <li key={`${item.kind}-${item.id}`}>
            <ActivityRow item={item} links={links} showAddress={false} />
          </li>
        ))}
      </ul>
    </section>
  );
}

// ------------------------------------------------------------ запись на приём

export function ReceptionScreen({ api, houseId }: { api: CommunityApi; houseId: string; links: CommunityLinks }) {
  const id = useId();
  const load = useCallback((signal: AbortSignal) => api.reception(houseId, signal), [api, houseId]);
  const resource = useResource(`reception:${houseId}`, load);
  const [slot, setSlot] = useState<string>("");
  const [topic, setTopic] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ text: string; ok: boolean } | null>(null);
  const [cancelling, setCancelling] = useState<{ id: string; when: string } | null>(null);
  if (resource.error && !resource.data)
    return <Failure error={resource.error} subject="время приёма" onRetry={resource.refresh} />;
  if (!resource.data) return <StatePanel title="Загружаем время приёма" loading />;
  const data = resource.data;
  const active = data.bookings.filter((item) => item.status === "booked");
  async function act(run: () => Promise<unknown>, done: string, keepInput = false) {
    setBusy(true);
    setMessage(null);
    try {
      await run();
      setMessage({ text: done, ok: true });
      if (!keepInput) {
        setTopic("");
        setSlot("");
      }
      maxBridge.haptic("success");
      resource.refresh();
    } catch (error) {
      setMessage({ text: actionError(error), ok: false });
    } finally {
      setBusy(false);
      setCancelling(null);
    }
  }
  return (
    <>
      {active.length > 0 && (
        <section className="ds-section" aria-labelledby={`${id}-mine`}>
          <h2 id={`${id}-mine`}>Ваши записи</h2>
          <ul className="ds-list">
            {active.map((booking) => (
              <li key={booking.id} className="ds-row">
                <p className="ds-strong">{formatWhen(booking.starts_at)}</p>
                <p>{booking.topic}</p>
                {booking.place && <p className="ds-meta">{booking.place}</p>}
                <div>
                  <Button
                    variant="danger"
                    disabled={busy}
                    onClick={() => setCancelling({ id: booking.id, when: formatWhen(booking.starts_at) ?? "" })}
                  >
                    Отменить запись
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}
      <section className="ds-section" aria-labelledby={`${id}-new`}>
        <h2 id={`${id}-new`}>Приём в {data.company_name || "управляющей компании"}</h2>
        {data.slots.length ? (
          <form
            className="ds-form"
            onSubmit={(event) => {
              event.preventDefault();
              void act(() => api.book(houseId, slot, topic.trim()), "Вы записаны. Накануне бот напомнит в личных сообщениях.");
            }}
          >
            <label className="ds-field">
              Время приёма
              <select value={slot} required onChange={(event) => setSlot(event.target.value)}>
                <option value="">Выберите время</option>
                {data.slots.map((item) => (
                  <option key={item.id} value={item.id} disabled={item.free === 0 || Boolean(item.my_booking_id)}>
                    {formatWhen(item.starts_at)} — {item.free ? `свободно мест: ${item.free}` : "мест нет"}
                    {item.my_booking_id ? ", вы записаны" : ""}
                  </option>
                ))}
              </select>
            </label>
            <div className="ds-field">
              <label htmlFor={`${id}-topic`}>С каким вопросом</label>
              <p id={`${id}-topic-hint`} className="ds-hint">
                Например: перерасчёт за отопление. От 3 до 300 символов.
              </p>
              <textarea
                id={`${id}-topic`}
                aria-describedby={`${id}-topic-hint`}
                value={topic}
                required
                minLength={3}
                maxLength={300}
                rows={3}
                onChange={(event) => setTopic(event.target.value)}
              />
            </div>
            <div>
              <Button type="submit" variant="primary" disabled={!slot || topic.trim().length < 3} loading={busy} loadingLabel="Записываем…">
                Записаться
              </Button>
            </div>
          </form>
        ) : (
          <p className="ds-subtle">Свободного времени приёма пока нет. Контакты управляющей компании — в разделе «Мой дом».</p>
        )}
        {message && (
          <Notice tone={message.ok ? "success" : "danger"} role={message.ok ? "status" : "alert"}>
            <p>{message.text}</p>
          </Notice>
        )}
      </section>
      {cancelling && (
        <ConfirmDialog
          title="Отменить запись на приём?"
          confirmLabel="Отменить запись"
          cancelLabel="Не отменять"
          tone="danger"
          busy={busy}
          busyLabel="Отменяем…"
          onCancel={() => setCancelling(null)}
          onConfirm={() => void act(() => api.cancelBooking(houseId, cancelling.id), "Запись отменена.", true)}
        >
          <p>
            Запись на {cancelling.when} будет отменена. Это время смогут занять другие жители.
          </p>
        </ConfirmDialog>
      )}
    </>
  );
}
