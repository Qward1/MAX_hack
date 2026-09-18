import { Button, Flex, Panel, Typography } from "@maxhub/max-ui";
import { type ReactNode, useCallback, useEffect, useState } from "react";
import {
  ApiProblem,
  apiClient,
  type Capabilities,
  type DomSignalApi,
  type IncidentDetail,
  type IncidentList,
  type Me,
  type NotificationLaunch,
  problemStatus,
  retryable,
} from "../shared/api/client";
import { useResource } from "../shared/api/useResource";
import { maxBridge } from "../shared/max/bridge";
import {
  DemoBadge,
  InfoRow,
  NextAction,
  PageHeader,
  SourceChip,
  StatePanel,
  StatusBadge,
  Timeline,
} from "../shared/ui/semantic";
import { IncidentCard } from "../features/incidents/IncidentCard";
import { ReportForm } from "../features/incidents/ReportForm";
import { ResidentWorkProgress } from "../features/tickets/ResidentWorkProgress";
import {
  categoryLabel,
  formatDate,
  knownActions,
  statusLabels,
} from "../features/incidents/presentation";

type Loaded = {
  notificationLaunch?: NotificationLaunch;
  capabilities: Capabilities;
  me: Me;
  house?: Me["houses"][number];
  incidents?: IncidentList;
  incident?: IncidentDetail;
  unavailable?: boolean;
};
function routeUrl(house?: string, incident?: string, offset = 0) {
  // Never propagate MAX launch/auth parameters into DOM links or copied navigation URLs.
  const url = new URL(window.location.pathname, window.location.origin);
  const testActor = new URLSearchParams(window.location.search).get("test_actor");
  if (testActor && /^a16-[a-z-]+$/.test(testActor)) url.searchParams.set("test_actor", testActor);
  if (house) url.searchParams.set("house", house);
  if (incident) url.searchParams.set("incident", incident);
  if (offset) url.searchParams.set("offset", String(offset));
  return url.pathname + url.search;
}

export function App({ client = apiClient }: { client?: DomSignalApi }) {
  const [location, setLocation] = useState(() => window.location.href);
  const [reportOpen, setReportOpen] = useState(false);
  const [launchPending, setLaunchPending] = useState(true);
  const [launchNotice, setLaunchNotice] = useState(false);
  const [launchAttempt, setLaunchAttempt] = useState<string | null>(null);
  const route = new URL(location);
  const houseId = route.searchParams.get("house");
  const incidentId = route.searchParams.get("incident");
  const offset = Math.max(
    0,
    Math.min(
      1000000,
      Number.parseInt(route.searchParams.get("offset") ?? "0") || 0,
    ),
  );
  const key = JSON.stringify([houseId, incidentId, offset, launchPending]);
  const navigate = useCallback((href: string) => {
    window.history.pushState(null, "", href);
    setLocation(window.location.href);
    setReportOpen(false);
    setLaunchPending(false);
    setLaunchNotice(false);
    setLaunchAttempt(null);
    window.scrollTo?.(0, 0);
  }, []);
  useEffect(() => {
    const onBack = () => {
      setLocation(window.location.href);
      setReportOpen(false);
    };
    window.addEventListener("popstate", onBack);
    return () => window.removeEventListener("popstate", onBack);
  }, []);
  const load = useCallback(
    async (signal: AbortSignal): Promise<Loaded> => {
      const capabilities = await client.capabilities(signal);
      await client.authenticate(capabilities, signal);
      const me = await client.me(signal);
      const testRef = capabilities.environment !== "production" && capabilities.features.test_auth
        ? new URLSearchParams(window.location.search).get("test_start_param") : null;
      const launchRef = launchPending ? (maxBridge.startParam ?? testRef) : null;
      if (launchRef && capabilities.features.miniapp && capabilities.features.incident_detail) {
        const target = await client.notificationLaunch(launchRef, signal);
        const incident = await client.incident(target.incident_id, signal, target.house_id);
        return { capabilities, me, incident, notificationLaunch: target,
          house: me.houses.find((house) => house.id === target.house_id) };
      }
      if (
        !capabilities.features.miniapp ||
        !(incidentId
          ? capabilities.features.incident_detail
          : capabilities.features.incident_board)
      ) {
        return { capabilities, me, unavailable: true };
      }
      if (incidentId) {
        const incident = await client.incident(
          incidentId, signal, houseId ?? undefined,
        );
        return {
          capabilities,
          me,
          incident,
          house: me.houses.find((house) => house.id === incident.house_id),
        };
      }
      const house = houseId !== null
        ? me.houses.find((item) => item.id === houseId)
        : me.houses.length === 1
          ? me.houses[0]
          : undefined;
      if (houseId !== null && !house)
        throw new ApiProblem({
          status: 403,
          type: "about:blank",
          code: "house_access_denied",
          title: "",
          detail: "",
          trace_id: "",
          retryable: false,
        });
      if (!house) return { capabilities, me };
      const incidents = await client.incidents(house.id, signal, offset);
      return { capabilities, me, house, incidents };
    },
    [client, houseId, incidentId, offset, launchPending],
  );
  const resource = useResource(key, load);
  const data = resource.data;
  useEffect(() => {
    const target = data?.notificationLaunch;
    if (!target || !launchPending) return;
    setLaunchPending(false);
    setLaunchNotice(target.stale);
    setLaunchAttempt(target.work_attempt_id);
    window.history.replaceState(null, "", routeUrl(target.house_id, target.incident_id));
    setLocation(window.location.href);
  }, [data?.notificationLaunch, launchPending]);
  const back = useCallback(
    () => navigate(routeUrl(data?.incident?.house_id ?? houseId ?? undefined)),
    [navigate, data?.incident?.house_id, houseId],
  );
  useEffect(
    () => (incidentId ? maxBridge.subscribeBack(back) : undefined),
    [incidentId, back],
  );
  useEffect(() => {
    if (data || resource.error)
      document.getElementById("page-title")?.focus({ preventScroll: true });
  }, [key, Boolean(data), Boolean(resource.error)]);

  const backLink = (
    <Button variant="secondary" onClick={() => navigate(routeUrl())}>
      К домам
    </Button>
  );
  if (!data)
    return (
      <main className="app-shell detail-shell">
        <PageHeader title={incidentId ? "Проблема дома" : "Мой дом"} />
        {resource.error ? (
          <ErrorPanel
            error={resource.error}
            onRetry={resource.refresh}
            back={backLink}
          />
        ) : (
          <StatePanel
            title={incidentId ? "Загрузка проблемы" : "Загрузка доски дома"}
            detail="Получаем актуальные данные"
            loading
          />
        )}
      </main>
    );
  if (data.unavailable)
    return (
      <main className="app-shell">
        <PageHeader title="Раздел пока недоступен" />
        <StatePanel
          title="Этот раздел сейчас отключён"
          detail="Попробуйте обновить данные позже."
          action="Обновить"
          onAction={resource.refresh}
          back={incidentId ? backLink : undefined}
        />
      </main>
    );
  if (!data.house && !data.incident)
    return (
      <main className="app-shell">
        <PageHeader title="Мой дом" />
        {data.me.houses.length > 1 ? (
          <Panel>
            <h2>Выберите дом</h2>
            {data.me.houses.map((house) => (
              <Button key={house.id} onClick={() => navigate(routeUrl(house.id))}>
                {house.address}
              </Button>
            ))}
          </Panel>
        ) : (
          <StatePanel
            title="Пока нет доступных домов"
            detail="Откройте ДомСигнал из своего дома в MAX. Ссылка сама по себе не предоставляет доступ."
            action="Обновить"
            onAction={resource.refresh}
          />
        )}
      </main>
    );

  const notice = (
    <>
      {resource.loading && (
        <p role="status" className="refresh-notice">
          Обновляем данные…
        </p>
      )}
      {resource.error && (
        <div className="refresh-notice" role="alert">
          <strong>
            Не удалось обновить. Показаны ранее загруженные данные.
          </strong>
          {retryable(resource.error) && (
            <Button size="small" variant="secondary" onClick={resource.refresh}>
              Повторить
            </Button>
          )}
        </div>
      )}
      {resource.stale && !resource.loading && !resource.error && (
        <div className="refresh-notice" role="status">
          Данные могли измениться.
          <Button size="small" variant="secondary" onClick={resource.refresh}>
            Обновить
          </Button>
        </div>
      )}
    </>
  );
  const toolbar = (
    <Flex
      justify="space-between"
      align="center"
      wrap="wrap"
      gap={12}
      className="toolbar"
    >
      {incidentId ? (
        <Button variant="ghost" onClick={back}>
          ← К доске дома
        </Button>
      ) : (
        <Typography.Text variant="label-strong">ДомСигнал</Typography.Text>
      )}
      <Button
        size="small"
        variant="ghost"
        disabled={resource.loading}
        onClick={resource.refresh}
      >
        Обновить
      </Button>
    </Flex>
  );
  if (data.incident) {
    const incident = data.incident;
    return (
      <main className="app-shell detail-shell">
        {toolbar}
        <PageHeader
          title={incident.title || "Проблема дома"}
          subtitle={data.house?.address}
          eyebrow={categoryLabel(incident.category)}
        >
          <Flex gap={12} wrap="wrap">
            <StatusBadge status={incident.status} />
            {data.house?.is_demo && <DemoBadge />}
          </Flex>
        </PageHeader>
        {notice}
        {launchNotice && <p role="status" className="refresh-notice">
          Работа обновилась. Показываем актуальный результат.
        </p>}
        <ResidentWorkProgress key={incident.id} client={client} incidentId={incident.id}
          launchAttempt={launchAttempt}
          revision={resource.updatedAt} parentBusy={resource.loading || Boolean(resource.error) || resource.stale} />
        {incident.status === "reported" && (
          <Panel className="honesty-note">
            Житель отметил отправку. Регистрация во внешней системе ДомСигналом
            не подтверждена.
          </Panel>
        )}
        <NextAction
          actions={incident.allowed_actions}
          handlers={{ retry: resource.refresh }}
          busy={resource.loading || Boolean(resource.error) || resource.stale}
        />
        <Panel className="detail-section">
          <Typography.Title asChild>
            <h2>О проблеме</h2>
          </Typography.Title>
          <p className="full-text">
            {incident.description || "Описание пока не добавлено."}
          </p>
          <SourceChip source={incident.provenance} />
          <dl>
            <InfoRow label="Сообщений по проблеме">
              {incident.report_count ?? "Нет данных"}
            </InfoRow>
            <InfoRow label="Участников">
              {incident.participant_count ?? "Нет данных"}
            </InfoRow>
            <InfoRow label="Место">
              {incident.location
                ? [
                    incident.location.entrance && `Подъезд ${incident.location.entrance}`,
                    incident.location.floor && `Этаж ${incident.location.floor}`,
                    incident.location.label,
                  ].filter(Boolean).join(", ") || "Не указано"
                : "Не указано"}
            </InfoRow>
            <InfoRow label="Обновлена">
              {formatDate(incident.updated_at) ?? "Нет данных"}
            </InfoRow>
            <InfoRow label="Создана">
              {formatDate(incident.created_at) ?? "Дата не указана"}
            </InfoRow>
            <InfoRow label="Срок">
              {formatDate(incident.due_at) ?? "Не определён"}
            </InfoRow>
          </dl>
        </Panel>
        {incident.rule && (
          <Panel className="detail-section">
            <Typography.Title asChild>
              <h2>Источник и основание</h2>
            </Typography.Title>
            <SourceChip source={incident.rule} />
          </Panel>
        )}
        {incident.reports?.length > 0 && (
          <Panel className="detail-section">
            <Typography.Title asChild>
              <h2>Сообщения по проблеме</h2>
            </Typography.Title>
            <Timeline
              events={incident.reports.map((report) => ({
                id: report.id,
                title: "Сообщение",
                detail: report.description,
                occurred_at: report.created_at,
              }))}
            />
          </Panel>
        )}
        <footer className="page-footer">
          Информация обновляется по сообщениям жителей.
        </footer>
        {import.meta.env.DEV && <Diagnostics />}
      </main>
    );
  }
  const house = data.house!;
  const list = data.incidents!;
  const openCount = list.items.filter((item) =>
    ["detected", "open", "reported", "overdue", "escalated"].includes(
      item.status,
    ),
  ).length;
  const unknownCount = list.items.filter(
    (item) => !Object.hasOwn(statusLabels, item.status),
  ).length;
  const actionCount = list.items.filter((item) =>
    knownActions(item.allowed_actions).some(
      (action) => action.enabled && action.code !== "retry",
    ),
  ).length;
  return (
    <main className="app-shell">
      {toolbar}
      <PageHeader
        title={house.address}
        subtitle={house.name !== house.address ? house.name : undefined}
        eyebrow="Дом"
      >
        {house.is_demo && <DemoBadge />}
      </PageHeader>
      {data.me.houses.length > 1 && (
        <label className="house-select">
          Выбрать дом
          <select
            value={house.id}
            onChange={(event) => navigate(routeUrl(event.target.value))}
          >
            {data.me.houses.map((item) => (
              <option key={item.id} value={item.id}>
                {item.address}
              </option>
            ))}
          </select>
        </label>
      )}
      {notice}
      <Panel className="board-summary">
        <Flex gap={24} wrap="wrap" align="center">
          <Typography.Text variant="header" className="summary-value">
            {openCount}
          </Typography.Text>
          <div>
            <Typography.Text variant="body-strong">
              Открытых проблем
            </Typography.Text>
            <p className="muted">
              {list.page.total > list.items.length
                ? "На этой странице"
                : "В вашем доме"}
            </p>
          </div>
        </Flex>
        {unknownCount > 0 && (
          <p className="muted">
            Статус неизвестен ещё у {unknownCount} проблем.
          </p>
        )}
        <p className="muted">
          {actionCount > 0
            ? `Требуют действия: ${actionCount}`
            : "Следующие действия пока не определены."}
        </p>
      </Panel>
      <Flex
        className="section-heading"
        justify="space-between"
        align="center"
        wrap="wrap"
        gap={16}
      >
        <Typography.Title asChild>
          <h2>
            Проблемы дома <span className="muted">· {list.page.total}</span>
          </h2>
        </Typography.Title>
        {data.capabilities.features.report_create && (
          <Button
            variant="secondary"
            onClick={() => setReportOpen((value) => !value)}
            aria-expanded={reportOpen}
          >
            {reportOpen ? "Закрыть форму" : "Сообщить"}
          </Button>
        )}
      </Flex>
      {reportOpen && (
        <ReportForm
          key={house.id}
          houseId={house.id}
          client={client}
          onCreated={() => {
            setReportOpen(false);
            resource.refresh();
          }}
        />
      )}
      {list.items.length ? (
        <ul className="incident-grid" aria-label="Инциденты дома">
          {list.items.map((incident) => (
            <li key={incident.id}>
              <IncidentCard
                incident={incident}
                detailAvailable={data.capabilities.features.incident_detail}
                href={routeUrl(house.id, incident.id)}
                onNavigate={navigate}
              />
            </li>
          ))}
        </ul>
      ) : (
        <StatePanel
          title="На доске пока пусто"
          detail="Новый сигнал появится здесь после сохранения."
        />
      )}
      {(list.page.total > list.page.limit || offset > 0) && (
        <nav className="pagination" aria-label="Страницы инцидентов">
          <Button
            variant="secondary"
            disabled={offset === 0}
            onClick={() =>
              navigate(
                routeUrl(
                  house.id,
                  undefined,
                  Math.max(0, offset - list.page.limit),
                ),
              )
            }
          >
            Предыдущие
          </Button>
          <span>
            {offset + 1}–{offset + list.items.length} из {list.page.total}
          </span>
          <Button
            variant="secondary"
            disabled={offset + list.items.length >= list.page.total}
            onClick={() =>
              navigate(routeUrl(house.id, undefined, offset + list.page.limit))
            }
          >
            Следующие
          </Button>
        </nav>
      )}
      <footer className="page-footer">
        Общая картина начинается с вашего сигнала.
      </footer>
      {import.meta.env.DEV && <Diagnostics />}
    </main>
  );
}

function ErrorPanel({
  error,
  onRetry,
  back,
}: {
  error: unknown;
  onRetry: () => void;
  back: ReactNode;
}) {
  const status = problemStatus(error);
  const trace = error instanceof ApiProblem ? error.problem.trace_id : null;
  const safeTrace =
    typeof trace === "string" &&
    /^[a-zA-Z0-9._:-]{1,80}$/.test(trace) &&
    ![401, 403].includes(status ?? 0)
      ? trace
      : null;
  const titles: Record<number, string> = {
    401: "Войдите через MAX",
    403: "Нет доступа к этому дому",
    404: "Проблема не найдена",
    409: "Данные изменились",
  };
  const details: Record<number, string> = {
    401: "Сессия недействительна или истекла. Закройте мини-приложение и откройте его заново в MAX.",
    403: "Выберите доступный вам дом.",
    404: "Вернитесь к доске и обновите список проблем.",
    409: "Обновите данные перед следующим действием.",
  };
  return (
    <>
      <StatePanel
        title={titles[status ?? 0] ?? "Доска временно недоступна"}
        detail={
          details[status ?? 0] ?? "Проверьте соединение и попробуйте ещё раз."
        }
        action={retryable(error) ? "Попробовать снова" : undefined}
        onAction={onRetry}
        back={status === 401 ? undefined : back}
      />
      {safeTrace && (
        <p className="page-footer">Код для поддержки: {safeTrace}</p>
      )}
    </>
  );
}
function Diagnostics() {
  return (
    <details className="diagnostics">
      <summary>Диагностика MAX · только разработка</summary>
      <dl>
        <InfoRow label="Platform">{maxBridge.platform}</InfoRow>
        <InfoRow label="Client version">
          {maxBridge.clientVersion ?? "неизвестна"}
        </InfoRow>
        <InfoRow label="initData present">
          {String(Boolean(maxBridge.initData))}
        </InfoRow>
        {Object.entries(maxBridge.capabilities).map(([label, value]) => (
          <InfoRow key={label} label={label}>
            {String(value)}
          </InfoRow>
        ))}
      </dl>
    </details>
  );
}
