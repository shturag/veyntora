/**
 * A Grafana dashboard drawn with Monitoring's own charts: Veyntora reads the panels' data
 * through Grafana's API (with the service-account token from Integrations), so nobody
 * needs a Grafana login and nothing is framed. Time series are lines, stat and gauge
 * panels are numbers, tables are tables; other panel types link to Grafana.
 */
import { getFormatter, getTranslations } from "next-intl/server";
import type { CSSProperties } from "react";

type Series = { name: string; points: [number, number | null][] };
type Panel = {
  id: number | null;
  title: string;
  type: string;
  kind: "timeseries" | "stat" | "table" | "unsupported";
  unit: string | null;
  width: number;
  series: Series[];
  table: { columns: string[]; rows: unknown[][] } | null;
  error: string | null;
};
export type GrafanaDashboardData = {
  uid: string;
  title: string;
  url: string;
  start: number;
  end: number;
  panels: Panel[];
};

type Format = Awaited<ReturnType<typeof getFormatter>>;

const STROKES = [
  "stroke-series-1",
  "stroke-series-2",
  "stroke-series-3",
  "stroke-series-4",
  "stroke-series-5",
  "stroke-series-6",
  "stroke-series-7",
  "stroke-series-8",
];
const FILLS = [
  "fill-series-1",
  "fill-series-2",
  "fill-series-3",
  "fill-series-4",
  "fill-series-5",
  "fill-series-6",
  "fill-series-7",
  "fill-series-8",
];
const SWATCHES = [
  "bg-series-1",
  "bg-series-2",
  "bg-series-3",
  "bg-series-4",
  "bg-series-5",
  "bg-series-6",
  "bg-series-7",
  "bg-series-8",
];

/** A value in the panel's unit (Grafana's unit ids; the common ones). */
function valueOf(format: Format, v: number | null | undefined, unit: string | null) {
  if (v === null || v === undefined) return "—";
  // Small values keep two significant digits instead of rounding to 0.
  const n = (x: number, digits = 2) =>
    x !== 0 && Math.abs(x) < 1
      ? format.number(x, { maximumSignificantDigits: 2 })
      : format.number(x, { maximumFractionDigits: digits });
  switch (unit) {
    case "percent":
      return `${n(v, 1)} %`;
    case "percentunit":
      return format.number(v, { style: "percent", maximumFractionDigits: 1 });
    case "s":
      return v < 1 ? `${n(v * 1000, 0)} ms` : `${n(v, 1)} s`;
    case "ms":
      return v >= 1000 ? `${n(v / 1000, 1)} s` : `${n(v, 0)} ms`;
    case "bytes":
    case "decbytes": {
      const base = unit === "bytes" ? 1024 : 1000;
      const units = ["B", "KB", "MB", "GB", "TB"];
      let i = 0;
      let x = v;
      while (Math.abs(x) >= base && i < units.length - 1) {
        x /= base;
        i += 1;
      }
      return `${n(x, 1)} ${units[i]}`;
    }
    case "reqps":
      return `${n(v)} req/s`;
    case "ops":
      return `${n(v)} ops/s`;
    default:
      return format.number(v, { notation: "compact", maximumFractionDigits: 2 });
  }
}

function last(s: Series) {
  for (let i = s.points.length - 1; i >= 0; i -= 1)
    if (s.points[i]![1] !== null) return s.points[i]![1];
  return null;
}

const H = 180;
const PAD = { top: 8, right: 8, bottom: 22, left: 60 };

function Timeseries({
  panel,
  window: [t0, t1],
  span,
  format,
  labels,
}: {
  panel: Panel;
  /** The dashboard's time range (epoch ms): Grafana draws the whole range too. */
  window: [number, number];
  /** Columns of 12: the drawing keeps its text the same size in narrow panels. */
  span: number;
  format: Format;
  labels: { table: string; series: string; latest: string; min: string; max: string; time: string };
}) {
  // About the panel's width on screen (a column is ~100 px), so labels keep their size.
  const W = Math.max(360, span * 100);
  const series = panel.series;
  const all = series.flatMap((s) => s.points);
  const values = all.map((p) => p[1]).filter((v): v is number => v !== null);
  if (!values.length) return null;
  const lo = Math.min(0, ...values);
  const top = Math.max(...values);
  // A flat line still gets a scale: three distinct gridline labels.
  const hi = top > lo ? top : lo + 1;
  const plotW = W - PAD.left - PAD.right;
  const plotH = H - PAD.top - PAD.bottom;
  // Grafana aligns points to its step, so the first may fall just before the range.
  const x = (t: number) => PAD.left + Math.min(1, Math.max(0, (t - t0) / (t1 - t0))) * plotW;
  const y = (v: number) => PAD.top + plotH - ((v - lo) / (hi - lo)) * plotH;
  const duration = t1 - t0;
  const tick = (t: number) =>
    duration > 36 * 3600_000
      ? format.dateTime(new Date(t), { day: "numeric", month: "short" })
      : format.dateTime(new Date(t), { hour: "2-digit", minute: "2-digit" });
  // A line per series, broken where Grafana has no value.
  const path = (s: Series) => {
    let d = "";
    let pen = false;
    for (const [t, v] of s.points) {
      if (v === null) {
        pen = false;
        continue;
      }
      d += `${pen ? "L" : "M"}${x(t).toFixed(1)},${y(v).toFixed(1)}`;
      pen = true;
    }
    return d;
  };
  // Hover: one band per timestamp of the first series, naming every series' value there.
  const first = series[0]!.points;
  const byTime = series.map((s) => new Map(s.points));
  const band = plotW / Math.max(1, first.length);
  return (
    <figure className="m-0 flex flex-col gap-2">
      {series.length > 1 ? (
        <ul
          className="m-0 flex list-none flex-wrap gap-x-4 gap-y-1 p-0 text-xs text-fg-secondary"
          aria-hidden
        >
          {series.map((s, i) => (
            <li key={s.name + i} className="flex items-center gap-1.5">
              <span className={`inline-block h-0.5 w-3 rounded-full ${SWATCHES[i]}`} />
              {s.name}
            </li>
          ))}
        </ul>
      ) : null}
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={panel.title} className="h-auto w-full">
        {[0, 0.5, 1].map((f) => {
          const v = lo + f * (hi - lo);
          return (
            <g key={f}>
              <line
                x1={PAD.left}
                x2={W - PAD.right}
                y1={y(v)}
                y2={y(v)}
                className="stroke-line"
                strokeWidth={1}
              />
              <text
                x={PAD.left - 6}
                y={y(v) + 4}
                textAnchor="end"
                className="fill-fg-muted text-[11px]"
              >
                {valueOf(format, v, panel.unit)}
              </text>
            </g>
          );
        })}
        {[0, 0.25, 0.5, 0.75, 1].map((f) => (
          <text
            key={f}
            x={PAD.left + f * plotW}
            y={H - 6}
            textAnchor={f === 0 ? "start" : f === 1 ? "end" : "middle"}
            className="fill-fg-muted text-[11px]"
          >
            {tick(t0 + f * duration)}
          </text>
        ))}
        {series.map((s, i) => (
          <g key={s.name + i}>
            <path
              d={path(s)}
              fill="none"
              strokeWidth={2}
              strokeLinejoin="round"
              strokeLinecap="round"
              className={STROKES[i]}
            />
            {/* A value with gaps on both sides has no line: show it as a dot. */}
            {s.points.map(([t, v], j) =>
              v !== null && s.points[j - 1]?.[1] == null && s.points[j + 1]?.[1] == null ? (
                <circle key={t} cx={x(t)} cy={y(v)} r={2.5} className={FILLS[i]} />
              ) : null,
            )}
          </g>
        ))}
        {first.map(([t]) => (
          <rect
            key={t}
            x={x(t) - band / 2}
            y={PAD.top}
            width={band}
            height={plotH}
            fill="transparent"
          >
            <title>
              {[
                tick(t),
                ...series.map(
                  (s, j) =>
                    `${s.name || panel.title}: ${valueOf(format, byTime[j]!.get(t), panel.unit)}`,
                ),
              ].join("\n")}
            </title>
          </rect>
        ))}
      </svg>
      <details className="text-xs">
        <summary className="cursor-pointer text-fg-secondary">{labels.table}</summary>
        <table className="mt-2 w-full border-collapse">
          <thead>
            <tr className="text-left text-fg-muted">
              <th className="py-1 font-medium">{labels.series}</th>
              <th className="py-1 text-right font-medium">{labels.latest}</th>
              <th className="py-1 text-right font-medium">{labels.min}</th>
              <th className="py-1 text-right font-medium">{labels.max}</th>
            </tr>
          </thead>
          <tbody>
            {series.map((s, i) => {
              const vs = s.points.map((p) => p[1]).filter((v): v is number => v !== null);
              return (
                <tr key={s.name + i} className="border-t border-line">
                  <td className="py-1">{s.name || panel.title}</td>
                  <td className="py-1 text-right tabular-nums">
                    {valueOf(format, last(s), panel.unit)}
                  </td>
                  <td className="py-1 text-right tabular-nums">
                    {valueOf(format, vs.length ? Math.min(...vs) : null, panel.unit)}
                  </td>
                  <td className="py-1 text-right tabular-nums">
                    {valueOf(format, vs.length ? Math.max(...vs) : null, panel.unit)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </details>
    </figure>
  );
}

function Cell({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <>—</>;
  return <>{typeof value === "object" ? JSON.stringify(value) : String(value)}</>;
}

export async function GrafanaDashboard({ dashboard }: { dashboard: GrafanaDashboardData }) {
  const t = await getTranslations("monitoring.grafana");
  const format = await getFormatter();
  const labels = {
    table: t("asTable"),
    series: t("series"),
    latest: t("latest"),
    min: t("min"),
    max: t("max"),
    time: t("time"),
  };
  return (
    <section aria-labelledby={`dash-${dashboard.uid}`} className="flex flex-col gap-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 id={`dash-${dashboard.uid}`} className="m-0 text-sm font-semibold">
          {dashboard.title}
        </h3>
        <a href={dashboard.url} target="_blank" rel="noreferrer" className="text-xs">
          {t("openDashboard")}
        </a>
      </div>
      {dashboard.panels.length === 0 ? (
        <p className="m-0 text-sm text-fg-secondary">{t("noPanels")}</p>
      ) : null}
      <div className="grid grid-cols-12 items-start gap-3">
        {dashboard.panels.map((p, i) => {
          const span = Math.min(12, Math.max(3, Math.round(p.width / 2)));
          return (
            <article
              key={`${p.id}-${i}`}
              style={{ "--span": span } as CSSProperties}
              className="col-span-12 flex min-w-0 flex-col gap-2 rounded-lg border border-line bg-surface p-4 min-[901px]:[grid-column:span_var(--span)/span_var(--span)]"
            >
              <h4 className="m-0 text-xs font-medium text-fg-secondary">
                {p.title || t("untitled")}
              </h4>
              {p.error ? (
                <p className="m-0 text-sm text-red">{t("panelError", { reason: p.error })}</p>
              ) : p.kind === "unsupported" ? (
                <p className="m-0 text-sm text-fg-secondary">
                  {t("unsupported", { type: p.type })}{" "}
                  <a href={dashboard.url} target="_blank" rel="noreferrer">
                    {t("openDashboard")}
                  </a>
                </p>
              ) : p.kind === "table" ? (
                p.table && p.table.rows.length ? (
                  <div className="overflow-x-auto">
                    <table className="w-full border-collapse text-xs">
                      <thead>
                        <tr className="text-left text-fg-muted">
                          {p.table.columns.map((c, j) => (
                            <th key={j} className="py-1 pr-3 font-medium">
                              {c}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {p.table.rows.map((r, j) => (
                          <tr key={j} className="border-t border-line">
                            {r.map((v, k) => (
                              <td key={k} className="py-1 pr-3 tabular-nums">
                                <Cell value={v} />
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <p className="m-0 text-sm text-fg-secondary">{t("noData")}</p>
                )
              ) : !p.series.some((s) => s.points.some((pt) => pt[1] !== null)) ? (
                <p className="m-0 text-sm text-fg-secondary">{t("noData")}</p>
              ) : p.kind === "stat" ? (
                <dl className="m-0 flex flex-wrap gap-x-6 gap-y-2">
                  {p.series.slice(0, 4).map((s, j) => (
                    <div key={s.name + j} className="flex flex-col">
                      {p.series.length > 1 ? (
                        <dt className="text-xs text-fg-muted">{s.name}</dt>
                      ) : null}
                      <dd className="m-0 text-xl font-semibold tabular-nums">
                        {valueOf(format, last(s), p.unit)}
                      </dd>
                    </div>
                  ))}
                </dl>
              ) : (
                <Timeseries
                  panel={p}
                  window={[dashboard.start, dashboard.end]}
                  span={span}
                  format={format}
                  labels={labels}
                />
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
}
