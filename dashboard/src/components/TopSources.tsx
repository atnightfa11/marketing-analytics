import React from "react";

const sources = [
  { source: "Organic Search", share: 38 },
  { source: "Paid Search", share: 24 },
  { source: "Social", share: 18 },
  { source: "Referral", share: 12 },
  { source: "Direct", share: 8 },
];

export const TopSources: React.FC = () => (
  <div className="border border-gray-200 bg-white p-4">
    <div
      className="mb-3 text-xs uppercase tracking-[0.2em] text-gray-500"
      style={{ fontFamily: '"Inter", system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif' }}
    >
      Top Sources
    </div>
    <div className="divide-y divide-gray-100 text-sm">
      {sources.map((row) => (
        <div key={row.source} className="py-2">
          <div className="flex items-center justify-between text-gray-700">
            <span>{row.source}</span>
            <span
              className="text-gray-900"
              style={{
                fontFamily:
                  '"Roboto Mono", ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace',
              }}
            >
              {row.share}%
            </span>
          </div>
          <div className="mt-1 h-1 w-full bg-gray-100">
            <div className="h-1 bg-gray-400" style={{ width: `${row.share}%` }} />
          </div>
        </div>
      ))}
    </div>
  </div>
);
