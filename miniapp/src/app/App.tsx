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
import { lastHouse, rememberHouse } from "../shared/lastHouse";
import { LAUNCH_REF, maxBridge } from "../shared/max/bridge";
import { Button } from "../shared/ui/Button";
import { countLabel, formatWhen } from "../shared/ui/format";
import { HouseSwitch } from "../shared/ui/HouseSwitch";
import { IconHouse, IconNews, IconProblems, IconRequests } from "../shared/ui/icons";
import {
  BackLink,
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
  AppLink,
  type CommunityLinks,
  type CommunityView,
  MyActivityScreen,
  MyHouseScreen,
  PollScreen,
  ReceptionScreen,
  RecentActivity,
  WorksScreen,
} from "../features/community/CommunityScreens";
import { type ActivityItem, type CommunityApi, communityApi } from "../shared/api/community";
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
  /** D-01: у жителя несколько домов и ни один не выбран — сначала выбор дома. */
  pickHouse?: boolean;
};

const VIEWS: CommunityView[] = ["home", "news", "poll", "works", "mine", "reception"];
/** Разделы верхнего уровня — вкладки; остальное — вложенные экраны с «Назад». */
type Section = "board" | "mine" | "news" | "home";
/** [раздел, подпись, короткая подпись на телефоне, значок]. */
const SECTIONS: [Section, string, string, () => ReactNode][] = [
  ["board", "Проблемы", "Проблемы", IconProblems],
  ["mine", "Мои обращения", "Обращения", IconRequests],
  ["news", "Объявления", "Объявления", IconNews],
  ["home", "Мой дом", "Мой дом", IconHouse],
];
const VIEW_TITLES: Record<CommunityView, string> = {
  home: "Мой дом",
  news: "Объявления",
  poll: "Опрос",
  works: "Что сделано в доме",
  mine: "Мои обращения",
  reception: "Запись на приём",
};
/** Раздел, к которому относится вложенный экран, — он отмечен в меню. */
const VIEW_SECTION: Record<CommunityView, Section> = {
  home: "home",
  news: "news",
  poll: "news",
  works: "home",
  mine: "mine",
  reception: "home",
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
        // Кнопка «Открыть ДомСигнал» в домовом чате — доска дома этого чата (D-01).
        if (target.kind === "house") {
          if (!home) return { capabilities, me, notificationLaunch: target };
          rememberHouse(me.id, home.id);
          const incidents = await client.incidents(home.id, signal, 0, "open");
          return { capabilities, me, notificationLaunch: target, house: home, incidents };
        }
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
      // Дом из адреса; без него — последний выбранный на этом устройстве или
      // единственный. Несколько домов и выбора нет — житель выбирает сам (D-01):
      // первый по алфавиту дом уводил сообщение в чужую управляющую компанию.
      const remembered = lastHouse(me.id);
      const chosen =
        houseId !== null
          ? me.houses.find((item) => item.id === houseId)
          : me.houses.length === 1
            ? me.houses[0]
            : me.houses.find((item) => item.id === remembered);
      if (houseId !== null && !chosen && !incidentId && !cardId && !draftId) denied();
      if (chosen && houseId !== null) rememberHouse(me.id, chosen.id);
      if (!chosen && me.houses.length > 1 && !incidentId && !cardId && !draftId && view !== "mine" && view !== "poll")
        return { capabilities, me, pickHouse: true };
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
      const incidents = await client.incidents(chosen.id, signal, offset, "open");
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

  const topbar = (showBack: boolean, house?: string, refreshable = true) => (
    <div className="ds-topbar">
      <div className="ds-topbar-start">
        {showBack ? <BackLink onBack={back} /> : <span className="ds-brand">ДомСигнал</span>}
      </div>
      <div className="ds-topbar-end">
        {refreshable && (
          <button
            type="button"
            className="ds-icon-button"
            aria-label="Обновить"
            title="Обновить"
            disabled={resource.loading}
            onClick={resource.refresh}
          >
            <span aria-hidden="true">↻</span>
          </button>
        )}
        {house && view !== "home" && <EmergencyLink href={routeUrl({ house, view: "home" })} navigate={navigate} />}
      </div>
    </div>
  );

  /**
   * Оболочка экрана. Телефон: шапка, разделы (на главных экранах) и содержание.
   * Компьютер: шапка сверху, меню разделов слева — на всех экранах, с отметкой
   * раздела, к которому относится вложенный экран.
   */
  const frame = (
    content: ReactNode,
    options: { back?: boolean; house?: string; section?: Section; nested?: boolean; refreshable?: boolean; bar?: boolean } = {},
  ) => (
    <div className={`app-shell ds-resident${options.bar ? " has-bottom-bar" : ""}`}>
      {topbar(Boolean(options.back), options.house, options.refreshable ?? true)}
      {options.section && (
        <SectionTabs
          house={options.house}
          current={options.section}
          nested={Boolean(options.nested)}
          navigate={navigate}
        />
      )}
      <main className="ds-app-main">{content}</main>
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
  if (!data) {
    const status = resource.error ? problemStatus(resource.error) : null;
    return frame(
      resource.error ? (
        <ErrorPanel
          error={resource.error}
          subject={subject}
          missing={
            view
              ? "Раздел не найден"
              : cardId
                ? "Карточка «Куда обратиться» не найдена"
                : draftId
                  ? "Черновик не найден"
                  : incidentId
                    ? "Проблема не найдена"
                    : "Дом не найден"
          }
          onRetry={resource.refresh}
          back={
            status === 403 ? (
              // Текст предлагает выбрать другой дом — кнопка ведёт к выбору.
              <Button onClick={() => navigate(routeUrl(), { replace: true })}>Выбрать дом</Button>
            ) : detail ? (
              // Текст предлагает вернуться к проблемам дома — кнопка ведёт на доску этого дома.
              <Button onClick={() => navigate(routeUrl({ house: houseId ?? undefined }), { replace: true })}>
                К проблемам дома
              </Button>
            ) : undefined
          }
        />
      ) : (
        <>
          <PageHeader title={headerTitle} />
          <StatePanel title={`Загружаем ${subject}`} detail="Это займёт несколько секунд." loading />
        </>
      ),
      { back: detail, house: houseId ?? undefined },
    );
  }
  if (data.unavailable)
    return frame(
      <>
        <PageHeader title="Раздел пока недоступен" />
        <StatePanel
          title="Этот раздел сейчас выключен"
          detail="Его включает команда ДомСигнала. Попробуйте обновить позже."
          action="Обновить"
          onAction={resource.refresh}
          back={detail ? <Button onClick={() => navigate(routeUrl())}>К проблемам дома</Button> : undefined}
        />
      </>,
      { back: detail, house: currentHouse },
    );

  const houses = data.me.houses;
  const switcher = (house: House) =>
    houses.length > 1 ? (
      <HouseSwitch
        houses={houses}
        value={house.id}
        onChange={(id) => {
          rememberHouse(data.me.id, id);
          navigate(routeUrl({ house: id, view: view && view !== "poll" ? view : undefined }));
        }}
      />
    ) : (
      house.address
    );
  const refresh = <RefreshNotice resource={resource} />;

  // --------------------------------------------------------------- сообщество
  if (data.view && (data.house || ["mine", "poll"].includes(data.view))) {
    const home = data.house;
    const topLevel = ["mine", "news", "home"].includes(data.view);
    return frame(
      <>
        <PageHeader title={VIEW_TITLES[data.view]} subtitle={home && data.view !== "mine" ? switcher(home) : undefined} />
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
      </>,
      { back: !topLevel, house: home?.id, section: VIEW_SECTION[data.view], nested: !topLevel },
    );
  }

  // ------------------------------------------------------------ выбор дома
  if (data.pickHouse)
    return frame(
      <>
        <PageHeader title="Выберите дом" subtitle="Вы участник нескольких домовых чатов. Сообщения уйдут в управляющую компанию выбранного дома." />
        <ul className="ds-list ds-house-pick" aria-label="Ваши дома">
          {houses.map((house) => (
            <li key={house.id}>
              <a
                className="ds-row"
                href={routeUrl({ house: house.id, view: view && view !== "poll" ? view : undefined, report: reportParam || undefined })}
                onClick={(event) => {
                  if (event.ctrlKey || event.metaKey || event.shiftKey || event.button !== 0) return;
                  event.preventDefault();
                  rememberHouse(data.me.id, house.id);
                  navigate(routeUrl({ house: house.id, view: view && view !== "poll" ? view : undefined, report: reportParam || undefined }), { replace: true });
                }}
              >
                <span className="ds-row-title">{house.address}</span>
                <span className="ds-row-chevron" aria-hidden="true">›</span>
              </a>
            </li>
          ))}
        </ul>
      </>,
    );

  // --------------------------------------------------------------- нет дома
  if (!data.house && !data.incident && !data.card && !data.draft)
    return frame(
      <>
        <PageHeader title="Как открыть свой дом" subtitle="ДомСигнал показывает проблемы вашего дома и помогает сообщить о новой." />
        <NoHouse
          client={client}
          houses={data.openHouses ?? []}
          loadError={Boolean(data.openHousesFailed)}
          busy={resource.loading}
          onRefresh={resource.refresh}
          onJoined={(id) => navigate(routeUrl({ house: id }))}
        />
      </>,
    );

  // --------------------------------------------------------- сообщить о проблеме
  if (data.report && data.house) {
    const house = data.house;
    return frame(
      <ReportFlow
        key={house.id}
        houseId={house.id}
        houseAddress={house.address}
        client={client}
        draft={reportDrafts.current.get(house.id)}
        onDraft={onDraft}
        // Форма — промежуточный шаг: переход из неё заменяет запись истории,
        // и «Назад» из проблемы ведёт к списку, а не к пустой форме.
        onOpen={(target) => {
          // Черновик открывается поверх своей карточки «Куда обратиться»:
          // «Назад» из черновика ведёт к ней, а не к пустой форме.
          if (target.draft && target.card) {
            navigate(routeUrl({ house: house.id, card: target.card }), { replace: true });
            navigate(routeUrl({ house: house.id, draft: target.draft }));
          } else navigate(routeUrl({ house: house.id, ...target }), { replace: true });
        }}
        onCreated={() => undefined}
        onBoard={() =>
          depth() > 0 ? window.history.back() : navigate(routeUrl({ house: house.id }), { replace: true })
        }
      />,
      { back: true, house: house.id, refreshable: false, section: "board", nested: true },
    );
  }

  const busy = resource.loading || Boolean(resource.error) || resource.stale;

  // ------------------------------------------------------ куда обратиться
  if (data.card) {
    const outcome = data.card;
    return frame(
      <>
        <PageHeader title="Куда обратиться" subtitle={data.house?.address} />
        {refresh}
        {outcome.directory_changed && (
          <Notice role="status">
            <p>Сведения обновились — показываем актуальные.</p>
          </Notice>
        )}
        <div className="ds-reading">
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
        </div>
        {import.meta.env.DEV && <Diagnostics />}
      </>,
      { back: true, house: outcome.house_id, section: "board", nested: true },
    );
  }

  // --------------------------------------------------------- черновик обращения
  if (data.draft) {
    const draft = data.draft;
    return frame(
      <>
        <PageHeader title="Черновик обращения" subtitle={data.house?.address} />
        {refresh}
        <div className="ds-reading">
          <AppealDraftScreen
            key={draft.id}
            draft={draft}
            client={client}
            // P6b: «данные могли измениться» не запирает редактор и копирование —
            // черновик пишут дольше минуты, а устаревшую правку отсекает версия (409).
            busy={resource.loading}
            onLoaded={() => resource.refresh()}
          />
        </div>
        {import.meta.env.DEV && <Diagnostics />}
      </>,
      { back: true, house: draft.house_id, section: "mine", nested: true },
    );
  }

  // ------------------------------------------------------------ проблема дома
  if (data.incident) {
    const incident = data.incident;
    const place = placeText(incident.location);
    const due = formatWhen(incident.due_at);
    return frame(
      <>
        <PageHeader
          title={incident.title || "Проблема дома"}
          subtitle={[categoryLabel(incident.category), data.house?.address].filter(Boolean).join(" · ")}
        >
          <div className="ds-status-line">
            <StatusBadge status={incident.status} />
          </div>
        </PageHeader>
        {refresh}
        {closureText(incident) && (
          <Notice tone={incident.closure === "residents_confirmed" ? "success" : "neutral"} role="status">
            <p>{closureText(incident)}</p>
          </Notice>
        )}
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
        {/* Ход решения — первым: что сейчас происходит и что дальше. На компьютере — колонка справа. */}
        <div className="ds-split ds-split-aside-first">
          <div className="ds-aside">
            <ResidentWorkProgress
              key={incident.id}
              client={client}
              incidentId={incident.id}
              launchAttempt={launchAttempt}
              revision={resource.updatedAt}
              parentBusy={busy}
              reported={{
                people: incident.participant_count,
                messages: incident.report_count,
              }}
            />
            <NextAction actions={incident.allowed_actions} handlers={{ retry: resource.refresh }} busy={busy} />
          </div>
          <div className="ds-main">
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
              <div>
                <SourceChip source={incident.provenance} label="Источник сведений" />
                {incident.rule && <SourceChip source={incident.rule} label="Основание" />}
              </div>
            </section>
            {incident.reports?.length > 0 && (
              <section className="ds-section" aria-labelledby="incident-history">
                <h2 id="incident-history">Сообщения жителей</h2>
                <Timeline
                  label="сообщения"
                  events={incident.reports.map((report, index) => ({
                    id: report.id,
                    // O-2: сосед присоединился — текст проблемы второй раз не повторяется.
                    title: report.joined ? "Сосед отметил: «Меня тоже касается»" : "Сообщение жителя",
                    detail: report.joined && index > 0 ? null : report.description,
                    occurred_at: report.created_at,
                  }))}
                />
              </section>
            )}
          </div>
        </div>
        {import.meta.env.DEV && <Diagnostics />}
      </>,
      { back: true, house: incident.house_id, section: "board", nested: true },
    );
  }

  // ------------------------------------------------------------ главный экран
  const house = data.house!;
  const canReport = data.capabilities.features.report_create;
  return frame(
    <>
      <div className="ds-header-row">
        <PageHeader title="Проблемы дома" subtitle={switcher(house)} />
        {canReport && (
          // Телефон: липкая панель у большого пальца; компьютер — действие в шапке экрана.
          <div className="ds-bottom-bar">
            <Button variant="primary" stretched onClick={() => navigate(routeUrl({ house: house.id, report: true }))}>
              Сообщить о проблеме
            </Button>
          </div>
        )}
      </div>
      {refresh}
      <Board
        house={house}
        list={data.incidents!}
        client={client}
        offset={offset}
        canReport={canReport}
        detailAvailable={data.capabilities.features.incident_detail}
        community={communityClient}
        links={links}
        navigate={navigate}
      />
      {import.meta.env.DEV && <Diagnostics />}
    </>,
    { house: house.id, section: "board", bar: canReport },
  );
}

/**
 * Доска дома. Свои сообщения жителя отмечены прямо в строке проблемы — со
 * статусом заявки из «Мои обращения»; отдельным списком ниже остаются только
 * обращения, которых на этой странице доски нет (черновики, «куда обратиться»).
 * Если все обращения уже видны в списке, вместо блока — одна ссылка на полный
 * список: блок без новых сведений только повторял бы доску.
 */
function Board({
  house,
  list,
  client,
  offset,
  canReport,
  detailAvailable,
  community,
  links,
  navigate,
}: {
  house: House;
  list: IncidentList;
  client: DomSignalApi;
  offset: number;
  canReport: boolean;
  detailAvailable: boolean;
  community: CommunityApi;
  links: CommunityLinks;
  navigate: (href: string) => void;
}) {
  const load = useCallback((signal: AbortSignal) => community.myActivity(0, signal), [community]);
  const activity = useResource(`recent:${house.id}`, load);
  const mine = (activity.data?.items ?? []).filter((item) => item.house_id === house.id);
  const byIncident = new Map<string, ActivityItem>();
  for (const item of mine) if (item.incident_id && !byIncident.has(item.incident_id)) byIncident.set(item.incident_id, item);
  const shown = new Set(list.items.map((item) => item.id));
  const rest = mine.filter((item) => !(item.incident_id && shown.has(item.incident_id)));
  const allOnBoard = mine.length > 0 && rest.length === 0;
  // Счёт доски — по всему дому с сервера (F1), а не по странице списка.
  const openCount =
    list.open_total ??
    list.items.filter((item) => ["detected", "open", "reported", "overdue", "escalated"].includes(item.status)).length;
  const resolvedCount = list.resolved_recent_total ?? 0;
  return (
    <div className="ds-split">
      <section className="ds-group ds-board" aria-labelledby="board-title">
        <div className="ds-group-head">
          <h2 id="board-title">
            {openCount
              ? `Сейчас открыто: ${countLabel(openCount, PROBLEMS)}`
              : list.items.length || resolvedCount
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
                  detailAvailable={detailAvailable}
                  href={routeUrl({ house: house.id, incident: incident.id })}
                  onNavigate={navigate}
                  mine={mineLabel(byIncident.get(incident.id))}
                />
              </li>
            ))}
          </ul>
        ) : (
          <p className="ds-subtle">
            {resolvedCount
              ? "Все проблемы, о которых сообщали соседи, решены."
              : "Здесь появятся проблемы, о которых сообщили соседи."}
            {canReport ? " Если что-то сломалось — сообщите первым." : ""}
          </p>
        )}
        {resolvedCount > 0 && (
          <ResolvedRecently
            house={house}
            client={client}
            total={resolvedCount}
            detailAvailable={detailAvailable}
            navigate={navigate}
          />
        )}
        {allOnBoard && (
          <p className="ds-board-mine">
            <AppLink className="ds-action-link" href={links.view("mine", { house: house.id })} navigate={links.navigate}>
              Все мои обращения
            </AppLink>
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
      {!allOnBoard && (
        <div className="ds-aside">
          <RecentActivity
            houseId={house.id}
            links={links}
            items={rest.slice(0, 3)}
            onBoard={mine.length - rest.length}
            error={activity.data ? undefined : activity.error}
            onRetry={activity.refresh}
          />
        </div>
      )}
    </div>
  );
}

/**
 * «Решённые за 30 дней» (F1, B-04): проблемы, которые жители подтвердили.
 * Список грузится при раскрытии — главная доска показывает открытые.
 */
function ResolvedRecently({
  house,
  client,
  total,
  detailAvailable,
  navigate,
}: {
  house: House;
  client: DomSignalApi;
  total: number;
  detailAvailable: boolean;
  navigate: (href: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const load = useCallback(
    (signal: AbortSignal) => client.incidents(house.id, signal, 0, "resolved_recent"),
    [client, house.id],
  );
  return (
    <details className="ds-disclosure ds-resolved" onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary>Решённые за 30 дней ({total})</summary>
      <div className="ds-disclosure-body">{open && <ResolvedList load={load} house={house} detailAvailable={detailAvailable} navigate={navigate} />}</div>
    </details>
  );
}

function ResolvedList({
  load,
  house,
  detailAvailable,
  navigate,
}: {
  load: (signal: AbortSignal) => Promise<IncidentList>;
  house: House;
  detailAvailable: boolean;
  navigate: (href: string) => void;
}) {
  const resolved = useResource(`resolved:${house.id}`, load);
  if (!resolved.data)
    return resolved.error ? (
      <StatePanel kind="error" title="Не удалось загрузить решённые проблемы" action="Повторить" onAction={resolved.refresh} />
    ) : (
      <StatePanel title="Загружаем решённые проблемы" loading />
    );
  return (
    <ul className="ds-list" aria-label="Решённые за 30 дней">
      {resolved.data.items.map((incident) => (
        <li key={incident.id}>
          <IncidentRow
            incident={incident}
            detailAvailable={detailAvailable}
            href={routeUrl({ house: house.id, incident: incident.id })}
            onNavigate={navigate}
            mine={closureText(incident) ?? undefined}
          />
        </li>
      ))}
    </ul>
  );
}

/** «Решена 29 сентября — жители подтвердили» / «Закрыта … — заявку отменила УК» (B-04). */
function closureText(incident: { status: string; closure?: string | null; resolved_at?: string | null }): string | null {
  if (!incident.closure || !incident.resolved_at) return null;
  const day = formatWhen(incident.resolved_at);
  return incident.closure === "residents_confirmed"
    ? `Решена ${day} — жители подтвердили, что исправлено.`
    : `Закрыта ${day} — управляющая компания отменила заявку.`;
}

/** «Вы сообщили · T-2 · Заявка у УК: ждёт принятия в работу» — из «Мои обращения», без второй карточки. */
function mineLabel(item: ActivityItem | undefined): string | undefined {
  if (!item) return undefined;
  return [item.kind === "joined" ? "Вас тоже касается" : "Вы сообщили", item.ticket_number, item.status_label]
    .filter(Boolean)
    .join(" · ");
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

/**
 * Разделы верхнего уровня. Ссылки, а не вкладки-кнопки: у каждого раздела свой адрес.
 * Телефон: четыре равные ячейки в одну строку при любой ширине, на вложенных
 * экранах вместо них — «Назад». Компьютер: меню слева на всех экранах.
 */
function SectionTabs({
  house,
  current,
  nested,
  navigate,
}: {
  house?: string;
  current: Section;
  nested: boolean;
  navigate: (href: string, options?: { replace?: boolean }) => void;
}) {
  return (
    <nav className={`ds-nav${nested ? " is-nested" : ""}`} aria-label="Разделы">
      {SECTIONS.filter(([target]) => house || target === "mine").map(([target, label, short, Icon]) => {
        const href = target === "board" ? routeUrl({ house }) : routeUrl({ view: target, house });
        return (
          <a
            key={target}
            href={href}
            // Вложенный экран относится к разделу, но не является им: «true», а не «page».
            aria-current={current === target ? (nested ? "true" : "page") : undefined}
            aria-label={short !== label ? label : undefined}
            onClick={(event) => {
              if (event.ctrlKey || event.metaKey || event.shiftKey || event.button !== 0) return;
              event.preventDefault();
              if (current !== target || nested) navigate(href);
            }}
          >
            <Icon />
            {short !== label ? (
              <>
                <span className="ds-nav-short">{short}</span>
                <span className="ds-nav-long">{label}</span>
              </>
            ) : (
              <span>{label}</span>
            )}
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
  missing,
  onRetry,
  back,
}: {
  error: unknown;
  subject: string;
  /** Заголовок для 404: что именно не нашлось. */
  missing: string;
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
    404: missing,
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
