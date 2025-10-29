import React from "react";

const countries = [
  { country: "US", share: 45 },
  { country: "GB", share: 15 },
  { country: "DE", share: 12 },
  { country: "CA", share: 10 },
  { country: "FR", share: 6 },
];

export const TopCountries: React.FC = () => (
  <div className="rounded border border-slate-200 bg-white p-4 shadow-sm">
    <div className="mb-2 text-sm font-semibold text-slate-600">Top Countries</div>
    <ul className="space-y-2 text-sm">
      {countries.map((row) => (
        <li key={row.country} className="flex items-center justify-between">
          <span>{row.country}</span>
          <span className="font-semibold">{row.share}%</span>
        </li>
      ))}
    </ul>
  </div>
);
