/**
 * Requests by mode over time: stacked bars (Fast below, Agent above) on one axis, with a
 * legend, a hover title per bar and the same numbers as a table.
 */

type Bucket = { at: string; fast: number; agent: number };

// Drawn near the size it is shown at, so its labels stay at the page's text size.
const W = 840;
const H = 180;
const PAD = { top: 8, right: 8, bottom: 22, left: 36 };

export function RequestsChart({
  buckets,
  label,
  legend,
  tick,
  tableLabel,
}: {
  buckets: Bucket[];
  label: string;
  legend: { fast: string; agent: string };
  tick: (iso: string) => string;
  tableLabel: { summary: string; time: string };
}) {
  const max = Math.max(1, ...buckets.map((b) => b.fast + b.agent));
  const top = niceMax(max);
  const plotW = W - PAD.left - PAD.right;
  const plotH = H - PAD.top - PAD.bottom;
  const slot = plotW / Math.max(1, buckets.length);
  const barW = Math.max(2, Math.min(24, slot - 4));
  const y = (v: number) => (v / top) * plotH;
  const every = Math.ceil(buckets.length / 10);
  return (
    <figure className="m-0 flex flex-col gap-2">
      <div className="flex gap-4 text-xs text-fg-secondary" aria-hidden>
        {(["fast", "agent"] as const).map((k, i) => (
          <span key={k} className="flex items-center gap-1.5">
            <span
              className={`inline-block size-2.5 rounded-sm ${i === 0 ? "bg-series-1" : "bg-series-2"}`}
            />
            {legend[k]}
          </span>
        ))}
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label} className="h-auto w-full">
        {[0, 0.5, 1].map((f) => (
          <g key={f}>
            <line
              x1={PAD.left}
              x2={W - PAD.right}
              y1={PAD.top + plotH - f * plotH}
              y2={PAD.top + plotH - f * plotH}
              className="stroke-line"
              strokeWidth={1}
            />
            <text
              x={PAD.left - 6}
              y={PAD.top + plotH - f * plotH + 4}
              textAnchor="end"
              className="fill-fg-muted text-[11px]"
            >
              {Math.round(f * top)}
            </text>
          </g>
        ))}
        {buckets.map((b, i) => {
          const x = PAD.left + i * slot + (slot - barW) / 2;
          const fastH = y(b.fast);
          const agentH = y(b.agent);
          const base = PAD.top + plotH;
          return (
            <g key={b.at}>
              <title>{`${tick(b.at)} · ${legend.fast} ${b.fast} · ${legend.agent} ${b.agent}`}</title>
              {/* A full-height hit target, larger than the bar. */}
              <rect
                x={PAD.left + i * slot}
                y={PAD.top}
                width={slot}
                height={plotH}
                fill="transparent"
              />
              {b.fast > 0 ? (
                <rect
                  x={x}
                  y={base - fastH}
                  width={barW}
                  height={fastH}
                  rx={2}
                  className="fill-series-1"
                />
              ) : null}
              {b.agent > 0 ? (
                <rect
                  x={x}
                  y={base - fastH - agentH - (b.fast > 0 ? 2 : 0)}
                  width={barW}
                  height={agentH}
                  rx={2}
                  className="fill-series-2"
                />
              ) : null}
              {i % every === 0 ? (
                <text
                  x={x + barW / 2}
                  y={H - 6}
                  textAnchor="middle"
                  className="fill-fg-muted text-[11px]"
                >
                  {tick(b.at)}
                </text>
              ) : null}
            </g>
          );
        })}
      </svg>
      <details className="text-xs">
        <summary className="cursor-pointer text-fg-secondary">{tableLabel.summary}</summary>
        <table className="mt-2 w-full border-collapse">
          <thead>
            <tr className="text-left text-fg-muted">
              <th className="py-1 font-medium">{tableLabel.time}</th>
              <th className="py-1 text-right font-medium">{legend.fast}</th>
              <th className="py-1 text-right font-medium">{legend.agent}</th>
            </tr>
          </thead>
          <tbody>
            {buckets.map((b) => (
              <tr key={b.at} className="border-t border-line">
                <td className="py-1">{tick(b.at)}</td>
                <td className="py-1 text-right tabular-nums">{b.fast}</td>
                <td className="py-1 text-right tabular-nums">{b.agent}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </figure>
  );
}

function niceMax(v: number) {
  // Even steps so the middle gridline is a whole number.
  const mag = 10 ** Math.floor(Math.log10(Math.max(v, 4)));
  for (const s of [2, 4, 10]) if (s * mag >= v && s * mag >= 4) return s * mag;
  return 20 * mag;
}
