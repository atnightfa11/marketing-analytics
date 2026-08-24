import React, { useEffect, useState } from "react";
import type { BreakdownMetricKey } from "../api";
import { breakdownMetricInlineLabels } from "../constants";
import { CloseIcon, ExpandIcon } from "./icons";
import { fontBody, fontMetric } from "../styles/typography";
import type { ActiveFilter, BreakdownComparisonContext, BreakdownMetricTotals, BreakdownTableRow } from "../types";
import { formatMetricValue } from "../utils/format";
import {
  getBreakdownBarColor,
  getBreakdownDimensionHeaderLabel,
  getBreakdownMetricValue,
  renderBreakdownLabel,
} from "../utils/breakdowns";

export const TableBlock: React.FC<{
  title: string;
  header?: React.ReactNode;
  rows: BreakdownTableRow[];
  metricKeys: BreakdownMetricKey[];
  primaryMetric: BreakdownMetricKey;
  total?: number;
  totalsByMetric?: BreakdownMetricTotals;
  emptyState?: string;
  error?: string | null;
  rowDimension?: string;
  comparison?: BreakdownComparisonContext | null;
  activeFilters?: ActiveFilter[];
  onToggleFilter?: (dimension: string, row: BreakdownTableRow, total: number, primaryMetric: BreakdownMetricKey) => void;
}> = ({
  title,
  header,
  rows,
  metricKeys,
  primaryMetric,
  total,
  totalsByMetric,
  emptyState,
  error,
  rowDimension,
  comparison,
  activeFilters,
  onToggleFilter,
}) => {
  const [expanded, setExpanded] = useState(false);
  const shareMetric = chooseShareMetric(rowDimension, metricKeys, primaryMetric);
  const valueMetric = chooseValueMetric(rowDimension, metricKeys, shareMetric, primaryMetric);
  const maxValue = rows.reduce((max, row) => Math.max(max, getBreakdownMetricValue(row, shareMetric)), 0);
  const shareMetricTotal = totalsByMetric?.[shareMetric];
  const shareTotal =
    Number.isFinite(shareMetricTotal ?? Number.NaN)
      ? shareMetricTotal ?? 0
      : shareMetric === primaryMetric && Number.isFinite(total ?? Number.NaN)
        ? total ?? 0
        : rows.reduce((sum, row) => sum + getBreakdownMetricValue(row, shareMetric), 0);
  const comparisonRowsByLabel = new Map((comparison?.rows ?? []).map((row) => [row.label, row]));
  const comparisonShareMetricTotal = comparison?.totalsByMetric?.[shareMetric];
  const comparisonShareTotal =
    Number.isFinite(comparisonShareMetricTotal ?? Number.NaN)
      ? comparisonShareMetricTotal ?? 0
      : Number.isFinite(comparison?.total ?? Number.NaN)
        ? comparison?.total ?? 0
        : (comparison?.rows ?? []).reduce((sum, row) => sum + getBreakdownMetricValue(row, shareMetric), 0);
  const showComparison = Boolean(comparison?.comparisonLabel);

  useEffect(() => {
    if (!expanded) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setExpanded(false);
    };
    window.addEventListener("keydown", onKey);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = previousOverflow;
    };
  }, [expanded]);

  const renderRows = (compact: boolean) => {
    if (error) {
      return (
        <div className="py-6 text-xs text-[#8B2635]" style={fontBody}>
          {error}
        </div>
      );
    }
    if (rows.length === 0) {
      return (
        <div className="py-6 text-xs text-gray-400" style={fontBody}>
          {emptyState ?? "Awaiting events. This table will populate after data arrives."}
        </div>
      );
    }
    const dimensionLabel = getBreakdownDimensionHeaderLabel(title, rowDimension);
    const gridTemplateColumns = compact
      ? "minmax(0,1fr) minmax(58px,auto) minmax(96px,0.8fr)"
      : "minmax(0,1.25fr) minmax(86px,auto) minmax(160px,1fr)";
    const gridStyle: React.CSSProperties = { gridTemplateColumns };
    const barColor = getBreakdownBarColor(rowDimension);
    const shareLabel = `Share of ${breakdownMetricInlineLabels[shareMetric].toLowerCase()}`;
    return (
      <div className="space-y-1.5">
        <div
          className={`grid items-center gap-2 border-b border-[var(--color-border-subtle)] pb-2 text-[11px] text-[#6B7280] ${
            compact ? "" : "text-xs"
          }`}
          style={{ ...fontBody, ...gridStyle }}
        >
          <div className="uppercase tracking-[0.06em]">{dimensionLabel}</div>
          <div className="text-right uppercase tracking-[0.06em]">{breakdownMetricInlineLabels[valueMetric]}</div>
          <div className="text-right uppercase tracking-[0.06em]">{shareLabel}</div>
        </div>
        {rows.map((row) => {
          const shareValue = getBreakdownMetricValue(row, shareMetric);
          const value = getBreakdownMetricValue(row, valueMetric);
          const width = maxValue > 0 ? Math.max(1, (shareValue / maxValue) * 100) : 0;
          const share = shareTotal > 0 ? shareValue / shareTotal : 0;
          const comparisonRow = comparisonRowsByLabel.get(row.label);
          const comparisonValue = comparisonRow ? getBreakdownMetricValue(comparisonRow, valueMetric) : 0;
          const comparisonShareValue = comparisonRow ? getBreakdownMetricValue(comparisonRow, shareMetric) : 0;
          const comparisonShare = comparisonShareTotal > 0 ? comparisonShareValue / comparisonShareTotal : 0;
          const isActive = Boolean(
            rowDimension && activeFilters?.some((f) => f.dimension === rowDimension && f.value === row.label)
          );
          const labelClass = compact
            ? "truncate whitespace-nowrap"
            : "whitespace-normal break-words";
          const textSize = compact ? "text-[13px]" : "text-sm";
          return (
            <div key={row.label} className={`${compact ? "py-1" : "py-1.5"} group relative`}>
              <div className="grid items-center gap-2" style={gridStyle}>
                <button
                  type="button"
                  className={`flex min-w-0 items-center gap-2 rounded-sm py-1.5 text-left ${textSize} text-[#374151] transition-colors ${
                    rowDimension && onToggleFilter
                      ? isActive
                        ? "text-[#4338ca]"
                        : "hover:text-[#4338ca]"
                      : ""
                  }`}
                  style={fontBody}
                  onClick={() => {
                    if (!rowDimension || !onToggleFilter) return;
                    onToggleFilter(rowDimension, row, shareTotal, shareMetric);
                  }}
                >
                  <span className={`h-5 w-1 shrink-0 rounded-full ${isActive ? "bg-[#4F46E5]" : "bg-[#E0E7FF]"}`} />
                  <span className={`block min-w-0 ${labelClass}`}>
                    {renderBreakdownLabel(rowDimension, row.label)}
                  </span>
                </button>
                <div
                  className={`${textSize} whitespace-nowrap text-right font-medium text-[#111827] metric-number`}
                  style={fontMetric}
                >
                  {formatMetricValue(valueMetric, value)}
                </div>
                <div className="min-w-0">
                  <div className="mb-1 text-right text-[11px] text-[#6B7280] metric-number" style={fontMetric}>
                    {formatBreakdownShare(share)}
                  </div>
                  <div className="h-1.5 rounded-full bg-[#EEF2F7]">
                    <div className="h-1.5 rounded-full" style={{ width: `${width}%`, backgroundColor: barColor }} />
                  </div>
                </div>
              </div>
              {showComparison ? (
                <BreakdownComparisonTooltip
                  valueMetric={valueMetric}
                  shareMetric={shareMetric}
                  currentValue={value}
                  currentShare={share}
                  comparisonValue={comparisonValue}
                  comparisonShare={comparisonShare}
                  currentLabel={comparison?.currentLabel}
                  comparisonLabel={comparison?.comparisonLabel}
                />
              ) : null}
            </div>
          );
        })}
      </div>
    );
  };

  return (
    <div className="min-h-[280px] rounded-lg border border-[var(--color-border-subtle)] bg-white p-5 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
      <div className="mb-4 flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          {header ? (
            header
          ) : (
            <div className="text-[15px] font-semibold text-[#1F2937]" style={fontBody}>
              {title}
            </div>
          )}
        </div>
        <button
          type="button"
          aria-label={`Expand ${title}`}
          title="Expand"
          onClick={() => setExpanded(true)}
          className="shrink-0 p-1 text-gray-400 transition-colors hover:text-[#1F2937]"
        >
          <ExpandIcon />
        </button>
      </div>
      {renderRows(true)}
      {expanded && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-[#111827]/50 p-4"
          role="dialog"
          aria-modal="true"
          aria-label={`${title} details`}
          onClick={() => setExpanded(false)}
        >
          <div
            className="flex max-h-[90vh] w-full max-w-3xl flex-col rounded-lg border border-[var(--color-border-subtle)] bg-white shadow-xl"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-center justify-between gap-3 border-b border-[var(--color-border-subtle)] px-5 py-3">
              <div className="text-sm font-semibold text-[#1F2937]" style={fontBody}>
                {title}
              </div>
              <button
                type="button"
                aria-label="Close"
                onClick={() => setExpanded(false)}
                className="p-1 text-gray-400 transition-colors hover:text-[#1F2937]"
              >
                <CloseIcon />
              </button>
            </div>
            <div className="overflow-auto px-5 py-4">{renderRows(false)}</div>
          </div>
        </div>
      )}
    </div>
  );
};

const BreakdownComparisonTooltip: React.FC<{
  valueMetric: BreakdownMetricKey;
  shareMetric: BreakdownMetricKey;
  currentValue: number;
  currentShare: number;
  comparisonValue: number;
  comparisonShare: number;
  currentLabel?: string | null;
  comparisonLabel?: string | null;
}> = ({
  valueMetric,
  shareMetric,
  currentValue,
  currentShare,
  comparisonValue,
  comparisonShare,
  currentLabel,
  comparisonLabel,
}) => {
  const valueLabel = breakdownMetricInlineLabels[valueMetric].toLowerCase();
  const shareLabel = breakdownMetricInlineLabels[shareMetric].toLowerCase();
  const delta = formatComparisonDelta(currentValue, comparisonValue);
  return (
    <div
      className="pointer-events-none absolute right-0 top-full z-30 mt-2 hidden w-64 rounded-md bg-[#111827] px-3 py-2.5 text-white shadow-xl group-hover:block group-focus-within:block"
      style={fontBody}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="metric-number text-sm font-semibold text-white" style={fontMetric}>
            {formatMetricValue(valueMetric, currentValue)} {valueLabel}
          </div>
          <div className="mt-0.5 text-[11px] text-white/70">{currentLabel ?? "Selected period"}</div>
        </div>
        <div className={`metric-number whitespace-nowrap text-xs font-semibold ${delta.tone}`} style={fontMetric}>
          {delta.label}
        </div>
      </div>
      <div className="mt-2 text-[11px] text-white/70">
        Share of {shareLabel}: <span className="metric-number text-white" style={fontMetric}>{formatBreakdownShare(currentShare)}</span>
      </div>
      <div className="my-2 border-t border-white/15" />
      <div className="metric-number text-sm font-semibold text-white/80" style={fontMetric}>
        {formatMetricValue(valueMetric, comparisonValue)} {valueLabel}
      </div>
      <div className="mt-0.5 text-[11px] text-white/60">{comparisonLabel ?? "Comparison period"}</div>
      <div className="mt-2 text-[11px] text-white/60">
        Share of {shareLabel}: <span className="metric-number text-white/80" style={fontMetric}>{formatBreakdownShare(comparisonShare)}</span>
      </div>
    </div>
  );
};

const chooseShareMetric = (
  rowDimension: string | undefined,
  metricKeys: BreakdownMetricKey[],
  primaryMetric: BreakdownMetricKey
): BreakdownMetricKey => {
  if (rowDimension === "page") return metricKeys.includes("pageviews") ? "pageviews" : primaryMetric;
  if (rowDimension === "goal") return metricKeys.includes("conversions") ? "conversions" : primaryMetric;
  if (metricKeys.includes("sessions")) return "sessions";
  return primaryMetric;
};

const chooseValueMetric = (
  rowDimension: string | undefined,
  metricKeys: BreakdownMetricKey[],
  shareMetric: BreakdownMetricKey,
  primaryMetric: BreakdownMetricKey
): BreakdownMetricKey => {
  if (rowDimension === "page") return metricKeys.includes("pageviews") ? "pageviews" : shareMetric;
  if (rowDimension === "goal") return metricKeys.includes("conversions") ? "conversions" : shareMetric;
  if (metricKeys.includes("uniques")) return "uniques";
  return metricKeys.includes(shareMetric) ? shareMetric : primaryMetric;
};

const formatBreakdownShare = (share: number): string => {
  if (!Number.isFinite(share) || share <= 0) return "0%";
  const pct = share * 100;
  if (pct < 0.5) return "<1%";
  if (pct < 10) return `${pct.toFixed(1)}%`;
  return `${Math.round(pct)}%`;
};

const formatComparisonDelta = (
  currentValue: number,
  comparisonValue: number
): { label: string; tone: string } => {
  if (!Number.isFinite(currentValue) || !Number.isFinite(comparisonValue)) {
    return { label: "—", tone: "text-white/70" };
  }
  if (comparisonValue <= 0) {
    if (currentValue <= 0) return { label: "0%", tone: "text-white/70" };
    return { label: "New", tone: "text-emerald-300" };
  }
  const delta = (currentValue - comparisonValue) / comparisonValue;
  if (Math.abs(delta) < 0.005) return { label: "0%", tone: "text-white/70" };
  const arrow = delta > 0 ? "↑" : "↓";
  const tone = delta > 0 ? "text-emerald-300" : "text-rose-300";
  const pct = Math.abs(delta) * 100;
  const formatted = pct < 10 ? `${pct.toFixed(1)}%` : `${Math.round(pct)}%`;
  return { label: `${arrow} ${formatted}`, tone };
};
