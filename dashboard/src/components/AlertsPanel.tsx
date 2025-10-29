import React, { useEffect, useState } from "react";

interface Alert {
  id: string;
  severity: "info" | "warning" | "critical";
  message: string;
  timestamp: string;
}

const severityColor: Record<Alert["severity"], string> = {
  info: "bg-sky-100 text-sky-800",
  warning: "bg-amber-100 text-amber-800",
  critical: "bg-rose-100 text-rose-800",
};

export const AlertsPanel: React.FC = () => {
  const [alerts, setAlerts] = useState<Alert[]>([]);

  useEffect(() => {
    setAlerts([
      {
        id: "1",
        severity: "warning",
        message: "Landing page conversions dipped below SNR guard.",
        timestamp: new Date().toISOString(),
      },
    ]);
  }, []);

  return (
    <div className="space-y-3 rounded border border-slate-200 bg-white p-4 shadow-sm">
      <div className="text-sm font-semibold text-slate-600">Recent Alerts</div>
      {alerts.length === 0 ? (
        <div className="text-sm text-slate-400">No alerts.</div>
      ) : (
        alerts.map((alert) => (
          <div key={alert.id} className={`rounded px-3 py-2 text-sm ${severityColor[alert.severity]}`}>
            <div className="font-medium">{alert.message}</div>
            <div className="text-xs opacity-70">{new Date(alert.timestamp).toLocaleString()}</div>
          </div>
        ))
      )}
    </div>
  );
};
