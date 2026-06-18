import type React from "react";

export const fontHeading: React.CSSProperties = { fontFamily: "var(--font-sans)" };

export const fontBody: React.CSSProperties = {
  fontFamily: "var(--font-sans)",
};

export const fontMetric: React.CSSProperties = {
  fontFamily: "var(--font-sans)",
  fontVariantNumeric: "tabular-nums lining-nums",
  fontFeatureSettings: '"tnum" 1, "lnum" 1',
  letterSpacing: "0em",
};

export const fontMeta: React.CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontVariantNumeric: "tabular-nums lining-nums",
  fontFeatureSettings: '"tnum" 1, "lnum" 1',
  letterSpacing: "0.01em",
};
