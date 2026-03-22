# Competitor Comparison Guide (Pilot)

Use this during owned-site pilots against tools like Plausible.

## Setup parity

1. Install Valid and competitor scripts on the same pages.
2. Match date ranges/timezones.
3. Compare at daily granularity first.

## Recommended checks

- Pageviews trend direction
- Session trend direction
- Conversion event trend direction
- Forecast reasonableness (range, not single-point match)

## Expected differences

- Minor count variance due to privacy/noise handling and sampling choices.
- Timing differences around late events and reduction cadence.

## Pass criteria for pilot

- Stable ingest (no persistent 401/403/429)
- Dashboard updates daily without manual intervention
- Forecasts available for primary metric(s)
