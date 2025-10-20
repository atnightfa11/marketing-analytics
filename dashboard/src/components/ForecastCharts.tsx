// Minimal prop shape Codex will follow: actual, forecast, ci bands, mape, anomaly flag
import { LineChart, Line, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'

type Point = { t: string; y: number; yhat?: number; yhat_low?: number; yhat_high?: number }
export default function ForecastChart({ data, mape, hasAnomaly }: { data: Point[]; mape?: number; hasAnomaly?: boolean }) {
  return (
    <div aria-label="Forecast chart">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-sm">MAPE: {mape?.toFixed(1) ?? '—'}%</span>
        {hasAnomaly ? <span title="Anomaly" className="text-red-600">!</span> : null}
      </div>
      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={data}>
          <XAxis dataKey="t" hide />
          <YAxis hide />
          <Tooltip />
          <Area type="monotone" dataKey="yhat_high" strokeOpacity={0} fillOpacity={0.15} />
          <Area type="monotone" dataKey="yhat_low" strokeOpacity={0} fillOpacity={0.15} />
          <Line type="monotone" dataKey="y" dot={false} />
          <Line type="monotone" dataKey="yhat" strokeDasharray="4 4" dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
