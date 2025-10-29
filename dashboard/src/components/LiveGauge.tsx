import React, { useEffect, useState } from "react";

export const LiveGauge: React.FC = () => {
  const [value, setValue] = useState(0);
  const [status, setStatus] = useState<"online" | "offline">("online");

  useEffect(() => {
    const interval = setInterval(() => {
      setValue((v) => Math.max(0, v + (Math.random() - 0.5) * 5));
    }, 3000);
    const heartbeat = setInterval(() => {
      setStatus(Math.random() > 0.05 ? "online" : "offline");
    }, 10000);
    return () => {
      clearInterval(interval);
      clearInterval(heartbeat);
    };
  }, []);

  return (
    <div className="flex items-center justify-between rounded border p-4">
      <div>
        <div className="text-sm text-slate-500">Live events (last 3 minutes)</div>
        <div className="text-3xl font-semibold">{Math.round(value)}</div>
      </div>
      <div className="text-sm">
        <span
          className={`mr-2 inline-block h-2 w-2 rounded-full ${status === "online" ? "bg-emerald-500" : "bg-rose-500"}`}
        />
        {status === "online" ? "Online" : "Delayed"}
      </div>
    </div>
  );
};
