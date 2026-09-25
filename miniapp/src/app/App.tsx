import { type ReactNode, useCallback, useEffect, useRef, useState } from "react";
import {
  ApiProblem,
  apiClient,
  type AppealDraftView,
  type Capabilities,
  type DomSignalApi,
  type IncidentDetail,
  type IncidentList,
  type Me,
  type NotificationLaunch,
  type OpenHouse,
  type RouteOutcomeView,
  problemStatus,
  retryable,
} from "../shared/api/client";
import { useResource } from "../shared/api/useResource";
import { LAUNCH_REF, maxBridge } from "../shared/max/bridge";
import { Button } from "../shared/ui/Button";
import { countLabel, formatWhen } from "../shared/ui/format";
import {
  BackLink,
  DemoBadge,
  InfoRow,
  NextAction,
  Notice,
  PageHeader,
  SourceChip,
  StatePanel,
  StatusBadge,
  Timeline,
} from "../shared/ui/semantic";
import { IncidentRow, placeText } from "../features/incidents/IncidentCard";
import { type FlowTarget, type ReportDraft, ReportFlow } from "../features/incidents/ReportFlow";
import { AppealDraftScreen } from "../features/appeals/AppealDraftScreen";
import { RouteCard } from "../features/routing/RouteCard";
import { ResidentWorkProgress } from "../features/tickets/ResidentWorkProgress";
import { NoHouse } from "../features/houses/NoHouse";
import {
  AnnouncementsScreen,
  type CommunityLinks,
  type CommunityView,
  MyActivityScreen,
  MyHouseScreen,
  PollScreen,
  ReceptionScreen,
  RecentActivity,
  WorksScreen,
} from "../features/community/CommunityScreens";
import { type CommunityApi, communityApi } from "../shared/api/community";
import { categoryLabel } from "../features/incidents/presentation";

type House = Me["houses"][number];
type Loaded = {
  notificationLaunch?: NotificationLaunch;
  capabilities: Capabilities;
  me: Me;
  house?: House;
  incidents?: IncidentList;
  incident?: IncidentDetail;
  card?: RouteOutcomeView;
  draft?: AppealDraftView;
  report?: boolean;
  unavailable?: boolean;
  /** Дома с открытым доступом — для жителя, у которого домов ещё нет. */
  openHouses?: OpenHouse[];
  openHousesFailed?: boolean;
  /** Раздел сообщества D3: «Мой дом», объявления, опрос, работы, обращения, приём. */
  view?: CommunityView;
};

const VIEWS: CommunityView[] = ["home", "news", "poll", "works", "mine", "reception"];
/** Разделы верхнего уровня — вкладки; остальное — вложенные экраны с «Назад». */
type Section = "board" | "mine" | "news" | "home";
const SECTIONS: [Section, string][] = [
  ["board", "Проблемы"],
  ["mine", "Мои обращения"],
  ["news", "Объявления"],
  ["home", "Мой дом"],
];
const VIEW_TITLES: Record<CommunityView, string> = {
  home: "Мой дом",
  news: "Объявления",
  poll: "Опрос",
  works: "Что сделано в доме",
  mine: "Мои обращения",
  reception: "Запись на приём",
};
const PROBLEMS = ["проблема", "проблемы", "проблем"] as const;

type Target = FlowTarget & {
  house?: string;
  offset?: number;
  view?: CommunityView;
  poll?: string;
  report?: boolean;
};
function routeUrl(target: Target = {}) {
  // Never propagate MAX launch/auth parameters into DOM links or copied navigation URLs.
  const url = new URL(window.location.pathname, window.location.origin);
  const testActor = new URLSearchParams(window.location.search).get("test_actor");
  if (testActor && /^[a-z0-9-]{1,40}$/.test(testActor)) url.searchParams.set("test_actor", testActor);
  if (target.house) url.searchParams.set("house", target.house);
  if (target.incident) url.searchParams.set("incident", target.incident);
  if (target.card) url.searchParams.set("card", target.card);
  if (target.draft) url.searchParams.set("draft", target.draft);
  if (target.offset) url.searchParams.set("offset", String(target.offset));
  if (target.view) url.searchParams.set("view", target.view);
  if (target.poll) url.searchParams.set("poll", target.poll);
  if (target.report) url.searchParams.set("report", "1");
  return url.pathname + url.search;
}

/** Глубина истории внутри мини-приложения: «Назад» возвращает, а не уводит на доску. */
function depth(): number {
  const value = (window.history.state as { dsDepth?: unknown } | null)?.dsDepth;
  return typeof value === "number" ? value : 0;
}

function denied(): never {
  throw new ApiProblem({
    status: 403,
    type: "about:blank",
    code: "house_access_denied",
    title: "",
    detail: "",
    trace_id: "",
    retryable: false,
  });
}

export function App({
  client = apiClient,
  community,
}: {
  client?: DomSignalApi;
  /** Запросы D3; по умолчанию — поверх того же вошедшего клиента. */
  community?: CommunityApi;
}) {
  const [communityClient] = useState<CommunityApi>(
    () =>
      community ??
      communityApi("request" in client ? (client as unknown as Parameters<typeof communityApi>[0]) : apiClient),
  );
  const [location, setLocation] = useState(() => window.location.href);
  const [launchPending, setLaunchPending] = useState(true);
  const [launchNotice, setLaunchNotice] = useState(false);
  const [launchAttempt, setLaunchAttempt] = useState<string | null>(null);
  // Текст формы живёт в памяти, пока приложение открыто (не в хранилище браузера).
  const reportDrafts = useRef(new Map<string, ReportDraft>());
  const route = new URL(location);
  const houseId = route.searchParams.get("house");
  const incidentId = route.searchParams.get("incident");
  const cardId = route.searchParams.get("card");
  const draftId = route.searchParams.get("draft");
  const rawView = route.searchParams.get("view");
  const view = VIEWS.find((item) => item === rawView);
  const pollId = route.searchParams.get("poll");
  const reportParam = route.searchParams.get("report") === "1";
  const detail = Boolean(incidentId || cardId || draftId || view || reportParam);
  const offset = Math.max(0, Math.min(1000000, Number.parseInt(route.searchParams.get("offset") ?? "0") || 0));
  const key = JSON.stringify([houseId, incidentId, cardId, draftId, offset, launchPending, view, pollId, reportParam]);

  const navigate = useCallback((href: string, options: { replace?: boolean } = {}) => {
    if (options.replace) window.history.replaceState({ dsDepth: depth() }, "", href);
    else window.history.pushState({ dsDepth: depth() + 1 }, "", href);
    setLocation(window.location.href);
    setLaunchPending(false);
    setLaunchNotice(false);
    setLaunchAttempt(null);
    window.scrollTo?.(0, 0);
  }, []);
  useEffect(() => {
    const onBack = () => setLocation(window.location.href);
    window.addEventListener("popstate", onBack);
    return () => window.removeEventListener("popstate", onBack);
  }, []);

  const load = useCallback(
    async (signal: AbortSignal): Promise<Loaded> => {
      const capabilities = await client.capabilities(signal);
      await client.authenticate(capabilities, signal);
      const me = await client.me(signal);
      const testRef =
        capabilities.environment !== "production" && capabilities.features.test_auth
          ? new URLSearchParams(window.location.search).get("test_start_param")
          : null;
      const startRef = launchPending ? (maxBridge.startParam ?? testRef) : null;
      const launchRef = startRef && LAUNCH_REF.test(startRef) ? startRef : null;
      if (launchRef && capabilities.features.miniapp) {
        const target = await client.notificationLaunch(launchRef, signal);
        const home = me.houses.find((house) => house.id === target.house_id);
        // Пост объявления или опроса и личная рассылка ведут в раздел дома (D3).
        if (target.kind === "poll" || target.kind === "announcements")
          return {
            capabilities,
            me,
            notificationLaunch: target,
            house: home,
            view: target.kind === "poll" ? "poll" : "news",
          };
        // Карточка «куда обратиться» ведёт на свой экран: у внешнего адресата заявки нет.
        if (target.kind === "route_card" && target.route_outcome_id) {
          if (!capabilities.features.routes) return { capabilities, me, notificationLaunch: target, unavailable: true };
          const card = await client.routeOutcome(target.route_outcome_id, signal);
          return { capabilities, me, card, notificationLaunch: target, house: home };
        }
        if (target.incident_id && capabilities.features.incident_detail) {
          const incident = await client.incident(target.incident_id, signal, target.house_id);
          return { capabilities, me, incident, notificationLaunch: target, house: home };
        }
        return { capabilities, me, notificationLaunch: target, unavailable: true };
      }
      // Дом из адреса или, если его нет, первый доступный: при нескольких домах
      // переключатель стоит в шапке, а адрес виден перед отправкой сообщения.
      const chosen = houseId !== null ? me.houses.find((item) => item.id === houseId) : me.houses[0];
      if (houseId !== null && !chosen && !incidentId && !cardId && !draftId) denied();
      if (view && capabilities.features.miniapp) {
        // «Мои обращения» и опрос не требуют выбранного дома; остальные разделы — дома.
        if (!chosen && !["mine", "poll"].includes(view)) return { capabilities, me };
        return { capabilities, me, house: chosen, view };
      }
      if (reportParam && capabilities.features.miniapp) {
        if (!chosen) return { capabilities, me };
        if (!capabilities.features.report_create) return { capabilities, me, unavailable: true };
        return { capabilities, me, house: chosen, report: true };
      }
      if (
        !capabilities.features.miniapp ||
        (cardId && !capabilities.features.routes) ||
        (draftId && !capabilities.features.appeals) ||
        !(detail ? capabilities.features.incident_detail || cardId || draftId : capabilities.features.incident_board)
      ) {
        return { capabilities, me, unavailable: true };
      }
      if (cardId) {
        const card = await client.routeOutcome(cardId, signal);
        return { capabilities, me, card, house: me.houses.find((house) => house.id === card.house_id) };
      }
      if (draftId) {
        const draft = await client.appealDraft(draftId, signal);
        return { capabilities, me, draft, house: me.houses.find((house) => house.id === draft.house_id) };
      }
      if (incidentId) {
        const incident = await client.incident(incidentId, signal, houseId ?? undefined);
        return { capabilities, me, incident, house: me.houses.find((house) => house.id === incident.house_id) };
      }
      if (!chosen) {
        // Домов нет — показать, как в дом попасть, и открытые дома, если они есть.
        try {
          return { capabilities, me, openHouses: await client.openHouses(signal) };
        } catch (reason) {
          if (signal.aborted) throw reason;
          return { capabilities, me, openHouses: [], openHousesFailed: true };
        }
      }
      const incidents = await client.incidents(chosen.id, signal, offset);
      return { capabilities, me, house: chosen, incidents };
    },
    [client, houseId, incidentId, cardId, draftId, detail, offset, launchPending, view, reportParam],
  );
  const resource = useResource(key, load);
  const data = resource.data;
  useEffect(() => {
    const target = data?.notificationLaunch;
    if (!target || !launchPending) return;
    setLaunchPending(false);
    setLaunchNotice(target.stale);
    setLaunchAttempt(target.work_attempt_id);
    window.history.replaceState(
      { dsDepth: 0 },
      "",
      routeUrl(
        target.kind === "route_card"
          ? { house: target.house_id, card: target.route_outcome_id ?? undefined }
          : target.kind === "poll"
            ? { house: target.house_id, view: "poll", poll: target.poll_id ?? undefined }
            : target.kind === "announcements"
              ? { house: target.house_id, view: "news" }
              : { house: target.house_id, incident: target.incident_id ?? undefined },
      ),
    );
    setLocation(window.location.href);
  }, [data?.notificationLaunch, launchPending]);

  const currentHouse = data?.house?.id ?? data?.incident?.house_id ?? data?.card?.house_id ?? data?.draft?.house_id ?? houseId ?? undefined;
  /** Родитель экрана — куда ведёт «Назад», если внутри приложения истории нет (вход по ссылке). */
  const parent = useCallback((): string => {
    if (view === "poll") return routeUrl({ house: currentHouse, view: "news" });
    if (view === "reception" || view === "works") return routeUrl({ house: currentHouse, view: "home" });
    if (data?.draft) return routeUrl({ house: data.draft.house_id, card: data.draft.route_outcome_id });
    return routeUrl({ house: currentHouse });
  }, [view, currentHouse, data?.draft]);
  const back = useCallback(() => {
    if (depth() > 0) window.history.back();
    else navigate(parent(), { replace: true });
  }, [navigate, parent]);
  // Системная «Назад» MAX: видна везде, кроме главного экрана, и ведёт туда же.
  const isHome = !detail;
  useEffect(() => (isHome ? undefined : maxBridge.subscribeBack(back)), [isHome, back]);
  useEffect(() => {
    if (!(data || resource.error)) return;
    // Первый шаг формы сам ставит фокус в поле; остальные экраны — на заголовок.
    if (document.querySelector("[data-autofocus]")) return;
    document.getElementById("page-title")?.focus({ preventScroll: true });
  }, [key, Boolean(data), Boolean(resource.error)]);
  const rememberDraft = useCallback(
    (house: string) => (draft: ReportDraft | null) => {
      if (draft && (draft.text || draft.category)) reportDrafts.current.set(house, draft);
      else reportDrafts.current.delete(house);
    },
    [],
  );
  const onDraft = useCallback((draft: ReportDraft | null) => {
    if (currentHouse) rememberDraft(currentHouse)(draft);
  }, [currentHouse, rememberDraft]);

  const links: CommunityLinks = {
    board: (house) => routeUrl({ house }),
    view: (target, extra) => routeUrl({ view: target, house: extra?.house, poll: extra?.poll }),
    incident: (house, incident) => routeUrl({ house, incident }),
    card: (house, card) => routeUrl({ house, card }),
    draft: (house, draft) => routeUrl({ house, draft }),
    report: (house) => routeUrl({ house, report: true }),
    navigate,
  };

  const topbar = (showBack: boolean, house?: string) => (
    <div className="ds-topbar">
      <div className="ds-topbar-start">
        {showBack ? <BackLink onBack={back} /> : <span className="ds-brand">ДомСигнал</span>}
      </div>
      {house && view !== "home" && <EmergencyLink href={routeUrl({ house, view: "home" })} navigate={navigate} />}
    </div>
  );

  // Что грузим — одними словами для заголовка, загрузки и ошибки.
  const subject = view
    ? `раздел «${VIEW_TITLES[view]}»`
    : cardId
      ? "сведения, куда обратиться"
      : draftId
        ? "черновик обращения"
        : incidentId
          ? "проблему"
          : reportParam
            ? "форму сообщения"
            : "проблемы дома";
  const headerTitle = view
    ? VIEW_TITLES[view]
    : cardId
      ? "Куда обратиться"
      : draftId
        ? "Черновик обращения"
        : incidentId
          ? "Проблема дома"
          : reportParam
            ? "Что случилось?"
            : "Проблемы дома";
  if (!data)
    return (
      <main className="app-shell">
        {topbar(detail, houseId ?? undefined)}
        {resource.error ? (
          <ErrorPanel
            error={resource.error}
            subject={subject}
            onRetry={resource.refresh}
            back={
              detail || problemStatus(resource.error) === 403 ? (
                <Button onClick={() => navigate(routeUrl(), { replace: true })}>К выбору дома</Button>
              ) : undefined
            }
          />
        ) : (
          <>
            <PageHeader title={headerTitle} />
            <StatePanel title={`Загружаем ${subject}`} detail="Это займёт несколько секунд." loading />
          </>
        )}
      </main>
    );
  if (data.unavailable)
    return (
      <main className="app-shell">
        {topbar(detail, currentHouse)}
        <PageHeader title="Раздел пока недоступен" />
        <StatePanel
          title="Этот раздел сейчас выключен"
          detail="Его включает команда ДомСигнала. Попробуйте обновить позже."
          action="Обновить"
          onAction={resource.refresh}
          back={detail ? <Button onClick={() => navigate(routeUrl())}>К проблемам дома</Button> : undefined}
        />
      </main>
    );

  const houses = data.me.houses;
  const switcher = (house: House) =>
    houses.length > 1 ? (
      <label className="ds-house-switch">
        Дом
        <select
          value={house.id}
          onChange={(event) => navigate(routeUrl({ house: event.target.value, view: view && view !== "poll" ? view : undefined }))}
        >
          {houses.map((item) => (
            <option key={item.id} value={item.id}>
              {item.address}
            </option>
          ))}
        </select>
      </label>
    ) : (
      house.address
    );
  const refresh = <RefreshNotice resource={resource} />;

  // --------------------------------------------------------------- сообщество
  if (data.view && (data.house || ["mine", "poll"].includes(data.view))) {
    const home = data.house;
    const topLevel = ["mine", "news", "home"].includes(data.view);
    return (
      <main className="app-shell">
        {topbar(!topLevel, home?.id)}
        <PageHeader title={VIEW_TITLES[data.view]} subtitle={home && data.view !== "mine" ? switcher(home) : undefined}>
          {home?.is_demo && <DemoBadge />}
        </PageHeader>
        {topLevel && <SectionTabs house={home?.id} current={data.view as Section} navigate={navigate} />}
        {data.view === "home" && home && <MyHouseScreen api={communityClient} houseId={home.id} links={links} />}
        {data.view === "news" && home && <AnnouncementsScreen api={communityClient} houseId={home.id} links={links} />}
        {data.view === "works" && home && <WorksScreen api={communityClient} houseId={home.id} links={links} />}
        {data.view === "reception" && home && <ReceptionScreen api={communityClient} houseId={home.id} links={links} />}
        {data.view === "mine" && <MyActivityScreen api={communityClient} houseId={home?.id} links={links} />}
        {data.view === "poll" && pollId && (
          <PollScreen api={communityClient} pollId={pollId} houseId={home?.id} links={links} />
        )}
        {data.view === "poll" && !pollId && (
          <StatePanel title="Опрос не найден" detail="Вернитесь к объявлениям дома." />
        )}
        {import.meta.env.DEV && <Diagnostics />}
      </main>
    );
  }

  // --------------------------------------------------------------- нет дома
  if (!data.house && !data.incident && !data.card && !data.draft)
    return (
      <main className="app-shell">
        {topbar(false)}
        <PageHeader title="Как открыть свой дом" subtitle="ДомСигнал показывает проблемы вашего дома и помогает сообщить о новой." />
        <NoHouse
          client={client}
          houses={data.openHouses ?? []}
          loadError={Boolean(data.openHousesFailed)}
          busy={resource.loading}
          onRefresh={resource.refresh}
          onJoined={(id) => navigate(routeUrl({ house: id }))}
        />
      </main>
    );

  // --------------------------------------------------------- сообщить о проблеме
  if (data.report && data.house) {
    const house = data.house;
    return (
      <main className="app-shell">
        {topbar(true, house.id)}
        <ReportFlow
          key={house.id}
          houseId={house.id}
          houseAddress={house.address}
          client={client}
          draft={reportDrafts.current.get(house.id)}
          onDraft={onDraft}
          onOpen={(target) => navigate(routeUrl({ house: house.id, ...target }))}
          onCreated={() => undefined}
          onBoard={() => navigate(routeUrl({ house: house.id }))}
        />
      </main>
    );
  }

  const busy = resource.loading || Boolean(resource.error) || resource.stale;

  // ------------------------------------------------------ куда обратиться
  if (data.card) {
    const outcome = data.card;
    return (
      <main className="app-shell">
        {topbar(true, outcome.house_id)}
        <PageHeader title="Куда обратиться" subtitle={data.house?.address}>
          {data.house?.is_demo && <DemoBadge />}
        </PageHeader>
        {refresh}
        {outcome.directory_changed && (
          <Notice role="status">
            <p>Сведения обновились — показываем актуальные.</p>
          </Notice>
        )}
        <RouteCard
          card={outcome.action_card}
          busy={busy}
          demo={Boolean(data.house?.is_demo)}
          handlers={{
            prepare_appeal: () =>
              void (async () => {
                const created = outcome.appeal_draft_id
                  ? { id: outcome.appeal_draft_id }
                  : await client.createAppealDraft({ house_id: outcome.house_id, route_outcome_id: outcome.id });
                navigate(routeUrl({ house: outcome.house_id, draft: created.id }));
              })(),
          }}
          extra={
            outcome.incident_id ? (
              <Button stretched onClick={() => navigate(routeUrl({ house: outcome.house_id, incident: outcome.incident_id! }))}>
                Открыть проблему дома
              </Button>
            ) : undefined
          }
        />
        <p className="ds-meta">Карточка составлена по текущему справочнику ДомСигнала.</p>
        {import.meta.env.DEV && <Diagnostics />}
      </main>
    );
  }

  // --------------------------------------------------------- черновик обращения
  if (data.draft) {
    const draft = data.draft;
    return (
      <main className="app-shell">
        {topbar(true, draft.house_id)}
        <PageHeader title="Черновик обращения" subtitle={data.house?.address}>
          {data.house?.is_demo && <DemoBadge />}
        </PageHeader>
        {refresh}
        <AppealDraftScreen
          key={draft.id}
          draft={draft}
          client={client}
          // P6b: «данные могли измениться» не запирает редактор и копирование —
          // черновик пишут дольше минуты, а устаревшую правку отсекает версия (409).
          busy={resource.loading}
          onLoaded={() => resource.refresh()}
        />
        {import.meta.env.DEV && <Diagnostics />}
      </main>
    );
  }

  // ------------------------------------------------------------ проблема дома
  if (data.incident) {
    const incident = data.incident;
    const place = placeText(incident.location);
    const due = formatWhen(incident.due_at);
    return (
      <main className="app-shell">
        {topbar(true, incident.house_id)}
        <PageHeader
          title={incident.title || "Проблема дома"}
          subtitle={[categoryLabel(incident.category), data.house?.address].filter(Boolean).join(" · ")}
        >
          <div className="ds-status-line">
            <StatusBadge status={incident.status} />
            {data.house?.is_demo && <DemoBadge />}
          </div>
        </PageHeader>
        {refresh}
        {launchNotice && (
          <Notice role="status">
            <p>Работа обновилась. Показываем актуальный результат.</p>
          </Notice>
        )}
        {incident.status === "reported" && (
          <Notice tone="neutral" role="note">
            <p>Житель отметил отправку. Регистрация во внешней системе ДомСигналом не подтверждена.</p>
          </Notice>
        )}
        <ResidentWorkProgress
          key={incident.id}
          client={client}
          incidentId={incident.id}
          launchAttempt={launchAttempt}
          revision={resource.updatedAt}
          parentBusy={busy}
        />
        <NextAction actions={incident.allowed_actions} handlers={{ retry: resource.refresh }} busy={busy} />
        <section className="ds-section" aria-labelledby="incident-known">
          <h2 id="incident-known">Что известно</h2>
          {incident.description && <p className="ds-prose">{incident.description}</p>}
          <dl className="ds-kv">
            {place && <InfoRow label="Место">{place}</InfoRow>}
            <InfoRow label="Сообщили">
              {incident.participant_count !== null
                ? countLabel(incident.participant_count, ["житель", "жителя", "жителей"])
                : "Нет данных"}
              {`, ${countLabel(incident.report_count, ["сообщение", "сообщения", "сообщений"])}`}
            </InfoRow>
            <InfoRow label="Впервые">{formatWhen(incident.created_at) ?? "Дата не указана"}</InfoRow>
            {incident.updated_at && <InfoRow label="Обновлена">{formatWhen(incident.updated_at)}</InfoRow>}
            {due && <InfoRow label="Срок">{due}</InfoRow>}
          </dl>
          <SourceChip source={incident.provenance} label="Источник сведений" />
          {incident.rule && <SourceChip source={incident.rule} label="Основание" />}
        </section>
        {incident.reports?.length > 0 && (
          <section className="ds-section" aria-labelledby="incident-history">
            <h2 id="incident-history">Сообщения жителей</h2>
            <Timeline
              label="сообщения"
              events={incident.reports.map((report) => ({
                id: report.id,
                title: "Сообщение жителя",
                detail: report.description,
                occurred_at: report.created_at,
              }))}
            />
          </section>
        )}
        {import.meta.env.DEV && <Diagnostics />}
      </main>
    );
  }

  // ------------------------------------------------------------ главный экран
  const house = data.house!;
  const list = data.incidents!;
  const openCount = list.items.filter((item) =>
    ["detected", "open", "reported", "overdue", "escalated"].includes(item.status),
  ).length;
  const canReport = data.capabilities.features.report_create;
  return (
    <main className={`app-shell${canReport ? " has-bottom-bar" : ""}`}>
      {topbar(false, house.id)}
      <PageHeader title="Проблемы дома" subtitle={switcher(house)}>
        {house.is_demo && <DemoBadge />}
      </PageHeader>
      <SectionTabs house={house.id} current="board" navigate={navigate} />
      {refresh}
      <section className="ds-group" aria-labelledby="board-title">
        <div className="ds-group-head">
          <h2 id="board-title">
            {openCount
              ? `Сейчас открыто: ${countLabel(openCount, PROBLEMS)}`
              : list.items.length
                ? "Открытых проблем нет"
                : "О проблемах пока не сообщали"}
          </h2>
          {list.page.total > 0 && (
            <span className="ds-meta">
              {list.page.total > list.items.length ? `на странице ${list.items.length} из ${list.page.total}` : `всего ${list.page.total}`}
            </span>
          )}
        </div>
        {list.items.length ? (
          <ul className="ds-list" aria-label="Проблемы дома">
            {list.items.map((incident) => (
              <li key={incident.id}>
                <IncidentRow
                  incident={incident}
                  detailAvailable={data.capabilities.features.incident_detail}
                  href={routeUrl({ house: house.id, incident: incident.id })}
                  onNavigate={navigate}
                />
              </li>
            ))}
          </ul>
        ) : (
          <p className="ds-subtle">
            Здесь появятся проблемы, о которых сообщили соседи.{canReport ? " Если что-то сломалось — сообщите первым." : ""}
          </p>
        )}
        {(list.page.total > list.page.limit || offset > 0) && (
          <nav className="pagination" aria-label="Страницы списка проблем">
            <Button
              disabled={offset === 0}
              onClick={() => navigate(routeUrl({ house: house.id, offset: Math.max(0, offset - list.page.limit) }))}
            >
              Предыдущие
            </Button>
            <span className="ds-meta">
              {offset + 1}–{offset + list.items.length} из {list.page.total}
            </span>
            <Button
              disabled={offset + list.items.length >= list.page.total}
              onClick={() => navigate(routeUrl({ house: house.id, offset: offset + list.page.limit }))}
            >
              Следующие
            </Button>
          </nav>
        )}
      </section>
      <RecentActivity api={communityClient} houseId={house.id} links={links} />
      {canReport && (
        <div className="ds-bottom-bar">
          <Button variant="primary" stretched onClick={() => navigate(routeUrl({ house: house.id, report: true }))}>
            Сообщить о проблеме
          </Button>
        </div>
      )}
      {import.meta.env.DEV && <Diagnostics />}
    </main>
  );
}

/** «Если авария» — всегда в одном месте шапки и одного вида. */
function EmergencyLink({ href, navigate }: { href: string; navigate: (href: string) => void }) {
  return (
    <a
      className="ds-emergency-link"
      href={href}
      onClick={(event) => {
        if (event.ctrlKey || event.metaKey || event.shiftKey || event.button !== 0) return;
        event.preventDefault();
        navigate(href);
      }}
    >
      <span aria-hidden="true">!</span> Если авария
    </a>
  );
}

/** Разделы верхнего уровня. Ссылки, а не вкладки-кнопки: у каждого раздела свой адрес. */
function SectionTabs({
  house,
  current,
  navigate,
}: {
  house?: string;
  current: Section;
  navigate: (href: string, options?: { replace?: boolean }) => void;
}) {
  return (
    <nav className="ds-tabs" aria-label="Разделы">
      {SECTIONS.filter(([target]) => house || target === "mine").map(([target, label]) => {
        const href = target === "board" ? routeUrl({ house }) : routeUrl({ view: target, house });
        return (
          <a
            key={target}
            href={href}
            aria-current={current === target ? "page" : undefined}
            onClick={(event) => {
              if (event.ctrlKey || event.metaKey || event.shiftKey || event.button !== 0) return;
              event.preventDefault();
              if (current !== target) navigate(href, { replace: true });
            }}
          >
            {label}
          </a>
        );
      })}
    </nav>
  );
}

function RefreshNotice({
  resource,
}: {
  resource: { loading: boolean; error?: unknown; stale: boolean; refresh: () => void };
}) {
  if (resource.loading)
    return (
      <p role="status" className="ds-meta">
        Обновляем данные…
      </p>
    );
  if (resource.error)
    return (
      <Notice tone="warning" role="alert">
        <p>Не удалось обновить. Показаны данные, загруженные раньше.</p>
        {retryable(resource.error) && (
          <div>
            <Button small onClick={resource.refresh}>
              Повторить
            </Button>
          </div>
        )}
      </Notice>
    );
  if (resource.stale)
    return (
      <div className="refresh-notice" role="status">
        <span>Данные могли измениться.</span>
        <Button small onClick={resource.refresh}>
          Обновить
        </Button>
      </div>
    );
  return null;
}

function ErrorPanel({
  error,
  subject,
  onRetry,
  back,
}: {
  error: unknown;
  subject: string;
  onRetry: () => void;
  back?: ReactNode;
}) {
  const status = problemStatus(error);
  const trace = error instanceof ApiProblem ? error.problem.trace_id : null;
  const safeTrace =
    typeof trace === "string" && /^[a-zA-Z0-9._:-]{1,80}$/.test(trace) && ![401, 403].includes(status ?? 0)
      ? trace
      : null;
  const titles: Record<number, string> = {
    401: "Сессия MAX истекла",
    403: "Нет доступа к этому дому",
    404: "Не нашли эту страницу",
    409: "Данные изменились",
    429: "Слишком много запросов",
  };
  const details: Record<number, string> = {
    401: "Закройте мини-приложение и откройте его снова в MAX.",
    403: "Доступ закрыт или ещё не подтверждён. Откройте ДомСигнал кнопкой из вашего домового чата или выберите другой дом.",
    404: "Возможно, ссылка устарела. Вернитесь к проблемам дома.",
    409: "Обновите страницу перед следующим действием.",
    429: "Подождите минуту и попробуйте ещё раз.",
  };
  return (
    <>
      <PageHeader title={titles[status ?? 0] ?? `Не удалось загрузить ${subject}`} />
      <StatePanel
        kind="error"
        title={titles[status ?? 0] ? "Что сделать" : "Проверьте интернет и попробуйте ещё раз"}
        detail={details[status ?? 0] ?? "Если не получится, закройте мини-приложение и откройте его снова."}
        action={retryable(error) ? "Повторить" : undefined}
        onAction={onRetry}
        back={status === 401 ? undefined : back}
      />
      {safeTrace && <p className="ds-meta">Код для поддержки: {safeTrace}</p>}
    </>
  );
}

function Diagnostics() {
  return (
    <details className="diagnostics">
      <summary>Диагностика MAX · только разработка</summary>
      <dl>
        <InfoRow label="Platform">{maxBridge.platform}</InfoRow>
        <InfoRow label="Client version">{maxBridge.clientVersion ?? "неизвестна"}</InfoRow>
        <InfoRow label="initData present">{String(Boolean(maxBridge.initData))}</InfoRow>
        {Object.entries(maxBridge.capabilities).map(([label, value]) => (
          <InfoRow key={label} label={label}>
            {String(value)}
          </InfoRow>
        ))}
      </dl>
    </details>
  );
}
