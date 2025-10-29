import React from "react";

const devices = [
  { device: "Desktop", share: 52 },
  { device: "Mobile", share: 42 },
  { device: "Tablet", share: 6 },
];

export const DeviceBreakdown: React.FC = () => (
  <div className="rounded border border-slate-200 bg-white p-4 shadow-sm">
    <div className="mb-2 text-sm font-semibold text-slate-600">Device Breakdown</div>
    <ul className="space-y-2 text-sm">
      {devices.map((row) => (
        <li key={row.device} className="flex items-center justify-between">
          <span>{row.device}</span>
          <span className="font-semibold">{row.share}%</span>
        </li>
      ))}
    </ul>
  </div>
);
