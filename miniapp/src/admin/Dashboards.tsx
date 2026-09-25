import { useState } from "react";
import { adminClient, Feedback, Title, useRead, type Schema } from "./administration";
import { ColumnChart, Funnel, PeriodSwitch, QuotaMeter, SERIES, STRENGTH, StatTile, formatNumber } from "./charts";
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

/** Обзор УК: «Чаты: N из Q», дома, динамика и выгрузка CSV. */
export function CompanyOverview({ base }: { base: string }) {
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
      <dl className="stat-row">
        <StatTile label={`Сигналы за ${days} дней`} value={formatNumber(sum("signals"))} />
        <StatTile label="Открытые заявки сейчас" value={formatNumber(sum("tickets_open"))} />
        <StatTile label="Заявки закрыты" value={formatNumber(sum("tickets_closed"))} note={`из ${formatNumber(sum("tickets_created"))} созданных за период`} />
        <StatTile label="Проверка жителями" value={`${formatNumber(sum("verification_confirmed"))} / ${formatNumber(sum("verification_returned"))}`}
          note="подтверждено / возвращено в работу" />
      </dl>
      {houses.length === 0 ? <p className="state-panel">{data.scope === "assigned"
        ? "Вы пока не назначены ни на один дом. Назначение делает администратор УК."
        : "Домов в управлении пока нет. Запросите управление домом в разделе «Дома»."}</p> : <>
        <ColumnChart title="Сигналы из чатов по дням" days={data.activity.map(d => d.day)}
          series={[{ key: "signals", label: "Сигналы", color: SERIES.primary, values: data.activity.map(d => d.signals) }]} />
        <ColumnChart title="Заявки по дням" days={data.activity.map(d => d.day)} series={[
          { key: "created", label: "Создано", color: SERIES.primary, values: data.activity.map(d => d.tickets_created) },
          { key: "closed", label: "Закрыто", color: SERIES.secondary, values: data.activity.map(d => d.tickets_closed) },
        ]} />
        <h2>По домам</h2>
        <div className="table-scroll"><table className="data-table">
          <thead><tr><th scope="col">Дом</th><th scope="col">Сигналы</th><th scope="col">Заявки открыто</th>
            <th scope="col">Закрыто</th><th scope="col">Медиана до принятия</th><th scope="col">Подтверждено</th>
            <th scope="col">Возвращено</th><th scope="col">Частые категории</th></tr></thead>
          <tbody>{houses.map(h => <tr key={h.house_id}>
            <th scope="row">{h.address}</th><td>{formatNumber(h.signals)}</td><td>{formatNumber(h.tickets_open)}</td>
            <td>{formatNumber(h.tickets_closed)}</td><td>{minutes(h.median_accept_minutes)}</td>
            <td>{formatNumber(h.verification_confirmed)}</td><td>{formatNumber(h.verification_returned)}</td>
            <td>{h.top_categories.length ? h.top_categories.map(c => `${categories[c.category] ?? c.category} (${c.count})`).join(", ") : "—"}</td>
          </tr>)}</tbody></table></div>
        <p className="muted">Сутки считаются по московскому времени. Медиана — от создания заявки до её принятия, по заявкам периода.
          Тексты жителей в обзор не попадают.</p>
      </>}
      {(data.polls ?? []).length > 0 && <section aria-label="Опросы жителей">
        <h2>Опросы жителей</h2>
        <div className="house-cards">{(data.polls ?? []).map(poll => <div className="admin-detail" key={poll.poll_id}>
          <PollResultsView poll={poll} /></div>)}</div>
      </section>}
    </div>}
  </>;
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
    </div>}
  </>;
}
