```mermaid
flowchart LR
  A[Client SDK\nLocal DP] --> B[Shuffle Relay\nToken check\nRandom delay\nHeader strip]
  B --> C[Collector API\nStore privatized payloads only]
  C --> D[Nightly Reducer\nSNR guard\nEpsilon audit log]
  D --> E[Aggregates & Forecasts]
  E --> F[Dashboard\nKPIs Forecast Anomalies]
