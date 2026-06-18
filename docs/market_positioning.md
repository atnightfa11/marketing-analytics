# Market Positioning

Valid's launch lane is privacy-first web analytics for site owners who want to act on what is changing, not spend time digging through reports.

## Primary Position

> Privacy-first web analytics with forecasting, anomaly context, and goal pacing.

This is narrower than "Google Analytics alternative" and more useful than competing only on cookie-free pageview counting. Plausible, Fathom, Simple Analytics, and Matomo already have credible positions in privacy analytics. Valid should win by making traffic changes easier to understand and act on.

## Hero Copy

Recommended hero:

> Privacy-first web analytics for people who would rather act than dig.
>
> Forecasting and anomaly detection that show you what's coming, not just dashboards of what already happened.

## Product Wedge

Standard should feel like the tier that turns analytics into a decision tool:

- forecasts with freshness/building states
- anomaly detection and alerts
- notes/annotations for business context
- performance targets and pacing
- historical data import
- longer-range trend context
- aggregate reporting with short-lived raw processing material

Free can show current analytics, but Standard should be the clear upgrade for understanding what changed, why it matters, and what is likely next.

## Audience

Best early customers:

- owner-operated and small-team sites
- publishers and local information sites
- service businesses and consultants
- privacy-conscious marketers who dislike GA4 complexity
- teams that want a quick read on traffic, goals, and anomalies

Do not optimize the first commercial launch for enterprise procurement. Enterprise buyers will expect SSO, SOC 2-style evidence, SLAs, formal audit trails, procurement review, and security/legal workflows.

## What Not To Chase Yet

Avoid Matomo-style product sprawl before the core trust loop is mature:

- heatmaps
- session recordings
- funnels as a primary navigation concept
- custom report builders
- broad enterprise analytics menus
- broad differential privacy claims across every dashboard surface

These can make the product harder to maintain and harder to trust before the forecasting/anomaly wedge is proven.

## Claim Boundaries

Use:

- "No visitor cookies."
- "No cross-site tracking."
- "Short-lived raw processing material."
- "Aggregate reporting."
- "Differential privacy controls for selected high-volume Standard KPI metrics."

Avoid:

- "No cookies anywhere." Dashboard login uses a first-party `HttpOnly` auth cookie.
- "Anonymous analytics" unless the statement is scoped to specific outputs after raw processing has been purged.
- "Differential privacy for the whole dashboard." Breakdowns currently use rollups and suppression thresholds, not dimension-level DP.
