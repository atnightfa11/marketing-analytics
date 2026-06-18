import React from "react";

export const DeviceIcon: React.FC<{ label: string }> = ({ label }) => {
  const commonProps = {
    width: 14,
    height: 14,
    viewBox: "0 0 14 14",
    fill: "none",
    stroke: "#94A3B8",
    strokeWidth: 1.3,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
  };

  if (label === "Mobile") {
    return (
      <svg {...commonProps}>
        <rect x="4" y="1.5" width="6" height="11" rx="1.6" />
        <path d="M6.3 10.2h1.4" />
      </svg>
    );
  }

  if (label === "Tablet") {
    return (
      <svg {...commonProps}>
        <rect x="2.7" y="1.7" width="8.6" height="10.6" rx="1.2" />
        <path d="M6.2 10.4h1.6" />
      </svg>
    );
  }

  return (
    <svg {...commonProps}>
      <rect x="1.7" y="2" width="10.6" height="7" rx="1" />
      <path d="M4.7 11.5h4.6" />
      <path d="M7 9v2.5" />
    </svg>
  );
};

export const SunIcon: React.FC = () => (
  <svg
    width="14"
    height="14"
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.4"
    strokeLinecap="round"
    aria-hidden="true"
  >
    <circle cx="8" cy="8" r="3" />
    <line x1="8" y1="1.5" x2="8" y2="3" />
    <line x1="8" y1="13" x2="8" y2="14.5" />
    <line x1="1.5" y1="8" x2="3" y2="8" />
    <line x1="13" y1="8" x2="14.5" y2="8" />
    <line x1="3.4" y1="3.4" x2="4.4" y2="4.4" />
    <line x1="11.6" y1="11.6" x2="12.6" y2="12.6" />
    <line x1="3.4" y1="12.6" x2="4.4" y2="11.6" />
    <line x1="11.6" y1="4.4" x2="12.6" y2="3.4" />
  </svg>
);

export const MoonIcon: React.FC = () => (
  <svg
    width="14"
    height="14"
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.4"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    <path d="M13.5 9.5A5.5 5.5 0 1 1 6.5 2.5 a4.5 4.5 0 0 0 7 7Z" />
  </svg>
);

export const ExpandIcon: React.FC = () => (
  <svg
    width="14"
    height="14"
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.5"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    <polyline points="3 6.5 3 3 6.5 3" />
    <polyline points="9.5 3 13 3 13 6.5" />
    <polyline points="13 9.5 13 13 9.5 13" />
    <polyline points="6.5 13 3 13 3 9.5" />
  </svg>
);

export const CloseIcon: React.FC = () => (
  <svg
    width="14"
    height="14"
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.5"
    strokeLinecap="round"
    aria-hidden="true"
  >
    <line x1="4" y1="4" x2="12" y2="12" />
    <line x1="12" y1="4" x2="4" y2="12" />
  </svg>
);
