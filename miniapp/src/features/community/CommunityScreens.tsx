import { type FormEvent, type ReactNode, useCallback, useEffect, useId, useRef, useState } from "react";
import { ApiProblem, problemStatus, retryable } from "../../shared/api/client";
import type {
  ActivityItem,
  AnnouncementItem,
  CommunityApi,
  HouseOverview,
  PollView,
  ProposalView,
  VerifiedSource,
} from "../../shared/api/community";
import { PAGE_SIZE } from "../../shared/api/community";
import { useResource, POLL_LIST_MS } from "../../shared/api/useResource";
import { maxBridge, safeUrl } from "../../shared/max/bridge";
import { Button } from "../../shared/ui/Button";
import { countLabel, formatDay, formatWhen, sentence } from "../../shared/ui/format";
import { IconExternal } from "../../shared/ui/icons";
import { ConfirmDialog, InfoRow, Notice, StatePanel, StatusTag } from "../../shared/ui/semantic";
import { SourceDisclosure } from "../../shared/ui/SourceLink";

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

/** Ссылка внутри приложения: без перезагрузки, с обычным открытием в новой вкладке. */
export function AppLink({ href, navigate, className, children }: { href: string; navigate: (href: string) => void; className?: string; children: ReactNode }) {
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

/** Источник сведения — одной строкой, полностью по раскрытию (дата проверки, ссылка). */
function Source({ source }: { source: VerifiedSource }) {
  return <SourceDisclosure url={source.url} title={source.title} verified={formatDay(source.verified_at)} />;
}

/**
 * Внешний сервис: в списке сервисов — строка во всю ширину со значком
 * внешнего перехода справа, в контактах (`inline`) — обычная текстовая ссылка.
 */
function ServiceLink({ href, inline = false, children }: { href: string; inline?: boolean; children: ReactNode }) {
  const url = safeUrl(href);
  if (!url) return <span className={inline ? undefined : "ds-service-name"}>{children}</span>;
  return (
    <a
      className={inline ? "ds-text-link" : "ds-service-name ds-service-link"}
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      onClick={(event) => {
        if (maxBridge.openLink(url)) event.preventDefault();
      }}
    >
      <span className="ds-service-link-text">{children}</span>
      {inline ? <span aria-hidden="true">&nbsp;↗</span> : <IconExternal />}{" "}
      <span className="ds-visually-hidden">(откроется отдельно)</span>
    </a>
  );
}

/** Телефон или почта: работают как tel:/mailto:, выглядят текстом, а не синей ссылкой. */
function ContactLink({ href, className, children }: { href: string; className?: string; children: ReactNode }) {
  return (
    <a className={["ds-text-link", className].filter(Boolean).join(" ")} href={href}>
      {children}
    </a>
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
            company.dispatcher_phone && (
              <ContactLink href={`tel:${company.dispatcher_phone}`} className="ds-phone">
                {company.dispatcher_phone}
              </ContactLink>
            ),
          ],
          [
            "Телефон",
            company.phone && (
              <ContactLink href={`tel:${company.phone}`} className="ds-phone">
                {company.phone}
              </ContactLink>
            ),
          ],
          ["Почта", company.email && <ContactLink href={`mailto:${company.email}`}>{company.email}</ContactLink>],
          ["Часы работы", company.office_hours],
          ["Часы приёма", company.reception_hours],
          ["Адрес офиса", company.office_address],
          [
            "Сайт",
            company.website && (
              <ServiceLink href={company.website} inline>
                {company.website}
              </ServiceLink>
            ),
          ],
        ] as [string, ReactNode][]
      ).filter(([, value]) => Boolean(value))
    : [];
  const companyUpdated = formatDay(company?.updated_at);
  const factsUpdated = formatDay(house.facts_updated_at);
  const channels = house.channels ?? [];
  const references = house.reference_links ?? [];
  const privacy = `${window.location.origin}/privacy`;
  return (
    <>
      <div className="ds-columns">
        <div>
          <EmergencyCard
            steps={house.accident_steps ?? []}
            emergency={house.emergency ?? []}
            dispatcher={company?.dispatcher_phone ?? null}
          />
          <section className="ds-house-group" aria-labelledby="company-title">
            <h2 id="company-title">Контакты управляющей компании</h2>
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
                      {sentence(`По данным управляющей компании${companyUpdated ? `, обновлено ${companyUpdated}` : ""}`)} ДомСигнал эти
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
          <section className="ds-house-group" aria-labelledby="house-title">
            <h2 id="house-title">Дом и домовой чат</h2>
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
            <AppLink className="ds-link-row" href={links.view("works", { house: houseId })} navigate={links.navigate}>
              Что сделано в доме за последние месяцы
            </AppLink>
          </section>
        </div>
        <div>
          <section className="ds-house-group" aria-labelledby="channels-title">
            <h2 id="channels-title">Официальные сервисы региона</h2>
            {channels.length ? (
              <ul className="ds-service-list">
                {channels.map((channel) => (
                  <li key={channel.id}>
                    {channel.url ? (
                      <ServiceLink href={channel.url}>{channel.label}</ServiceLink>
                    ) : (
                      <span className="ds-service-name">{channel.label}</span>
                    )}
                    {channel.phone && (
                      <ContactLink href={`tel:${channel.phone}`} className="ds-phone ds-service-phone">
                        {channel.phone}
                      </ContactLink>
                    )}
                    <Source source={channel.source} />
                  </li>
                ))}
              </ul>
            ) : (
              <p className="ds-subtle">Проверенных сервисов для региона дома пока нет в справочнике.</p>
            )}
          </section>
          {references.length > 0 && (
            <section className="ds-house-group" aria-labelledby="references-title">
              <h2 id="references-title">Где посмотреть тарифы и капремонт</h2>
              <p className="ds-subtle">Официальные страницы региона. Цифры и сроки смотрите на них — ДомСигнал их не пересказывает.</p>
              <ul className="ds-service-list">
                {references.map((link) => (
                  <li key={link.url}>
                    <ServiceLink href={link.url}>{link.label}</ServiceLink>
                    <Source source={link.source} />
                  </li>
                ))}
              </ul>
            </section>
          )}
          <HouseCouncil api={api} houseId={houseId} links={links} />
        </div>
      </div>
      <p className="ds-subtle">
        <a
          className="ds-text-link"
          href={privacy}
          target="_blank"
          rel="noopener noreferrer"
          onClick={(event) => {
            if (maxBridge.openLink(privacy)) event.preventDefault();
          }}
        >
          Политика данных
        </a>{" "}
        — что бот читает и хранит, как отключить чтение чата.
      </p>
    </>
  );
}

type Step = NonNullable<HouseOverview["accident_steps"]>[number];
type Emergency = NonNullable<HouseOverview["emergency"]>[number];

/**
 * «Если авария» — одна карточка: сначала звонок (каждый номер — одна кнопка,
 * 112 не повторяется), затем пункты памятки, затем источники одной строкой.
 * Номер в тексте памятки — обычный текст: звонок уже есть кнопкой выше.
 * Пункт экстренной службы, который повторяет шаг памятки с тем же номером,
 * не выводит заголовок второй раз — только свои пояснения.
 */
function EmergencyCard({ steps, emergency, dispatcher }: { steps: Step[]; emergency: Emergency[]; dispatcher: string | null }) {
  if (!steps.length && !emergency.length) return null;
  const calls: { phone: string; caption?: string }[] = [];
  const addCall = (phone: string | null | undefined, caption?: string) => {
    if (phone && !calls.some((call) => call.phone === phone)) calls.push({ phone, caption });
  };
  const stepPhones = new Set(steps.map((step) => step.phone).filter(Boolean));
  for (const step of steps) addCall(step.phone);
  for (const item of emergency) addCall(item.phone, stepPhones.has(item.phone ?? "") ? undefined : item.title);
  if (calls.length) addCall(dispatcher, "Аварийно-диспетчерская служба УК");
  const lines: ReactNode[] = [];
  for (const step of steps)
    lines.push(
      <li key={`step-${step.text}`}>
        <p>{step.text}</p>
      </li>,
    );
  for (const item of emergency) {
    const repeated = Boolean(item.phone && stepPhones.has(item.phone));
    if (!repeated)
      lines.push(
        <li key={`title-${item.title}`}>
          <p className="ds-strong">{item.title}</p>
        </li>,
      );
    for (const line of item.lines ?? [])
      lines.push(
        <li key={`line-${item.title}-${line}`}>
          <p>{line}</p>
        </li>,
      );
  }
  const sources: VerifiedSource[] = [];
  for (const source of [...steps.map((step) => step.source), ...emergency.map((item) => item.source)])
    if (source && !sources.some((known) => known.title === source.title && known.url === source.url)) sources.push(source);
  const [first, ...other] = calls;
  return (
    <section className="ds-safety" id="emergency" aria-labelledby="emergency-title">
      <h2 id="emergency-title">Если авария</h2>
      {first && (
        <div className="ds-calls">
          <a className="ds-call" href={`tel:${first.phone}`}>
            Позвонить {first.phone}
          </a>
          {other.map((call) => (
            <a key={call.phone} className="ds-call-secondary" href={`tel:${call.phone}`}>
              {call.phone}
              {call.caption && <small>{call.caption}</small>}
            </a>
          ))}
        </div>
      )}
      <ul className="ds-bullets ds-safety-lines">{lines}</ul>
      {sources.length > 0 && (
        <div>
          {sources.map((source) => (
            <Source key={`${source.title}-${source.url}`} source={source} />
          ))}
        </div>
      )}
    </section>
  );
}

// ------------------------------------------- совет дома и «Предложить вопрос» (D4)

const proposalLabels: Record<ProposalView["status"], string> = {
  new: "Ждёт рассмотрения",
  converted: "Вынесено на опрос",
};
const SERVICE_RULE = "Только сервисные сообщения для жителей. Реклама запрещена.";
const POLL_NOTE = "Предварительный опрос. Не является решением общего собрания собственников.";
const NOT_MEMBER = "Публиковать от имени совета могут только члены совета дома.";
const PUBLISHED = "Опубликовано: сообщение уйдёт в чат дома и в ленту «Объявления».";

/**
 * Ошибка формы. Правило сервиса при 422 уже сказано по-русски («Можно
 * предложить не больше 3 тем…») — показать его как есть; ошибка схемы —
 * назвать поля по словарю; отказ в доступе — словами `denied`.
 */
function formError(error: unknown, fields: Record<string, string>, denied: string): string {
  if (error instanceof ApiProblem) {
    const { problem } = error;
    if (problem.code === "validation_error") {
      const errors = problem.field_errors ?? [];
      const told = errors.map((item) => item.message).filter((message) => /[а-яё]/i.test(message ?? ""));
      if (told.length) return [...new Set(told)].join(" ");
      const named = errors.map((item) => fields[item.field.split(".")[1] ?? item.field]).filter(Boolean);
      return named.length ? `Проверьте: ${[...new Set(named)].join("; ")}.` : "Проверьте заполнение полей формы.";
    }
    if (problem.status === 403) return denied;
    // «Предложение уже вынесено на опрос», «Предложение не найдено» — сервер уже сказал словами.
    if ([404, 409].includes(problem.status) && /[а-яё]/i.test(problem.detail)) return problem.detail;
    if (problem.status === 429) return "Слишком много запросов. Подождите минуту.";
  }
  return "Не получилось. Проверьте соединение и попробуйте ещё раз.";
}

/** Ключ идемпотентности живёт, пока повторяется тот же запрос: повтор после сбоя не создаст второе. */
function useRetryKey() {
  const last = useRef<{ body: string; key: string } | null>(null);
  const keyFor = useCallback((body: unknown) => {
    const text = JSON.stringify(body);
    if (last.current?.body !== text) last.current = { body: text, key: crypto.randomUUID() };
    return last.current.key;
  }, []);
  const reset = useCallback(() => {
    last.current = null;
  }, []);
  return { keyFor, reset };
}

function localInput(date: Date) {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

type Note = { text: string; error: boolean } | null;
function FormNote({ note }: { note: Note }) {
  if (!note) return null;
  return (
    <p role={note.error ? "alert" : "status"} className="ds-subtle">
      {note.text}
    </p>
  );
}

function ProposalItem({
  item,
  houseId,
  links,
  children,
}: {
  item: ProposalView;
  houseId: string;
  links: CommunityLinks;
  children?: ReactNode;
}) {
  const pollId = item.poll_id;
  return (
    <li>
      <p className="full-text">{item.text}</p>
      <div className="ds-actions">
        <StatusTag entry={{ label: proposalLabels[item.status], tone: item.status === "converted" ? "success" : "neutral" }} />
        <time className="ds-meta" dateTime={item.created_at}>
          {formatDay(item.created_at)}
        </time>
      </div>
      {item.status === "converted" && pollId && (
        <Button
          small
          variant="secondary"
          onClick={() => links.navigate(links.view("poll", { house: houseId, poll: pollId }))}
        >
          Открыть опрос
        </Button>
      )}
      {children}
    </li>
  );
}

/** «Предложить вопрос» для каждого жителя и «Совет дома» для его членов. */
function HouseCouncil({ api, houseId, links }: { api: CommunityApi; houseId: string; links: CommunityLinks }) {
  const load = useCallback((signal: AbortSignal) => api.council(houseId, signal), [api, houseId]);
  const resource = useResource(`council:${houseId}`, load);
  if (resource.error && !resource.data) {
    // Доступ к дому уже объяснил экран; без права предлагать темы панели просто нет.
    if ([401, 403, 404].includes(problemStatus(resource.error) ?? 0)) return null;
    return (
      <StatePanel
        title="Не удалось загрузить предложения"
        detail="Проверьте соединение и попробуйте ещё раз."
        action={retryable(resource.error) ? "Попробовать снова" : undefined}
        onAction={resource.refresh}
      />
    );
  }
  if (!resource.data) return <StatePanel title="Загрузка предложений" loading />;
  const proposals = resource.data.proposals ?? [];
  return (
    <>
      <ProposePanel
        api={api}
        houseId={houseId}
        links={links}
        mine={proposals.filter((item) => item.mine)}
        onChanged={resource.refresh}
      />
      {resource.data.is_member && (
        <CouncilPanel
          api={api}
          houseId={houseId}
          links={links}
          proposals={proposals}
          onChanged={resource.refresh}
        />
      )}
    </>
  );
}

function ProposePanel({
  api,
  houseId,
  links,
  mine,
  onChanged,
}: {
  api: CommunityApi;
  houseId: string;
  links: CommunityLinks;
  mine: ProposalView[];
  onChanged: () => void;
}) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<Note>(null);
  // Только что добавленная тема видна сразу, не дожидаясь обновления списка.
  const [created, setCreated] = useState<ProposalView[]>([]);
  const retry = useRetryKey();
  const shown = [...created.filter((item) => !mine.some((known) => known.id === item.id)), ...mine];
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = text.trim();
    setBusy(true);
    setNote(null);
    try {
      const item = await api.propose(houseId, value, retry.keyFor(value));
      retry.reset();
      setCreated((list) => [item, ...list]);
      setText("");
      setNote({ text: "Тема добавлена. Её статус — в списке «Мои предложения».", error: false });
      onChanged();
    } catch (error) {
      setNote({
        text: formError(error, { text: "текст темы — от 3 до 1000 символов" }, "Предлагать темы могут жители дома."),
        error: true,
      });
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="ds-section">
      <h2>Предложить вопрос</h2>
      <p>Тему увидят совет дома и управляющая компания; её можно вынести на опрос.</p>
      <form className="ds-form" onSubmit={(event) => void submit(event)}>
        <label className="ds-field">
          Тема или вопрос
          <textarea
            value={text}
            required
            minLength={3}
            maxLength={1000}
            rows={3}
            disabled={busy}
            onChange={(event) => setText(event.target.value)}
            placeholder="Например: поставить велопарковку у второго подъезда"
          />
        </label>
        <Button
          type="submit"
          variant="primary"
          disabled={busy || text.trim().length < 3}
          reason={!busy && text.trim().length < 3 ? "Напишите тему — хотя бы 3 символа." : null}
        >
          Предложить
        </Button>
        <FormNote note={note} />
      </form>
      {shown.length > 0 && (
        <>
          <h3>Мои предложения</h3>
          <ul className="ds-bullets" aria-label="Мои предложения">
            {shown.map((item) => (
              <ProposalItem key={item.id} item={item} houseId={houseId} links={links} />
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

type PollForm = {
  question: string;
  options: string[];
  multiple: boolean;
  closes: string;
  proposalId: string | null;
  service: boolean;
};
const emptyPoll = (): PollForm => ({
  question: "",
  options: ["", ""],
  multiple: false,
  closes: localInput(new Date(Date.now() + 3 * 86400000)),
  proposalId: null,
  service: false,
});
const ANNOUNCEMENT_FIELDS = { title: "заголовок — от 3 до 200 символов", body: "текст — до 3000 символов" };
const POLL_FIELDS = { poll: "вопрос, варианты (без повторов, до 100 символов) и срок опроса", proposal_id: "предложение" };

function CouncilPanel({
  api,
  houseId,
  links,
  proposals,
  onChanged,
}: {
  api: CommunityApi;
  houseId: string;
  links: CommunityLinks;
  proposals: ProposalView[];
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [announcement, setAnnouncement] = useState({ title: "", body: "", service: false });
  const [announcementNote, setAnnouncementNote] = useState<Note>(null);
  const [poll, setPoll] = useState<PollForm>(emptyPoll);
  const [pollNote, setPollNote] = useState<Note>(null);
  const [publishedPoll, setPublishedPoll] = useState<string | null>(null);
  const announcementKey = useRetryKey();
  const pollKey = useRetryKey();
  const question = useRef<HTMLInputElement>(null);
  const setPollField = (patch: Partial<PollForm>) => setPoll((value) => ({ ...value, ...patch }));
  useEffect(() => {
    if (poll.proposalId) question.current?.focus();
  }, [poll.proposalId]);

  async function publishAnnouncement(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const payload = { title: announcement.title.trim(), body: announcement.body.trim(), service_only: true as const };
    setBusy(true);
    setAnnouncementNote(null);
    try {
      await api.councilAnnouncement(houseId, payload, announcementKey.keyFor(payload));
      announcementKey.reset();
      setAnnouncement({ title: "", body: "", service: false });
      setAnnouncementNote({ text: PUBLISHED, error: false });
      onChanged();
    } catch (error) {
      setAnnouncementNote({ text: formError(error, ANNOUNCEMENT_FIELDS, NOT_MEMBER), error: true });
      if (problemStatus(error) === 403) onChanged();
    } finally {
      setBusy(false);
    }
  }

  async function publishPoll(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const closes = new Date(poll.closes);
    setPollNote(null);
    setPublishedPoll(null);
    if (!Number.isFinite(closes.getTime())) {
      setPollNote({ text: "Укажите дату и время, до которых идёт голосование.", error: true });
      return;
    }
    const payload = {
      poll: {
        question: poll.question.trim(),
        options: poll.options.map((option) => option.trim()),
        multiple: poll.multiple,
        closes_at: closes.toISOString(),
      },
      proposal_id: poll.proposalId,
      service_only: true as const,
    };
    setBusy(true);
    try {
      const result = await api.councilPoll(houseId, payload, pollKey.keyFor(payload));
      pollKey.reset();
      setPoll(emptyPoll());
      setPublishedPoll(result.poll_id ?? null);
      setPollNote({ text: PUBLISHED, error: false });
      onChanged();
    } catch (error) {
      setPollNote({ text: formError(error, POLL_FIELDS, NOT_MEMBER), error: true });
      if (problemStatus(error) === 403 || problemStatus(error) === 404) onChanged();
    } finally {
      setBusy(false);
    }
  }

  const source = poll.proposalId ? proposals.find((item) => item.id === poll.proposalId) : undefined;
  const pollReady =
    poll.service && poll.question.trim().length >= 3 && poll.options.every((option) => option.trim()) && Boolean(poll.closes);
  return (
    <section className="ds-section">
      <h2>Совет дома</h2>
      <p>
        Вы в совете дома. Объявления и опросы совета подписаны «Сообщение от совета дома» и появляются в ленте
        «Объявления». В чат дома они уходят, если это разрешено настройками чата; в тихие часы — после их окончания.
      </p>
      <p className="honesty-inline">{SERVICE_RULE}</p>

      <form className="ds-form" onSubmit={(event) => void publishAnnouncement(event)}>
        <h3>Объявление от совета</h3>
        <label className="ds-field">
          Заголовок
          <input
            value={announcement.title}
            required
            minLength={3}
            maxLength={200}
            disabled={busy}
            onChange={(event) => setAnnouncement({ ...announcement, title: event.target.value })}
          />
        </label>
        <label className="ds-field">
          Текст
          <textarea
            value={announcement.body}
            required
            maxLength={3000}
            rows={4}
            disabled={busy}
            onChange={(event) => setAnnouncement({ ...announcement, body: event.target.value })}
          />
        </label>
        <label className="poll-option">
          <input
            type="checkbox"
            required
            checked={announcement.service}
            disabled={busy}
            onChange={(event) => setAnnouncement({ ...announcement, service: event.target.checked })}
          />
          <span>Это сервисное сообщение, не реклама</span>
        </label>
        <Button
          type="submit"
          variant="primary"
          disabled={
            busy || !announcement.service || announcement.title.trim().length < 3 || !announcement.body.trim()
          }
        >
          Опубликовать
        </Button>
        <FormNote note={announcementNote} />
      </form>

      <form className="ds-form" onSubmit={(event) => void publishPoll(event)}>
        <h3>Опрос от совета</h3>
        {poll.proposalId && (
          <div className="honesty-inline">
            <p>
              Опрос по предложению жителя{source ? `: «${source.text}»` : ""}. После публикации предложение получит
              статус «Вынесено на опрос».
            </p>
            <Button
              type="button"
              small
              variant="secondary"
              disabled={busy}
              onClick={() => setPollField({ proposalId: null })}
            >
              Не связывать с предложением
            </Button>
          </div>
        )}
        <label className="ds-field">
          Вопрос
          <input
            ref={question}
            value={poll.question}
            required
            minLength={3}
            maxLength={300}
            disabled={busy}
            onChange={(event) => setPollField({ question: event.target.value })}
          />
        </label>
        {poll.options.map((option, index) => (
          <div key={index} className="ds-actions">
            <label className="ds-field">
              Вариант {index + 1}
              <input
                value={option}
                required
                maxLength={100}
                disabled={busy}
                onChange={(event) =>
                  setPollField({ options: poll.options.map((item, i) => (i === index ? event.target.value : item)) })
                }
              />
            </label>
            {poll.options.length > 2 && (
              <Button
                type="button"
                small
                variant="secondary"
                disabled={busy}
                onClick={() => setPollField({ options: poll.options.filter((_, i) => i !== index) })}
              >
                Убрать вариант {index + 1}
              </Button>
            )}
          </div>
        ))}
        {poll.options.length < 10 && (
          <Button
            type="button"
            small
            variant="secondary"
            disabled={busy}
            onClick={() => setPollField({ options: [...poll.options, ""] })}
          >
            Добавить вариант
          </Button>
        )}
        <label className="poll-option">
          <input
            type="checkbox"
            checked={poll.multiple}
            disabled={busy}
            onChange={(event) => setPollField({ multiple: event.target.checked })}
          />
          <span>Можно выбрать несколько</span>
        </label>
        <label className="ds-field">
          Голосование до
          <input
            type="datetime-local"
            value={poll.closes}
            required
            disabled={busy}
            onChange={(event) => setPollField({ closes: event.target.value })}
          />
        </label>
        <label className="poll-option">
          <input
            type="checkbox"
            required
            checked={poll.service}
            disabled={busy}
            onChange={(event) => setPollField({ service: event.target.checked })}
          />
          <span>Это сервисное сообщение, не реклама</span>
        </label>
        <p className="ds-subtle">{POLL_NOTE}</p>
        <Button type="submit" variant="primary" disabled={busy || !pollReady}>
          Опубликовать опрос
        </Button>
        <FormNote note={pollNote} />
        {publishedPoll && (
          <Button
            type="button"
            small
            variant="secondary"
            onClick={() => links.navigate(links.view("poll", { house: houseId, poll: publishedPoll }))}
          >
            Открыть опрос
          </Button>
        )}
      </form>

      <h3>Предложения жителей</h3>
      {proposals.length ? (
        <ul className="ds-bullets" aria-label="Предложения жителей">
          {proposals.map((item) => (
            <ProposalItem key={item.id} item={item} houseId={houseId} links={links}>
              {item.status === "new" && (
                <Button
                  small
                  variant="secondary"
                  disabled={busy}
                  aria-label={`Сделать опросом: ${item.text.slice(0, 80)}`}
                  onClick={() => {
                    setPollNote(null);
                    setPublishedPoll(null);
                    setPollField({ question: item.text.slice(0, 300), proposalId: item.id });
                  }}
                >
                  Сделать опросом
                </Button>
              )}
            </ProposalItem>
          ))}
        </ul>
      ) : (
        <p className="ds-subtle">Жители пока ничего не предложили.</p>
      )}
    </section>
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
  const resource = useResource(`mine:${offset}`, load, { poll: POLL_LIST_MS });
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

/**
 * Главный экран: обращения жителя в этом доме, которых нет в списке проблем
 * выше (черновики, «куда обратиться»), и переход ко всем. Свои проблемы
 * доски отмечены прямо в строках — второй раз их карточки не повторяются,
 * а без таких обращений блок не показывается (доска ставит одну ссылку).
 */
export function RecentActivity({
  houseId,
  links,
  items,
  onBoard = 0,
  error,
  onRetry,
}: {
  houseId: string;
  links: CommunityLinks;
  /** Обращения жителя в этом доме, которых нет на текущей странице доски. */
  items: ActivityItem[];
  /** Сколько обращений жителя уже отмечено в списке проблем выше. */
  onBoard?: number;
  error?: unknown;
  onRetry: () => void;
}) {
  const titleId = useId();
  if (error)
    return (
      <section className="ds-group" aria-labelledby={titleId}>
        <h2 id={titleId}>Ваши обращения</h2>
        <p className="ds-subtle">Не удалось загрузить ваши обращения.</p>
        {retryable(error) && (
          <div>
            <Button small onClick={onRetry}>
              Повторить<span className="ds-visually-hidden"> загрузку обращений</span>
            </Button>
          </div>
        )}
      </section>
    );
  if (!items.length) return null;
  return (
    <section className="ds-group" aria-labelledby={titleId}>
      <div className="ds-group-head">
        <h2 id={titleId}>{onBoard ? "Другие ваши обращения" : "Ваши обращения"}</h2>
        <AppLink className="ds-action-link" href={links.view("mine", { house: houseId })} navigate={links.navigate}>
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
