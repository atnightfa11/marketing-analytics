import React from "react";

const sources = [
  { source: "Organic Search", share: 38 },
  { source: "Paid Search", share: 24 },
  { source: "Social", share: 18 },
  { source: "Referral", share: 12 },
  { source: "Direct", share: 8 },
];

export const TopSources: React.FC = () => (
  <div className="rounded border border-slate-200 bg-white p-4 shadow-sm">
    <div className="mb-2 text-sm font-semibold text-slate-600">Top Sources</div>
    <ul className="space-y-2 text-sm">
      {sources.map((row) => (
        <li key={row.source} className="flex items-center justify-between">
          <span>{row.source}</span>
          <span className="font-semibold">{row.share}%</span>
        </li>
      ))}
    </ul>
  </div>
);
