import { useState } from "react";
import { adminClient, Feedback, Title, useRead, type Schema } from "./administration";
import { ColumnChart, Funnel, PeriodSwitch, QuotaMeter, SERIES, STRENGTH, StatTile, dayLabel, formatNumber } from "./charts";
import { PollResultsView } from "./CommunityPages";

type Days = 7 | 14 | 30;
const categories: Record<string, string> = { elevator: "Лифт", water: "Вода", lighting: "Освещение", waste: "Отходы", other: "Другое" };
const rub = new Intl.NumberFormat("ru-RU", { style: "currency", currency: "RUB", maximumFractionDigits: 2 });
const percent = new Intl.NumberFormat("ru-RU", { style: "percent", maximumFractionDigits: 1 });

function minutes(value?: number | null) {
  if (value === null || value === undefined) return "—";
  if (value < 90) return `${formatNumber(Math.round(value))} мин`;
  return `${formatNumber(Math.round(value / 6) / 10)} ч`;
}

type Links = { tickets?: string; signals?: string; navigate: (href: string) => void };

function QueueLink({ href, navigate, children }: { href: string; navigate: (href: string) => void; children: string }) {
  return <a className="ds-btn ds-btn-secondary" href={href} onClick={e => { e.preventDefault(); navigate(href); }}>{children}</a>;
}

/** Обзор УК: «Чаты: N из Q», дома, динамика и выгрузка CSV. */
export function CompanyOverview({ base, links }: { base: string; links?: Links }) {
  const [days, setDays] = useState<Days>(7);
  const r = useRead<Schema["CompanyDashboard"]>(`${base}/dashboard?days=${days}`);
  const [csvError, setCsvError] = useState("");
  const data = r.error ? undefined : r.data;
  const houses = data?.houses ?? [];
  const sum = (key: keyof Schema["HouseStats"]) => houses.reduce((s, h) => s + Number(h[key] ?? 0), 0);
  async function download() {
    setCsvError("");
    try {
      const blob = await adminClient.download(`${base}/dashboard.csv?days=${days}`);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url; link.download = `domsignal-obzor-${days}d.csv`;
      document.body.append(link); link.click(); link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) { setCsvError(e instanceof Error ? e.message : "Не удалось выгрузить CSV"); }
  }
  return <>
    <Title description={data?.scope === "assigned" ? "Только дома, на которые вы назначены" : "Все дома вашей управляющей компании"}>Обзор</Title>
    <div className="dashboard-controls">
      <PeriodSwitch value={days} onChange={setDays} />
      <button type="button" className="ticket-button secondary" onClick={() => void download()} disabled={!data}>Выгрузить CSV</button>
    </div>
    <Feedback loading={r.loading && !data} error={r.error ?? (csvError || undefined)} />
    {data && <div className={r.loading ? "dashboard is-refreshing" : "dashboard"}>
      <QuotaMeter quota={data.quota} />
      {(() => {
        const activity = data.activity;
        const signalsEmpty = activity.every(d => d.signals === 0);
        const ticketsEmpty = activity.every(d => d.tickets_created === 0 && d.tickets_closed === 0);
        const empty = houses.length > 0 && signalsEmpty && ticketsEmpty;
        const period = activity.length ? `${dayLabel(activity[0].day)} – ${dayLabel(activity[activity.length - 1].day)}` : `${days} дней`;
        return <>
          <dl className="stat-row">
            <StatTile label="Открытые заявки сейчас" value={formatNumber(sum("tickets_open"))} />
            {!empty && <>
              <StatTile label={`Сигналы за ${days} дней`} value={formatNumber(sum("signals"))} />
              <StatTile label="Заявки закрыты" value={formatNumber(sum("tickets_closed"))} note={`из ${formatNumber(sum("tickets_created"))} созданных за период`} />
              <StatTile label="Проверка жителями" value={`${formatNumber(sum("verification_confirmed"))} / ${formatNumber(sum("verification_returned"))}`}
                note="подтверждено / возвращено в работу" />
            </>}
          </dl>
          {houses.length === 0 ? <p className="state-panel">{data.scope === "assigned"
            ? "Вы пока не назначены ни на один дом. Назначение делает администратор УК."
            : "Домов в управлении пока нет. Запросите управление домом в разделе «Дома»."}</p> : <>
            {empty ? <section className="dashboard-empty" aria-labelledby="dashboard-empty-title">
              <h2 id="dashboard-empty-title">За {period} событий нет</h2>
              <p>Сигналов из домовых чатов не было, заявки не создавались и не закрывались. Графики появятся, когда будут события.</p>
              {links && (links.tickets || links.signals) && <div className="button-row">
                {links.tickets && <QueueLink href={links.tickets} navigate={links.navigate}>Открыть заявки</QueueLink>}
                {links.signals && <QueueLink href={links.signals} navigate={links.navigate}>Открыть сигналы</QueueLink>}
              </div>}
            </section> : <div className="chart-grid-2">
              {signalsEmpty ? <EmptyChart title="Сигналы из чатов по дням" period={period} />
                : <ColumnChart title="Сигналы из чатов по дням" days={activity.map(d => d.day)}
                  series={[{ key: "signals", label: "Сигналы", color: SERIES.primary, values: activity.map(d => d.signals) }]} />}
              {ticketsEmpty ? <EmptyChart title="Заявки по дням" period={period} />
                : <ColumnChart title="Заявки по дням" days={activity.map(d => d.day)} series={[
                  { key: "created", label: "Создано", color: SERIES.primary, values: activity.map(d => d.tickets_created) },
                  { key: "closed", label: "Закрыто", color: SERIES.secondary, values: activity.map(d => d.tickets_closed) },
                ]} />}
            </div>}
            <h2>По домам</h2>
            <HouseStatsCards houses={houses} />
            <div className="table-scroll house-stats-table"><table className="data-table">
              <thead><tr><th scope="col">Дом</th><th scope="col">Сигналы</th><th scope="col">Заявки открыто</th>
                <th scope="col">Закрыто</th><th scope="col">Медиана до принятия</th><th scope="col">Подтверждено</th>
                <th scope="col">Возвращено</th><th scope="col">Частые категории</th></tr></thead>
              <tbody>{houses.map(h => <tr key={h.house_id}>
                <th scope="row">{h.address}</th><td>{formatNumber(h.signals)}</td><td>{formatNumber(h.tickets_open)}</td>
                <td>{formatNumber(h.tickets_closed)}</td><td>{minutes(h.median_accept_minutes)}</td>
                <td>{formatNumber(h.verification_confirmed)}</td><td>{formatNumber(h.verification_returned)}</td>
                <td>{topCategories(h)}</td>
              </tr>)}</tbody></table></div>
            <p className="muted">Сутки считаются по московскому времени. Медиана — от создания заявки до её принятия, по заявкам периода.
              Тексты жителей в обзор не попадают.</p>
          </>}
        </>;
      })()}
      {(data.polls ?? []).length > 0 && <section aria-label="Опросы жителей">
        <h2>Опросы жителей</h2>
        <div className="house-cards">{(data.polls ?? []).map(poll => <div className="admin-detail" key={poll.poll_id}>
          <PollResultsView poll={poll} /></div>)}</div>
      </section>}
    </div>}
  </>;
}

function topCategories(h: Schema["HouseStats"]) {
  return h.top_categories.length ? h.top_categories.map(c => `${categories[c.category] ?? c.category} (${c.count})`).join(", ") : "—";
}

/** Пустой график — одной строкой с периодом, а не полем нулевых столбцов. */
function EmptyChart({ title, period }: { title: string; period: string }) {
  return <section className="chart chart-empty-row" aria-label={title}>
    <h3>{title}</h3><p className="muted">За {period} событий нет</p>
  </section>;
}

/**
 * Телефон: дом — карточка с тремя главными показателями, остальные — по
 * раскрытию. Таблица на всю ширину остаётся для планшета и компьютера.
 */
function HouseStatsCards({ houses }: { houses: Schema["HouseStats"][] }) {
  return <ul className="house-stats-cards" aria-label="Показатели по домам">{houses.map(h => <li key={h.house_id}>
    <h3>{h.address}</h3>
    <dl className="house-stats-main">
      <div><dt>Открыто</dt><dd>{formatNumber(h.tickets_open)}</dd></div>
      <div><dt>Закрыто</dt><dd>{formatNumber(h.tickets_closed)}</dd></div>
      <div><dt>Проверка</dt><dd>{formatNumber(h.verification_confirmed)} / {formatNumber(h.verification_returned)}</dd></div>
    </dl>
    <details className="house-stats-more"><summary>Ещё показатели</summary>
      <dl className="ds-kv">
        <div className="ds-kv-row"><dt>Сигналы</dt><dd>{formatNumber(h.signals)}</dd></div>
        <div className="ds-kv-row"><dt>Проверка жителями</dt><dd>подтверждено {formatNumber(h.verification_confirmed)}, возвращено {formatNumber(h.verification_returned)}</dd></div>
        <div className="ds-kv-row"><dt>Медиана до принятия</dt><dd>{minutes(h.median_accept_minutes)}</dd></div>
        <div className="ds-kv-row"><dt>Частые категории</dt><dd>{topCategories(h)}</dd></div>
      </dl>
    </details>
  </li>)}</ul>;
}

/** Обзор платформы: УК и квоты, воронка, активность, модель и доставка. */
export function PlatformOverview({ open }: { open: (page: string) => void }) {
  const [days, setDays] = useState<Days>(7);
  const r = useRead<Schema["PlatformDashboard"]>(`/api/v1/platform/dashboard?days=${days}`);
  const data = r.error ? undefined : r.data;
  const activity = data?.activity ?? [];
  const dayList = activity.map(d => d.day);
  return <>
    <Title description="Подключённые УК, квоты чатов и работа системы по данным базы">Обзор</Title>
    <div className="dashboard-controls"><PeriodSwitch value={days} onChange={setDays} /></div>
    <Feedback loading={r.loading && !data} error={r.error} />
    {data && <div className={r.loading ? "dashboard is-refreshing" : "dashboard"}>
      <dl className="stat-row">
        <StatTile label="УК работают" value={formatNumber(data.totals.companies_active)}
          note={data.totals.companies_suspended ? `приостановлено: ${formatNumber(data.totals.companies_suspended)}` : undefined} />
        <StatTile label="Заявки УК ждут решения" value={<button type="button" className="stat-link" onClick={() => open("applications")}>{formatNumber(data.totals.applications_pending)}</button>} />
        <StatTile label="Запросы на расширение" value={<button type="button" className="stat-link" onClick={() => open("quota-requests")}>{formatNumber(data.totals.quota_requests_pending)}</button>} />
        <StatTile label="Чаты подключены" value={formatNumber(data.totals.chats_active)} note={`подключались всего: ${formatNumber(data.totals.chats_total)}`} />
        <StatTile label="Дома в управлении" value={formatNumber(data.totals.houses)} note={`с открытым доступом: ${formatNumber(data.totals.open_houses)}`} />
        {(data.totals.houses_without_region ?? 0) > 0 && <StatTile label="Регион не задан" value={<button type="button" className="stat-link" onClick={() => open("houses")}>{formatNumber(data.totals.houses_without_region ?? 0)}</button>} note="такие дома видят только федеральные каналы" />}
      </dl>
      <h2>Управляющие компании</h2>
      {data.companies.length === 0 ? <p className="state-panel">Организаций пока нет. Они появляются после одобрения заявки УК.</p> :
        <div className="table-scroll"><table className="data-table">
          <thead><tr><th scope="col">УК</th><th scope="col">Статус</th><th scope="col">Чаты: использовано / выдано</th>
            <th scope="col">Дома</th><th scope="col">Запросы</th></tr></thead>
          <tbody>{data.companies.map(c => <tr key={c.company_id}>
            <th scope="row">{c.name}</th><td>{c.status === "active" ? "Действует" : c.status === "suspended" ? "Приостановлена" : c.status}</td>
            <td><QuotaMeter quota={c.quota} label="" /></td><td>{formatNumber(c.houses)}</td>
            <td>{c.pending_quota_requests ? `${formatNumber(c.pending_quota_requests)} ждёт` : "—"}</td>
          </tr>)}</tbody></table></div>}
      <h2>Воронка подключения</h2>
      <p className="muted">За всё время, по заявкам УК</p>
      <Funnel steps={[
        { label: "Заявки", value: data.funnel.applications },
        { label: "Одобрены", value: data.funnel.approved },
        { label: "Подключён первый чат", value: data.funnel.first_chat },
        { label: "Первая заявка в работе", value: data.funnel.first_ticket },
      ]} />
      <h2>Активность за {days} дней</h2>
      <div className="chart-grid-2">
        <ColumnChart title="Реплики в окнах разбора" description="Сообщения домовых чатов, попавшие в разбор"
          days={dayList} series={[{ key: "lines", label: "Реплики", color: SERIES.primary, values: activity.map(d => d.lines) }]} />
        <ColumnChart title="Окна разбора" days={dayList}
          series={[{ key: "windows", label: "Окна", color: SERIES.primary, values: activity.map(d => d.windows) }]} />
        <ColumnChart title="Сигналы по силе" description={`Ещё отсеяно в аудит: ${formatNumber(activity.reduce((s, d) => s + d.signals_audit, 0))}`}
          days={dayList} stacked series={[
            { key: "weak", label: "Слабые", color: STRENGTH.weak, values: activity.map(d => d.signals_weak) },
            { key: "medium", label: "Средние", color: STRENGTH.medium, values: activity.map(d => d.signals_medium) },
            { key: "strong", label: "Сильные", color: STRENGTH.strong, values: activity.map(d => d.signals_strong) },
            { key: "critical", label: "Опасность", color: STRENGTH.critical, values: activity.map(d => d.signals_critical) },
          ]} />
        <ColumnChart title="Заявки УК" days={dayList} series={[
          { key: "created", label: "Создано", color: SERIES.primary, values: activity.map(d => d.tickets_created) },
          { key: "closed", label: "Закрыто", color: SERIES.secondary, values: activity.map(d => d.tickets_closed) },
        ]} />
      </div>
      <h2>Модель</h2>
      <dl className="stat-row">
        <StatTile label="Вызовы модели" value={formatNumber(data.model.calls)} note={`стоимость известна у ${formatNumber(data.model.calls_with_cost)}`} />
        <StatTile label="Стоимость" value={rub.format(data.model.cost_rub)} />
        <StatTile label="Дневной бюджет вызовов" value={formatNumber(data.model.daily_budget)}
          note={data.model.days.length ? `сегодня использовано ${percent.format(data.model.days[data.model.days.length - 1].budget_share ?? 0)}` : undefined} />
      </dl>
      <ColumnChart title="Вызовы модели по дням" days={data.model.days.map(d => d.day)}
        series={[{ key: "calls", label: "Вызовы", color: SERIES.primary, values: data.model.days.map(d => d.calls) }]} />
      {data.model.by_company.length > 0 && <div className="table-scroll"><table className="data-table">
        <thead><tr><th scope="col">УК (через дом)</th><th scope="col">Вызовы</th><th scope="col">Стоимость</th></tr></thead>
        <tbody>{data.model.by_company.map(c => <tr key={c.company_id ?? "none"}><th scope="row">{c.company_name}</th>
          <td>{formatNumber(c.calls)}</td><td>{rub.format(c.cost_rub)}</td></tr>)}</tbody></table></div>}
      <h2>Доставка сообщений MAX</h2>
      <dl className="stat-row">
        <StatTile label="Приняты MAX" value={formatNumber(data.delivery.accepted)} />
        <StatTile label="Ошибка" value={formatNumber(data.delivery.failed)} />
        <StatTile label="Исход неизвестен" value={formatNumber(data.delivery.unknown)} />
        <StatTile label="В работе" value={formatNumber(data.delivery.in_flight)} />
      </dl>
      <p className="muted">«Принято» — MAX принял сообщение к отправке; это не подтверждение прочтения. Сутки — по московскому времени.</p>
      {data.queue && <QueueHealthBlock queue={data.queue} />}
      {(data.directory?.length ?? 0) > 0 && <DirectoryReadiness packs={data.directory ?? []} />}
    </div>}
  </>;
}

const POOL_LABELS: Record<string, string> = { operational: "Операционный пул", ai: "Пул модели" };

function seconds(value: number | null | undefined): string {
  if (value === null || value === undefined) return "очередь пуста";
  return value < 90 ? `ждёт ${formatNumber(Math.round(value))} с` : `ждёт ${formatNumber(Math.round(value / 60))} мин`;
}

/** D5: здоровье очереди — ожидающие задачи, доля окон у правил, бюджет модели. */
function QueueHealthBlock({ queue }: { queue: Schema["QueueHealth"] }) {
  const windows = queue.windows_24h;
  return <section className="ds-section" aria-labelledby="queue-health">
    <h2 id="queue-health">Очередь задач</h2>
    <dl className="stat-row">
      {queue.pools.map(pool => <StatTile key={pool.pool} label={POOL_LABELS[pool.pool] ?? pool.pool}
        value={formatNumber(pool.due)} note={`${seconds(pool.oldest_due_seconds)} · в работе ${formatNumber(pool.leased)} · отложено ${formatNumber(pool.scheduled)}`} />)}
      <StatTile label="Доставки ждут отправки" value={formatNumber(queue.deliveries_due)} />
      <StatTile label="Окна у правил из-за перегрузки или бюджета, 24 ч"
        value={windows.share_rules_overload_or_budget === null || windows.share_rules_overload_or_budget === undefined
          ? "—" : percent.format(windows.share_rules_overload_or_budget)}
        note={`${formatNumber(windows.by_rules_overload_or_budget)} из ${formatNumber(windows.total)}: сторож ${formatNumber(windows.watchdog)}, бюджет ${formatNumber(windows.budget)}, перегрузка ${formatNumber(windows.provider_overload)}`} />
      <StatTile label="Бюджет модели сегодня" value={`${formatNumber(queue.model_budget_today.used)} из ${formatNumber(queue.model_budget_today.limit)}`}
        note={queue.model_budget_today.share === null || queue.model_budget_today.share === undefined ? undefined : percent.format(queue.model_budget_today.share)} />
    </dl>
    <p className="muted">Опасность распознают правила при приёме, без очереди модели: окна, не разобранные моделью, разбирают правила.</p>
  </section>;
}

/** D5 (аудит Р-3): готовность справочника по пакетам регионов. */
function DirectoryReadiness({ packs }: { packs: Schema["DirectoryPackReadiness"][] }) {
  return <section className="ds-section" aria-labelledby="directory-readiness">
    <h2 id="directory-readiness">Справочник регионов</h2>
    <div className="table-scroll"><table className="data-table">
      <thead><tr><th scope="col">Пакет</th><th scope="col">Версия</th><th scope="col">Проверено</th><th scope="col">Ждёт сверки</th>
        <th scope="col">Старше 180 дней</th><th scope="col">Недоступны в регионе</th></tr></thead>
      <tbody>{packs.map(pack => <tr key={pack.pack}><th scope="row">{pack.name} <span className="muted">{pack.pack}</span></th>
        <td>{pack.version}</td><td>{formatNumber(pack.verified)}</td><td>{formatNumber(pack.needs_verification)}</td>
        <td>{formatNumber(pack.stale)}</td><td>{pack.unavailable_channels.length ? pack.unavailable_channels.join(", ") : "—"}</td></tr>)}</tbody>
    </table></div>
    <p className="muted">Жителю показываются только проверенные записи; «ждёт сверки» хранится и не показывается.</p>
  </section>;
}
