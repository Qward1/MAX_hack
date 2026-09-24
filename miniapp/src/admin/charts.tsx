import { useEffect, useId, useRef, useState, type ReactNode } from "react";

/**
 * Лёгкие SVG-графики дашбордов (D2) без внешних библиотек.
 * Палитра проверена валидатором dataviz на белой поверхности: две серии —
 * синий действия #235dcc и оранжевый #eb6834; сила сигнала — порядковая
 * шкала одного синего тона (светлее — слабее). Текст — только цветами текста.
 */
export const SERIES = { primary: "#235dcc", secondary: "#eb6834" } as const;
export const STRENGTH = { weak: "#86b6ef", medium: "#3987e5", strong: "#1c5cab", critical: "#0d366b" } as const;

export type Series = { key: string; label: string; color: string; values: number[] };

const dayFormat = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "short" });
export function dayLabel(value: string) {
  return dayFormat.format(new Date(`${value}T12:00:00`)).replace(".", "");
}
const number = new Intl.NumberFormat("ru-RU");
export const formatNumber = (value: number) => number.format(value);

function niceMax(value: number) {
  if (value <= 4) return 4;
  const step = 10 ** Math.floor(Math.log10(value));
  for (const factor of [1, 2, 2.5, 5, 10]) if (factor * step >= value) return factor * step;
  return 10 * step;
}

/** Столбец с округлённым торцом 4px и квадратным основанием. */
function column(x: number, y: number, width: number, height: number, rounded: boolean) {
  if (height <= 0) return "";
  const r = rounded ? Math.min(4, height, width / 2) : 0;
  return `M${x},${y + height}V${y + r}Q${x},${y} ${x + r},${y}H${x + width - r}Q${x + width},${y} ${x + width},${y + r}V${y + height}Z`;
}

/** Ширина контейнера в пикселях: подписи осей остаются 11px на любом экране. */
function useWidth(fallback: number) {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(fallback);
  useEffect(() => {
    const node = ref.current;
    if (!node || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(entries => {
      const next = Math.round(entries[0]?.contentRect.width ?? 0);
      if (next > 0) setWidth(next);
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  return { ref, width };
}

export function ColumnChart({ title, description, days, series, stacked = false, height = 180 }: {
  title: string; description?: string; days: string[]; series: Series[]; stacked?: boolean; height?: number;
}) {
  const id = useId();
  const [active, setActive] = useState<number | null>(null);
  const frame = useWidth(640);
  const width = Math.max(frame.width, 240), top = 12, bottom = 26, left = 34, right = 8;
  const plotH = height - top - bottom, plotW = width - left - right;
  const totals = days.map((_, i) => stacked ? series.reduce((s, x) => s + x.values[i], 0) : Math.max(0, ...series.map(x => x.values[i])));
  const max = niceMax(Math.max(0, ...totals));
  const band = plotW / Math.max(days.length, 1);
  const groupW = Math.min(stacked ? 24 : 24 * series.length + 2 * (series.length - 1), band * 0.7);
  const barW = stacked ? groupW : Math.max(2, (groupW - 2 * (series.length - 1)) / series.length);
  const scale = (v: number) => (v / max) * plotH;
  const ticks = [0, max / 2, max];
  // Подпись дня не чаще, чем помещается: ~46px на подпись.
  const labelEvery = Math.max(1, Math.ceil(days.length / Math.max(1, Math.floor(plotW / 46))));
  const empty = totals.every(t => t === 0);
  return <figure className="chart" aria-labelledby={`${id}-title`}>
    <figcaption><h3 id={`${id}-title`}>{title}</h3>{description && <p className="muted">{description}</p>}</figcaption>
    {series.length > 1 && <ul className="chart-legend">{series.map(s => <li key={s.key}>
      <span className="chart-swatch" style={{ background: s.color }} aria-hidden="true" />{s.label}</li>)}</ul>}
    <div className="chart-frame" ref={frame.ref} onPointerLeave={() => setActive(null)}>
      <svg viewBox={`0 0 ${width} ${height}`} width="100%" height={height} role="img" aria-label={`${title}: ${empty ? "за период событий нет" : `максимум ${formatNumber(Math.max(...totals))} в день`}`}>
        {ticks.map(t => <g key={t}>
          <line x1={left} x2={width - right} y1={top + plotH - scale(t)} y2={top + plotH - scale(t)} className="chart-grid" />
          <text x={left - 6} y={top + plotH - scale(t) + 4} textAnchor="end" className="chart-tick">{formatNumber(Math.round(t))}</text>
        </g>)}
        {days.map((day, i) => {
          const center = left + band * i + band / 2;
          let stackY = top + plotH;
          return <g key={day}>
            {series.map((s, k) => {
              const h = scale(s.values[i]);
              if (stacked) {
                const last = series.slice(k + 1).every(n => n.values[i] === 0);
                const gap = h > 0 && stackY < top + plotH ? 2 : 0;
                const y = stackY - h;
                stackY = y;
                return <path key={s.key} d={column(center - groupW / 2, y, groupW, Math.max(0, h - gap), last)} fill={s.color} />;
              }
              const x = center - groupW / 2 + k * (barW + 2);
              return <path key={s.key} d={column(x, top + plotH - h, barW, h, true)} fill={s.color} />;
            })}
            {i % labelEvery === 0 && <text x={center} y={height - 8} textAnchor="middle" className="chart-tick">{dayLabel(day)}</text>}
            <rect x={left + band * i} y={top} width={band} height={plotH} className={`chart-hit ${active === i ? "is-active" : ""}`}
              tabIndex={0} aria-label={`${dayLabel(day)}: ${series.map(s => `${s.label} ${formatNumber(s.values[i])}`).join(", ")}`}
              onPointerEnter={() => setActive(i)} onFocus={() => setActive(i)} onBlur={() => setActive(null)} />
          </g>;
        })}
        <line x1={left} x2={width - right} y1={top + plotH} y2={top + plotH} className="chart-axis" />
      </svg>
      {active !== null && <div className="chart-tooltip" role="status"
        style={{ left: `${((left + band * active + band / 2) / width) * 100}%` }}>
        <strong>{dayLabel(days[active])}</strong>
        {series.map(s => <span key={s.key}><i style={{ background: s.color }} aria-hidden="true" /><b>{formatNumber(s.values[active])}</b> {s.label}</span>)}
      </div>}
      {empty && <p className="chart-empty">За выбранный период событий нет</p>}
    </div>
    <details className="chart-table"><summary>Таблица значений</summary>
      <table><thead><tr><th scope="col">День</th>{series.map(s => <th scope="col" key={s.key}>{s.label}</th>)}</tr></thead>
        <tbody>{days.map((day, i) => <tr key={day}><th scope="row">{dayLabel(day)}</th>{series.map(s => <td key={s.key}>{formatNumber(s.values[i])}</td>)}</tr>)}</tbody></table>
    </details>
  </figure>;
}

/** Квота чатов: заполнение одним тоном на светлой дорожке того же тона. */
export function QuotaMeter({ quota, label = "Чаты" }: { quota: { limit?: number | null; used: number; remaining?: number | null; over_limit: boolean; exhausted: boolean }; label?: string }) {
  const limit = quota.limit ?? null;
  const share = limit === null ? 0 : limit === 0 ? 1 : Math.min(1, quota.used / limit);
  const state = quota.over_limit ? "over" : quota.exhausted ? "full" : "ok";
  return <div className={`quota-meter quota-${state}`}>
    <p className="quota-value">{label && <span>{label}: </span>}<strong>{limit === null ? `${formatNumber(quota.used)}, квота без ограничения` : `${formatNumber(quota.used)} из ${formatNumber(limit)}`}</strong></p>
    {limit !== null && <div className="quota-track" role="meter" aria-valuemin={0} aria-valuemax={limit} aria-valuenow={quota.used}
      aria-label={`${label || "Чаты"}: ${quota.used} из ${limit}`}><span style={{ width: `${share * 100}%` }} /></div>}
    {state === "over" && <p className="quota-note"><span aria-hidden="true">⚠</span> Квота снижена ниже числа подключённых чатов: они работают, новые не подключаются.</p>}
    {state === "full" && <p className="quota-note"><span aria-hidden="true">●</span> Свободных слотов нет — новые чаты не подключаются.</p>}
  </div>;
}

export function Funnel({ steps }: { steps: { label: string; value: number }[] }) {
  const max = Math.max(1, ...steps.map(s => s.value));
  return <ol className="funnel">{steps.map(step => <li key={step.label}>
    <span className="funnel-label">{step.label}</span>
    <span className="funnel-bar"><span style={{ width: `${(step.value / max) * 100}%` }} /></span>
    <strong>{formatNumber(step.value)}</strong>
  </li>)}</ol>;
}

export function StatTile({ label, value, note }: { label: string; value: ReactNode; note?: ReactNode }) {
  return <div className="stat-tile"><dt>{label}</dt><dd>{value}</dd>{note && <p className="muted">{note}</p>}</div>;
}

export function PeriodSwitch({ value, onChange }: { value: number; onChange: (days: 7 | 14 | 30) => void }) {
  return <div className="period-switch" role="group" aria-label="Период">
    {([7, 14, 30] as const).map(days => <button key={days} type="button" className="ticket-button secondary"
      aria-pressed={value === days} onClick={() => onChange(days)}>{days} дней</button>)}
  </div>;
}
