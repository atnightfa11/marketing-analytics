import React from "react";
import en from "../locales/en.json";

const epsilonOptions = [
  { epsilon: 0.2, description: "Max privacy, higher noise" },
  { epsilon: 0.5, description: "Balanced privacy" },
  { epsilon: 1.0, description: "Lower privacy, lower noise" },
];

export const PrivacyControls: React.FC = () => (
  <div className="space-y-4 rounded border border-slate-200 bg-white p-4 shadow-sm">
    <div>
      <h2 className="text-lg font-semibold text-slate-700">{en.privacy.title}</h2>
      <p className="text-sm text-slate-500">{en.privacy.description}</p>
    </div>
    <table className="w-full text-left text-sm">
      <thead>
        <tr className="border-b">
          <th className="py-2">{en.privacy.epsilon}</th>
          <th>{en.privacy.effect}</th>
        </tr>
      </thead>
      <tbody>
        {epsilonOptions.map((option) => (
          <tr key={option.epsilon} className="border-b last:border-none">
            <td className="py-2 font-semibold">{option.epsilon}</td>
            <td>{option.description}</td>
          </tr>
        ))}
      </tbody>
    </table>
    <div className="rounded bg-slate-100 p-3 text-xs text-slate-600">
      {en.privacy.footer}
    </div>
  </div>
);
