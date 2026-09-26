import { Button, Flex, Panel, Typography } from "@maxhub/max-ui";
import { type ReactNode, useCallback, useState } from "react";
import { ApiProblem, problemStatus, retryable } from "../../shared/api/client";
import type {
  ActivityItem,
  AnnouncementItem,
  CommunityApi,
  PollView,
  VerifiedSource,
} from "../../shared/api/community";
import { PAGE_SIZE } from "../../shared/api/community";
import { useResource } from "../../shared/api/useResource";
import { maxBridge, safeUrl } from "../../shared/max/bridge";
import { InfoRow, StatePanel } from "../../shared/ui/semantic";
import { formatDate } from "../incidents/presentation";

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

function day(value?: string | null): string | null {
  if (!value) return null;
  const date = new Date(value.length === 10 ? `${value}T12:00:00` : value);
  if (!Number.isFinite(date.getTime())) return null;
  return new Intl.DateTimeFormat("ru", { dateStyle: "medium" }).format(date);
}

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

function Source({ source }: { source: VerifiedSource }) {
  const checked = day(source.verified_at);
  return (
    <p className="muted community-source">
      Источник: {source.url ? <ExternalLink href={source.url}>{source.title}</ExternalLink> : source.title}
      {checked && ` · проверено ${checked}`}
    </p>
  );
}

function problemText(error: unknown, subject: string): { title: string; detail: string } {
  const status = problemStatus(error);
  if (status === 403)
    return {
      title: "Раздел доступен жителям дома",
      detail:
        "Откройте ДомСигнал кнопкой из вашего домового чата или выберите дом с открытым доступом.",
    };
  if (status === 404) return { title: `${subject} не найдено`, detail: "Вернитесь к доске дома." };
  if (status === 401)
    return {
      title: "Войдите через MAX",
      detail: "Закройте мини-приложение и откройте его заново в MAX.",
    };
  if (status === 429) return { title: "Слишком много запросов", detail: "Подождите минуту." };
  return { title: "Не удалось загрузить", detail: "Проверьте соединение и попробуйте ещё раз." };
}

function Failure({
  error,
  subject,
  onRetry,
}: {
  error: unknown;
  subject: string;
  onRetry: () => void;
}) {
  const text = problemText(error, subject);
  return (
    <StatePanel
      title={text.title}
      detail={text.detail}
      action={retryable(error) ? "Попробовать снова" : undefined}
      onAction={onRetry}
    />
  );
}

function actionError(error: unknown): string {
  if (error instanceof ApiProblem) {
    if (error.problem.code === "poll_closed") return "Опрос уже закрыт — голос не принят.";
    if (error.problem.code === "slot_full") return error.problem.detail;
    if (error.problem.status === 403) return "Действие доступно жителям дома.";
    if (error.problem.status === 422) return "Проверьте выбор и попробуйте ещё раз.";
  }
  return "Не получилось. Проверьте соединение и попробуйте ещё раз.";
}

// ------------------------------------------------------------------ «Мой дом»

export function MyHouseScreen({
  api,
  houseId,
  links,
}: {
  api: CommunityApi;
  houseId: string;
  links: CommunityLinks;
}) {
  const load = useCallback((signal: AbortSignal) => api.houseOverview(houseId, signal), [api, houseId]);
  const resource = useResource(`overview:${houseId}`, load);
  if (resource.error && !resource.data)
    return <Failure error={resource.error} subject="Дом" onRetry={resource.refresh} />;
  if (!resource.data)
    return <StatePanel title="Загрузка сведений о доме" detail="Получаем актуальные данные" loading />;
  const house = resource.data;
  const company = house.company;
  const facts = [
    house.entrance_count ? `Подъездов: ${house.entrance_count}` : null,
    house.floor_count ? `Этажей: ${house.floor_count}` : null,
  ].filter(Boolean);
  const contacts: [string, ReactNode][] = company
    ? (
        [
          ["Аварийно-диспетчерская служба", company.dispatcher_phone && <a href={`tel:${company.dispatcher_phone}`}>{company.dispatcher_phone}</a>],
          ["Телефон", company.phone && <a href={`tel:${company.phone}`}>{company.phone}</a>],
          ["Почта", company.email && <a href={`mailto:${company.email}`}>{company.email}</a>],
          ["Часы работы", company.office_hours],
          ["Часы приёма", company.reception_hours],
          ["Адрес офиса", company.office_address],
          ["Сайт", company.website && <ExternalLink href={company.website}>{company.website}</ExternalLink>],
        ] as [string, ReactNode][]
      ).filter(([, value]) => Boolean(value))
    : [];
  return (
    <>
      <Panel className="detail-section">
        <Typography.Title asChild>
          <h2>Дом</h2>
        </Typography.Title>
        <p className="full-text">{house.address}</p>
        {facts.length > 0 && (
          <p>
            {facts.join(" · ")}{" "}
            <span className="muted">
              — по данным УК{day(house.facts_updated_at) && `, обновлено ${day(house.facts_updated_at)}`}
            </span>
          </p>
        )}
        <dl>
          <InfoRow label="Домовой чат">
            {house.chat.connected
              ? house.chat.reading_enabled
                ? "Подключён, бот читает сообщения, чтобы замечать проблемы"
                : "Подключён, бот отвечает на /report"
              : "Не подключён"}
          </InfoRow>
        </dl>
      </Panel>
      <Panel className="detail-section">
        <Typography.Title asChild>
          <h2>Управляющая компания</h2>
        </Typography.Title>
        {company ? (
          <>
            <p className="full-text">
              <strong>{company.name}</strong>
            </p>
            {contacts.length ? (
              <>
                <dl>
                  {contacts.map(([label, value]) => (
                    <InfoRow key={label} label={label}>
                      {value}
                    </InfoRow>
                  ))}
                </dl>
                <p className="muted">
                  По данным УК{day(company.updated_at) && `, обновлено ${day(company.updated_at)}`} — ДомСигнал эти
                  сведения не проверяет.
                </p>
              </>
            ) : (
              <p className="muted">Управляющая компания пока не заполнила контакты.</p>
            )}
            {house.reception_available && (
              <Button onClick={() => links.navigate(links.view("reception", { house: houseId }))}>
                Записаться на приём
              </Button>
            )}
          </>
        ) : (
          <p className="muted">К дому не подключена управляющая компания.</p>
        )}
      </Panel>
      <Panel className="detail-section safety-panel">
        <Typography.Title asChild>
          <h2>Что делать при аварии</h2>
        </Typography.Title>
        <ol className="community-steps">
          {(house.accident_steps ?? []).map((step) => (
            <li key={step.text}>
              <p>
                {step.phone ? (
                  <>
                    {step.text.split(step.phone)[0]}
                    <a href={`tel:${step.phone}`}>{step.phone}</a>
                    {step.text.split(step.phone).slice(1).join(step.phone)}
                  </>
                ) : (
                  step.text
                )}
              </p>
              {step.source && <Source source={step.source} />}
            </li>
          ))}
        </ol>
      </Panel>
      {(house.emergency ?? []).length > 0 && (
        <Panel className="detail-section">
          <Typography.Title asChild>
            <h2>Аварийные номера и памятка</h2>
          </Typography.Title>
          <ul className="community-list">
            {(house.emergency ?? []).map((item) => (
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
                  <p key={line} className="muted">
                    {line}
                  </p>
                ))}
                <Source source={item.source} />
              </li>
            ))}
          </ul>
        </Panel>
      )}
      <Panel className="detail-section">
        <Typography.Title asChild>
          <h2>Официальные каналы региона</h2>
        </Typography.Title>
        {(house.channels ?? []).length ? (
          <ul className="community-list">
            {(house.channels ?? []).map((channel) => (
              <li key={channel.id}>
                <p>
                  <strong>
                    {channel.url ? <ExternalLink href={channel.url}>{channel.label}</ExternalLink> : channel.label}
                  </strong>
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
          <p className="muted">Проверенных каналов для региона дома пока нет в справочнике.</p>
        )}
      </Panel>
      <p className="muted">
        <ExternalLink href={`${window.location.origin}/privacy`}>Политика данных</ExternalLink> — что бот читает и
        хранит, как отключить чтение чата.
      </p>
    </>
  );
}

// ------------------------------------------------------------------ объявления

export function AnnouncementsScreen({
  api,
  houseId,
  links,
}: {
  api: CommunityApi;
  houseId: string;
  links: CommunityLinks;
}) {
  const [offset, setOffset] = useState(0);
  const load = useCallback(
    (signal: AbortSignal) => api.announcements(houseId, offset, signal),
    [api, houseId, offset],
  );
  const resource = useResource(`news:${houseId}:${offset}`, load);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  if (resource.error && !resource.data)
    return <Failure error={resource.error} subject="Раздел" onRetry={resource.refresh} />;
  if (!resource.data) return <StatePanel title="Загрузка объявлений" loading />;
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
        <ul className="community-list" aria-label="Объявления дома">
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
      <Panel className="detail-section">
        <Typography.Title asChild>
          <h2>Личные сообщения</h2>
        </Typography.Title>
        <p>
          Рассылки в личные сообщения: <strong>{list.broadcast_opt_out ? "не получаю" : "получаю"}</strong>
        </p>
        <Button variant="secondary" disabled={saving} onClick={() => void toggle()}>
          {list.broadcast_opt_out ? "Получать рассылки" : "Не получать рассылки"}
        </Button>
        {message && (
          <p role="status" className="muted">
            {message}
          </p>
        )}
      </Panel>
    </>
  );
}

function Announcement({
  item,
  houseId,
  links,
}: {
  item: AnnouncementItem;
  houseId: string;
  links: CommunityLinks;
}) {
  const kind = item.kind === "poll" ? "Опрос" : item.topic_label ?? (item.kind === "mailing" ? "Рассылка" : "Объявление");
  return (
    <article className="incident-card community-card">
      <Flex gap={12} wrap="wrap" justify="space-between">
        <Typography.Text variant="label" color="secondary">
          {kind}
        </Typography.Text>
        <time className="muted" dateTime={item.sent_at}>
          {formatDate(item.sent_at)}
        </time>
      </Flex>
      <Typography.Title asChild>
        <h3>{item.title}</h3>
      </Typography.Title>
      {item.body && <LongText text={item.body} />}
      {item.edited_at && <p className="muted">Изменено {formatDate(item.edited_at)}</p>}
      <p className="muted">{item.sender}</p>
      {item.poll && (
        <Flex gap={12} wrap="wrap" align="center" className="card-footer">
          <span className="muted">
            {item.poll.closed ? "Опрос закрыт" : `Голосование до ${formatDate(item.poll.closes_at)}`} ·
            проголосовали: {item.poll.voters}
          </span>
          <Button
            size="small"
            onClick={() => links.navigate(links.view("poll", { house: houseId, poll: item.poll!.poll_id }))}
          >
            {item.poll.closed ? "Итоги опроса" : item.poll.voted ? "Изменить голос" : "Голосовать"}
          </Button>
        </Flex>
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
      <p className={long && !open ? "full-text clamped-text" : "full-text"}>{text}</p>
      {long && (
        <Button size="small" variant="secondary" aria-expanded={open} onClick={() => setOpen(!open)}>
          {open ? "Свернуть" : "Показать полностью"}
        </Button>
      )}
    </>
  );
}

function Pager({
  offset,
  total,
  shown,
  onPage,
}: {
  offset: number;
  total: number;
  shown: number;
  onPage: (offset: number) => void;
}) {
  if (total <= PAGE_SIZE && offset === 0) return null;
  return (
    <nav className="pagination" aria-label="Страницы списка">
      <Button variant="secondary" disabled={offset === 0} onClick={() => onPage(Math.max(0, offset - PAGE_SIZE))}>
        Предыдущие
      </Button>
      <span>
        {offset + 1}–{offset + shown} из {total}
      </span>
      <Button variant="secondary" disabled={offset + shown >= total} onClick={() => onPage(offset + PAGE_SIZE)}>
        Следующие
      </Button>
    </nav>
  );
}

// ------------------------------------------------------------------------ опрос

export function PollScreen({
  api,
  pollId,
  houseId,
  links,
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
  const [message, setMessage] = useState<string | null>(null);
  const [result, setResult] = useState<PollView | null>(null);
  if (resource.error && !resource.data)
    return <Failure error={resource.error} subject="Опрос" onRetry={resource.refresh} />;
  if (!resource.data) return <StatePanel title="Загрузка опроса" loading />;
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
      setMessage("Голос учтён. До закрытия опроса его можно изменить.");
    } catch (error) {
      setMessage(actionError(error));
      if (error instanceof ApiProblem && error.problem.code === "poll_closed") resource.refresh();
    } finally {
      setBusy(false);
    }
  }
  const changed =
    selected.length > 0 &&
    (selected.length !== mine.length || selected.some((item) => !mine.includes(item)));
  return (
    <>
      <Panel className="detail-section">
        <Typography.Title asChild>
          <h2>{poll.question}</h2>
        </Typography.Title>
        <p className="muted">
          {poll.sender} ·{" "}
          {poll.closed ? `опрос закрыт` : `голосование до ${formatDate(poll.closes_at)}`}
        </p>
        <p className="honesty-inline">{poll.disclaimer}</p>
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
                <span className="poll-label">{option.label}</span>
                <span className="poll-count">
                  {option.votes} · {percent}%
                </span>
                <span className="result-bar" aria-hidden="true">
                  <span style={{ width: `${percent}%` }} />
                </span>
              </label>
            );
          })}
        </fieldset>
        <p className="muted">Проголосовали: {poll.voters}. Итоги — только числа, без имён.</p>
        {poll.reason && <p className="muted">{poll.reason}</p>}
        {poll.can_vote && mine.length > 0 && !changed && (
          <p className="muted">Ваш голос учтён. Чтобы изменить его, выберите другой вариант.</p>
        )}
        {poll.can_vote && (
          <Button disabled={busy || !changed} onClick={() => void submit()}>
            {mine.length ? "Изменить голос" : "Проголосовать"}
          </Button>
        )}
        {message && (
          <p role="status" className="muted">
            {message}
          </p>
        )}
      </Panel>
    </>
  );
}

// ---------------------------------------------------------- выполненные работы

export function WorksScreen({
  api,
  houseId,
  links,
}: {
  api: CommunityApi;
  houseId: string;
  links: CommunityLinks;
}) {
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
          className="ticket-button secondary"
          aria-pressed={days === value}
          onClick={() => {
            setDays(value);
            setOffset(0);
          }}
        >
          {value} дней
        </button>
      ))}
    </div>
  );
  if (resource.error && !resource.data)
    return <Failure error={resource.error} subject="Раздел" onRetry={resource.refresh} />;
  if (!resource.data)
    return (
      <>
        {periods}
        <StatePanel title="Загрузка выполненных работ" loading />
      </>
    );
  const list = resource.data;
  return (
    <>
      {periods}
      {list.items.length ? (
        <ul className="community-list" aria-label="Выполненные работы">
          {list.items.map((item) => (
            <li key={item.attempt_id}>
              <article className="incident-card community-card">
                <Flex gap={12} wrap="wrap" justify="space-between">
                  <Typography.Text variant="label" color="secondary">
                    {item.category_title}
                    {item.entrance && ` · подъезд ${item.entrance}`}
                  </Typography.Text>
                  <span className={`status-badge ${item.outcome === "confirmed" ? "tone-calm" : "tone-attention"}`}>
                    {item.outcome === "confirmed" ? "Жители подтвердили" : "Возвращено в работу"}
                  </span>
                </Flex>
                <p className="full-text">{item.public_description}</p>
                <p className="muted">
                  Отчёт исполнителя: {formatDate(item.reported_at)}
                  {item.outcome_at && ` · проверка жителей: ${formatDate(item.outcome_at)}`}
                </p>
                <Button
                  size="small"
                  variant="secondary"
                  aria-label={`Открыть проблему: ${item.category_title}, отчёт ${formatDate(item.reported_at) ?? ""}`}
                  onClick={() => links.navigate(links.incident(houseId, item.incident_id))}
                >
                  Открыть проблему
                </Button>
              </article>
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
  joined: "Меня тоже касается",
  route_card: "Карточка маршрута",
  appeal_draft: "Черновик обращения",
};

export function MyActivityScreen({
  api,
  houseId,
  links,
}: {
  api: CommunityApi;
  houseId?: string;
  links: CommunityLinks;
}) {
  const [offset, setOffset] = useState(0);
  const load = useCallback((signal: AbortSignal) => api.myActivity(offset, signal), [api, offset]);
  const resource = useResource(`mine:${offset}`, load);
  if (resource.error && !resource.data)
    return <Failure error={resource.error} subject="Раздел" onRetry={resource.refresh} />;
  if (!resource.data) return <StatePanel title="Загрузка ваших обращений" loading />;
  const list = resource.data;
  const open = (item: ActivityItem) => {
    if ((item.kind === "report" || item.kind === "joined") && item.incident_id)
      links.navigate(links.incident(item.house_id, item.incident_id));
    else if (item.kind === "appeal_draft" && item.appeal_draft_id)
      links.navigate(links.draft(item.house_id, item.appeal_draft_id));
    else if (item.route_outcome_id) links.navigate(links.card(item.house_id, item.route_outcome_id));
  };
  const openLabel: Record<ActivityItem["kind"], string> = {
    report: "Открыть проблему",
    joined: "Открыть проблему",
    route_card: "Открыть карточку",
    appeal_draft: "Открыть черновик",
  };
  return (
    <>
      {list.items.length ? (
        <ul className="community-list" aria-label="Мои обращения">
          {list.items.map((item) => (
            <li key={`${item.kind}-${item.id}`}>
              <article className="incident-card community-card">
                <Flex gap={12} wrap="wrap" justify="space-between">
                  <Typography.Text variant="label" color="secondary">
                    {kindLabels[item.kind]}
                  </Typography.Text>
                  <time className="muted" dateTime={item.occurred_at}>
                    {formatDate(item.occurred_at)}
                  </time>
                </Flex>
                <Typography.Title asChild>
                  <h3>
                    {item.title}
                    {item.ticket_number && <span className="muted"> · {item.ticket_number}</span>}
                  </h3>
                </Typography.Title>
                <p>{item.status_label}</p>
                {item.filed_at && (
                  <p className="muted">
                    Ваша отметка от {formatDate(item.filed_at)}. ДомСигнал не подтверждает регистрацию во внешней
                    системе.
                  </p>
                )}
                <p className="muted">{item.house_address}</p>
                <Button
                  size="small"
                  variant="secondary"
                  aria-label={`${openLabel[item.kind]}: ${item.title}`}
                  onClick={() => open(item)}
                >
                  {openLabel[item.kind]}
                </Button>
              </article>
            </li>
          ))}
        </ul>
      ) : (
        <StatePanel
          title="Здесь появятся ваши обращения"
          detail="Сообщения о проблемах, карточки маршрута, черновики и проблемы, где вы отметили «Меня тоже касается»."
          action={houseId ? "Сообщить о проблеме" : undefined}
          onAction={houseId ? () => links.navigate(links.report(houseId)) : undefined}
        />
      )}
      <Pager offset={offset} total={list.page.total} shown={list.items.length} onPage={setOffset} />
    </>
  );
}

// ------------------------------------------------------------ запись на приём

export function ReceptionScreen({
  api,
  houseId,
  links,
}: {
  api: CommunityApi;
  houseId: string;
  links: CommunityLinks;
}) {
  const load = useCallback((signal: AbortSignal) => api.reception(houseId, signal), [api, houseId]);
  const resource = useResource(`reception:${houseId}`, load);
  const [slot, setSlot] = useState<string>("");
  const [topic, setTopic] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  if (resource.error && !resource.data)
    return <Failure error={resource.error} subject="Раздел" onRetry={resource.refresh} />;
  if (!resource.data) return <StatePanel title="Загрузка времени приёма" loading />;
  const data = resource.data;
  const active = data.bookings.filter((item) => item.status === "booked");
  async function act(run: () => Promise<unknown>, done: string) {
    setBusy(true);
    setMessage(null);
    try {
      await run();
      setMessage(done);
      setTopic("");
      setSlot("");
      resource.refresh();
    } catch (error) {
      setMessage(actionError(error));
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <Panel className="detail-section">
        <Typography.Title asChild>
          <h2>Приём в {data.company_name || "управляющей компании"}</h2>
        </Typography.Title>
        {active.length > 0 && (
          <ul className="community-list" aria-label="Мои записи">
            {active.map((booking) => (
              <li key={booking.id}>
                <p>
                  <strong>{formatDate(booking.starts_at)}</strong> · {booking.topic}
                </p>
                {booking.place && <p className="muted">{booking.place}</p>}
                <Button
                  size="small"
                  variant="secondary"
                  disabled={busy}
                  onClick={() =>
                    void act(() => api.cancelBooking(houseId, booking.id), "Запись отменена.")
                  }
                >
                  Отменить запись
                </Button>
              </li>
            ))}
          </ul>
        )}
        {data.slots.length ? (
          <form
            className="report-form"
            onSubmit={(event) => {
              event.preventDefault();
              void act(() => api.book(houseId, slot, topic.trim()), "Вы записаны. Накануне бот напомнит в личных сообщениях.");
            }}
          >
            <label>
              Время приёма
              <select value={slot} required onChange={(event) => setSlot(event.target.value)}>
                <option value="">Выберите время</option>
                {data.slots.map((item) => (
                  <option key={item.id} value={item.id} disabled={item.free === 0 || Boolean(item.my_booking_id)}>
                    {formatDate(item.starts_at)} · {item.free ? `свободно мест: ${item.free}` : "мест нет"}
                    {item.my_booking_id ? " · вы записаны" : ""}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Тема
              <textarea
                value={topic}
                required
                minLength={3}
                maxLength={300}
                rows={3}
                onChange={(event) => setTopic(event.target.value)}
                placeholder="Например: перерасчёт за отопление"
              />
            </label>
            <Button type="submit" disabled={busy || !slot || topic.trim().length < 3}>
              Записаться
            </Button>
          </form>
        ) : (
          <p className="muted">Свободного времени приёма пока нет. Контакты УК — в разделе «Мой дом».</p>
        )}
        {message && (
          <p role="status" className="muted">
            {message}
          </p>
        )}
      </Panel>
    </>
  );
}
