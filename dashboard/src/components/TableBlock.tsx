import React, { useEffect, useState } from "react";
import type { BreakdownMetricKey } from "../api";
import { breakdownMetricInlineLabels } from "../constants";
import { CloseIcon, ExpandIcon } from "./icons";
import { fontBody, fontMetric } from "../styles/typography";
import type { ActiveFilter, BreakdownTableRow } from "../types";
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
  emptyState?: string;
  error?: string | null;
  rowDimension?: string;
  activeFilters?: ActiveFilter[];
  onToggleFilter?: (dimension: string, row: BreakdownTableRow, total: number, primaryMetric: BreakdownMetricKey) => void;
}> = ({ title, header, rows, metricKeys, primaryMetric, total, emptyState, error, rowDimension, activeFilters, onToggleFilter }) => {
  const [expanded, setExpanded] = useState(false);
  const maxValue = rows.reduce((max, row) => Math.max(max, getBreakdownMetricValue(row, primaryMetric)), 0);
  const totalValue = total ?? rows.reduce((sum, row) => sum + getBreakdownMetricValue(row, primaryMetric), 0);

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
    const metricMinWidth = compact ? "minmax(64px,auto)" : "minmax(86px,auto)";
    const gridTemplateColumns = `minmax(0,1fr) ${metricKeys.map(() => metricMinWidth).join(" ")}`;
    const gridStyle: React.CSSProperties = { gridTemplateColumns };
    const barColor = getBreakdownBarColor(rowDimension);
    return (
      <div className="space-y-1.5">
        <div
          className={`grid items-center gap-2 border-b border-[var(--color-border-subtle)] pb-2 text-[11px] text-[#6B7280] ${
            compact ? "" : "text-xs"
          }`}
          style={{ ...fontBody, ...gridStyle }}
        >
          <div className="uppercase tracking-[0.06em]">{dimensionLabel}</div>
          {metricKeys.map((metricKey) => (
            <div key={metricKey} className="text-right uppercase tracking-[0.06em]">
              {breakdownMetricInlineLabels[metricKey]}
            </div>
          ))}
        </div>
        {rows.map((row) => {
          const primaryValue = getBreakdownMetricValue(row, primaryMetric);
          const width = maxValue > 0 ? Math.max(5, (primaryValue / maxValue) * 100) : 0;
          const isActive = Boolean(
            rowDimension && activeFilters?.some((f) => f.dimension === rowDimension && f.value === row.label)
          );
          const labelClass = compact
            ? "truncate whitespace-nowrap"
            : "whitespace-normal break-words";
          const textSize = compact ? "text-[13px]" : "text-sm";
          return (
            <div key={row.label} className={compact ? "py-1" : "py-1.5"}>
              <div className="grid items-center gap-2" style={gridStyle}>
                <button
                  type="button"
                  className={`relative min-w-0 overflow-hidden rounded-sm px-2 py-1.5 text-left ${textSize} text-[#374151] transition-colors ${
                    rowDimension && onToggleFilter
                      ? isActive
                        ? "text-[#4338ca] underline decoration-[#4338ca] underline-offset-2"
                        : "hover:text-[#4338ca] hover:underline hover:decoration-[#4338ca] hover:underline-offset-2"
                      : ""
                  }`}
                  style={fontBody}
                  onClick={() => {
                    if (!rowDimension || !onToggleFilter) return;
                    onToggleFilter(rowDimension, row, totalValue, primaryMetric);
                  }}
                >
                  <span
                    className="pointer-events-none absolute inset-y-0 left-0 rounded-sm"
                    style={{ width: `${width}%`, backgroundColor: barColor }}
                  />
                  <span className={`relative z-10 block min-w-0 ${labelClass}`}>
                    {renderBreakdownLabel(rowDimension, row.label)}
                  </span>
                </button>
                {metricKeys.map((metricKey) => (
                  <div
                    key={metricKey}
                    className={`${textSize} whitespace-nowrap text-right font-medium text-[#111827] metric-number`}
                    style={fontMetric}
                  >
                    {formatMetricValue(metricKey, getBreakdownMetricValue(row, metricKey))}
                  </div>
                ))}
              </div>
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
