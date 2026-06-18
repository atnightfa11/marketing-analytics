# Brand Guidelines

## Color Palette

- Primary: #1b7f8e
- Neutral Dark: #111827
- Neutral Light: #F3F4F6
- White: #FFFFFF
- Accent: #7d2331

Usage notes:
- Use Primary sparingly for emphasis (e.g., key chart lines, active states).
- Default backgrounds use Neutral Light with White panels.
- Body text and headings use Neutral Dark.

## Typography

Headlines and logo:
- Playfair Display
- Weights: 600 (Semibold), 700 (Bold)
- Use for page titles, section headings, and the wordmark.

Body and UI:
- Inter
- Weights: 400 (Regular), 500 (Medium), 600 (Semibold)
- Use for labels, UI controls, table text, and paragraphs.

Data and code:
- Roboto Mono
- Weight: 400 (Regular)
- Use for KPIs, numeric values, and technical specs.

## Voice and Tone

Do:
- Be clear and direct.
- Use plain language over jargon.
- Lead with benefits, not features.
- Sound confident but not arrogant.
- Back claims with data.

Do not:
- Use fear-based messaging.
- Over-promise or exaggerate.
- Use overly casual language.
- Criticize competitors directly.
- Use unnecessary technical terms.

## Messaging Examples

Instead of:
"Our revolutionary AI-powered platform leverages cutting-edge differential privacy algorithms."

Say:
"Get accurate analytics without tracking individual users."

## Product Positioning

Primary launch message:

> Privacy-first web analytics for people who would rather act than dig.
>
> Forecasting and anomaly detection that show you what's coming, not just dashboards of what already happened.

Valid should lead with privacy-first analytics, forecasting, anomaly context, and goal pacing. Avoid positioning the product as a generic Google Analytics replacement; that market is crowded and the stronger reason to choose Valid is the decision layer on top of privacy-preserving aggregate analytics.

## Privacy Language

Use precise privacy claims:

- No visitor cookies.
- No cross-site tracking.
- Short-lived raw processing material.
- Aggregate reporting.
- Differential privacy controls for selected high-volume Standard KPI metrics.

Avoid broad claims such as "no cookies anywhere," "anonymous analytics" without context, or "differential privacy across the whole dashboard." Dashboard authentication uses a first-party `HttpOnly` cookie, and breakdowns currently use aggregate rollups plus suppression thresholds.
