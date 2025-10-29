import React from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Tooltip,
  XAxis,
  YAxis,
  ResponsiveContainer,
} from "recharts";
import { ForecastEntry } from "../api";
import { formatNumber, formatShortDate } from "../utils/format";

interface Props {
  metric: string;
  data: ForecastEntry[];
}

export const ForecastChart: React.FC<Props> = ({ metric, data }) => (
  <div className="rounded border border-slate-200 bg-white p-4 shadow-sm">
    <div className="mb-2 text-sm text-slate-500 uppercase tracking-wide">
      Forecast: {metric}
    </div>
    {data.length === 0 ? (
      <div className="text-sm text-slate-400">Forecast unavailable (need 60+ days of history).</div>
    ) : (
      <ResponsiveContainer width="100%" height={260}>
        <AreaChart data={data}>
          <defs>
            <linearGradient id="forecastBand" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#4f46e5" stopOpacity={0.3} />
              <stop offset="95%" stopColor="#4f46e5" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="day" tickFormatter={formatShortDate} />
          <YAxis tickFormatter={formatNumber} />
          <Tooltip
            formatter={(value: number) => formatNumber(value)}
            labelFormatter={(label) => `Day ${label}`}
          />
          <Area type="monotone" dataKey="yhat" stroke="#4f46e5" fill="url(#forecastBand)" />
          <Area type="monotone" dataKey="yhat_upper" stroke="#a855f7" fillOpacity={0} />
          <Area type="monotone" dataKey="yhat_lower" stroke="#22d3ee" fillOpacity={0} />
        </AreaChart>
      </ResponsiveContainer>
    )}
    <p className="mt-2 text-xs text-slate-400">
      Bounds derived from Prophet + EWMA anomaly guard.
    </p>
  </div>
);
