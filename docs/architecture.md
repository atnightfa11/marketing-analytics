# Architecture

```mermaid
flowchart LR
    Client["Client SDK (Local DP)"] -->|Privatized batch| Shuffle["Shuffle Relay"]
    Shuffle -->|Uniform delay + forward| Collector["Collector API"]
    Collector -->|Persist batch| Warehouse["Postgres (ldp_reports partitions)"]
    Warehouse --> Reducer["Nightly Reducers"]
    Reducer -->|DP windows + uniques| Dashboard["Dashboard"]
    Reducer --> Forecast["Prophet + EWMA"]
    Forecast -->|Forecast bands + anomalies| Dashboard

The client SDK performs Boolean or histogram randomized response before sampling and transport. Each batch is shuffled, delayed uniformly between 0 and 120 seconds, and forwarded to the collector with linkable headers stripped. The collector writes into a month-partitioned ldp_reports table. Nightly reducers decode RR payloads, enforce MIN_REPORTS_PER_WINDOW, and only publish metrics whose signal-to-noise ratio (estimate / standard error) exceeds 1.5. Aggregates flow to the dashboard and to Prophet- and EWMA-based forecasting/anomaly detection. 

Watermarks 

Live windows tolerate LIVE_WATERMARK_SECONDS = 120 seconds of delay. 
Payloads older than MAX_OUT_OF_ORDER_SECONDS = 300 seconds are dropped and counted in events_dropped_late_total. 

Removed Fields Before Transport 

IP address 
User agent 
Cookies, session identifiers, and any per-user IDs 
Referrer and UTM values (encoded as DP histogram buckets on device) 
Exact timestamps (coarsened to window start on device) 
Only locally privatized, sampled statistics plus transport metadata (site_id, kind, epsilon_used, sampling_rate, nonce) reach the backend.

Publishing guards

Min sample: do not publish unless reports ≥ MIN_REPORTS_PER_WINDOW
SNR: do not publish unless estimate / std_error > 1.5
Include CI 80% and 95% with each published metric

Forecasting & anomalies

Train Prophet when ≥ 60 days of history; otherwise HTTP 204
Store and version models; promote only if MAPE improves ≥ 5%
Anomalies: flag when outside Prophet bounds or by z-score on EWMA baseline; expose has_anomaly, z_score