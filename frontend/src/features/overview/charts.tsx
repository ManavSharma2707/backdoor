import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceArea,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { compactMoney, formatDayMonth, money, quantity, weekStartOf } from "@/lib/format";
import { overview as copy } from "@/copy/overview";
import type { TrendsResponse } from "@/types/models";

type Point = { week: string; revenue: number; units: number };

function TrendTooltip({ active, payload }: { active?: boolean; payload?: { payload: Point }[] }) {
  const point = active ? payload?.[0]?.payload : undefined;
  if (!point) return null;
  return (
    <div className="rounded-md border border-border bg-surface px-3 py-2 text-sm shadow-popover">
      <div className="font-medium">{copy.trend.tooltipWeek(formatDayMonth(point.week))}</div>
      <div className="tabular mt-1 text-text-2">
        {copy.trend.tooltipSales}: {money(point.revenue)}
      </div>
      <div className="tabular text-text-2">
        {copy.trend.tooltipUnits}: {quantity(point.units)}
      </div>
    </div>
  );
}

/** Weekly sales as one line, with festival weeks shaded and named. */
export default function SalesTrendChart({ data }: { data: TrendsResponse }) {
  const points: Point[] = data.weeks.map((week) => ({
    week: week.week_start,
    revenue: Number(week.revenue),
    units: Number(week.units),
  }));
  const first = points[0]?.week ?? "";
  const last = points[points.length - 1]?.week ?? "";
  const bands = data.festival_bands
    .map((band) => ({
      name: band.name,
      x1: weekStartOf(band.start) < first ? first : weekStartOf(band.start),
      x2: weekStartOf(band.end) > last ? last : weekStartOf(band.end),
      visible: weekStartOf(band.end) >= first && weekStartOf(band.start) <= last,
    }))
    .filter((band) => band.visible);

  return (
    <div className="h-[220px]" role="img" aria-label={copy.trend.axisLabel}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={points} margin={{ top: 18, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid vertical={false} stroke="var(--color-chart-grid)" />
          {bands.map((band) => (
            <ReferenceArea
              key={`${band.name}-${band.x1}`}
              x1={band.x1}
              x2={band.x2}
              fill="var(--color-festival-band)"
              fillOpacity={1}
              label={{
                value: band.x1 === band.x2 ? "" : band.name,
                position: "insideTop",
                fontSize: 11,
                fill: "var(--color-text-2)",
              }}
            />
          ))}
          <XAxis
            dataKey="week"
            scale="band"
            tickFormatter={(value: string) => formatDayMonth(value)}
            tick={{ fontSize: 12, fill: "var(--color-text-3)" }}
            axisLine={{ stroke: "var(--color-border-strong)" }}
            tickLine={false}
            interval="preserveStartEnd"
          />
          <YAxis
            tickFormatter={(value: number) => compactMoney(value)}
            tick={{ fontSize: 12, fill: "var(--color-text-3)" }}
            axisLine={false}
            tickLine={false}
            width={72}
            domain={[0, "auto"]}
          />
          <Tooltip content={<TrendTooltip />} />
          <Line
            type="monotone"
            dataKey="revenue"
            stroke="var(--color-chart-1)"
            strokeWidth={2}
            dot={false}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
