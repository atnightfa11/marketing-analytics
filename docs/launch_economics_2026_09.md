# Valid launch economics and hosting assessment

Planning date: September 24, 2026.

This is an assumption-driven six-month operating model, not a measured capacity guarantee or a prediction of customer acquisition. No pricing, Stripe configuration, infrastructure, or product code was changed.

## Recommended pricing interpretation

Retain Solo at $10/month for this model. Proposed Standard is $29/month for one website and 1 million monthly account pageviews, plus $5 per additional website and $15 per additional started million pageviews above 1 million. Traffic pools across the account; an additional website does not bring another free million. This reproduces $29 at 681K, $44 at 2M, $104 at 6M, and $269 at 17M.

The exact formula is 29 + 5 * additional_sites + 15 * ceil(max(0, pageviews - 1,000,000) / 1,000,000).

Consider customer-selected traffic bands and advance notices rather than unexpected automatic billing. Define billing periods, excluded bots, accepted pageviews, duplicate handling, and overage behavior before implementation. Billing should use accepted pre-DP usage counters; SDK session/presence reports must not be charged as additional pageviews. A purchase's conversion and revenue reports must not accidentally count twice as pageviews.

This is volume pricing, so marketing must stop promising unlimited pageviews at a fixed $29. "All Standard features, starting at $29/month" is accurate. Solo economics need separate review if unlimited Solo remains available to large owner-operated sites.

## Base six-month scenario

Active paying subscribers are month-end counts, net of churn; these counts are acquisition targets, not observed demand. MRR is the month-end run rate, not cash collected during a month with mid-month signups. Coupons, annual discounts, free beta accounts, and taxes are excluded.

Assumptions:
- Solo: 10,000 pageviews/account/month, $10/month.
- Standard: 70% of accounts at 100K pageviews, 20% at 681K, 8% at 2M, 2% at 6M.
- Standard weighted traffic: 546,200 pageviews/account/month.
- Standard weighted volume subscription: $31.70/month.
- 20% of Standard accounts have one additional site: weighted $1/month extra.
- Standard weighted revenue: $32.70/account/month.
- Extra-site traffic is included in the account traffic distribution, not added again.
- No 17M account is embedded in the base mix; it is tested separately below.
- Payment and subscription-billing fee reserve: 4% of revenue, a budgeting allowance rather than a Stripe quote.

### Infrastructure assumptions

Railway published resource rates used: CPU $20/vCPU-month, RAM $10/GB-month, volume $0.15/GB-month, egress $0.05/GB. Pro is a $20 minimum usage commitment; do not add it again when resource costs exceed $20.

Shared baseline budget: $70/month, composed of 4GB average RAM ($40), 0.75 average vCPU ($15), 20GB volume ($3), 40GB egress ($2), and $10 backup/operational reserve. This is an assumed budget, not the current Railway invoice.

For each million monthly pageviews, assume additional:
- 0.05 average vCPU: $1.00/month.
- 0.125GB average RAM: $1.25/month.
- 6GB egress: $0.30/month.
- 3GB newly retained aggregate/index storage each month: $0.45/month, accumulated across months.

Formula:
monthly infrastructure = 70 + 2.55 * current_month_pageviews_in_millions + 0.45 * cumulative_pageviews_in_millions_since_launch.

The fixed baseline includes working raw storage and maintenance headroom; 3GB/million is an assumption for durable segment/index growth. Actual database allocation, indexes, WAL, retention timing, backups, query concurrency and RAM retention can change costs significantly. Neither the event multiplier nor segment compression has been benchmarked at these volumes. SDK full page loads can emit pageview, session-start and presence reports, so test approximately 2-3 reports/pageview plus conversions, rather than assuming 1 report/pageview.

High-cost sensitivity doubles every variable infrastructure component while keeping the shared $70 baseline. It is not a statistical confidence interval or a worst-case bound.

| Month | Solo | Standard | Monthly pageviews | MRR | Base infrastructure | 2x variable cost | After base infrastructure and 4% fees |
|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | 5 | 5 | 2.78M | $214 | $78 | $87 | $127 |
| 2 | 10 | 12 | 6.65M | $492 | $91 | $112 | $381 |
| 3 | 18 | 22 | 12.2M | $899 | $111 | $152 | $753 |
| 4 | 28 | 37 | 20.49M | $1490 | $141 | $212 | $1289 |
| 5 | 40 | 60 | 33.17M | $2362 | $188 | $307 | $2079 |
| 6 | 55 | 90 | 49.71M | $3493 | $253 | $436 | $3100 |

These amounts are contribution before founder labor, support, customer acquisition, legal work, taxes, other software and migration engineering. They are not profit forecasts.

## Sensitivity and customer economics

Slow acquisition example: 5, 8, 12, 18, 25, 35 total paying customers over six months. Assume 60% Solo, 40% Standard using the same traffic mix. Month six MRR is about $668. Infrastructure is about $100 under the base model. Acquisition and support costs, not hosting alone, can dominate this early phase.

At the base scenario's month-six customer count, revenue is $3,493/month. Base infrastructure is $253; doubling variable costs raises it to $436. After a 4% payment reserve, corresponding contribution is about $3,100 or $2,917.

For a single site at constant traffic for six months, the variable model including accumulated storage costs $5.25 per million monthly pageviews in month six:
- 681K: $3.58 modeled variable cost vs $29 revenue.
- 2M: $10.50 vs $44.
- 6M: $31.50 vs $104.
- 17M: $89.25 vs $269.
These exclude allocated shared overhead and support. Doubling variable costs gives $7.15, $21, $63 and $178.50 respectively. Volume pricing provides useful protection even in this higher-cost case.

Adding one 17M account at month six adds $269 MRR and approximately $51 of first-month variable cost, or $102 at 2x variable costs. After six months of that same customer's retained history, its variable cost reaches the $89.25 above. An added large site therefore matters both immediately and through accumulated retention.

At this assumed storage-growth rate, each additional year adds $5.40/month of storage cost per million recurring monthly pageviews. That is a reason to measure segment growth and revisit the analytics storage design; this model does not promise unchanged margins forever.

## What the attached hosting research gets right and wrong

1. Valid currently runs PostgreSQL on Railway. Railway does not imply ClickHouse. The attachment primarily compares self-hosted ClickHouse on Railway with managed ClickHouse Cloud.
2. Railway's $20 is the platform minimum, not a complete production analytics stack price. $15-$30 for an entire stack at 5-10M pageviews is not established by the cited resource rates.
3. Railway meters resource consumption. Persistent process memory still costs money during quiet periods.
4. The claim that tens of millions of rows easily cause OOM is too categorical. Schema, query shape, cardinality, concurrency, memory limits and aggregation strategy determine capacity.
5. ClickHouse Cloud separates compute and storage and offers managed operations. It does not remove capacity planning or make query latency universally milliseconds.
6. "Practically infinite" and "fully hands-off" overstate the service. Customers still own schemas, batching, query design, tenant isolation, deletion behavior, cost controls and restore verification.
7. Continuous writes generally undermine assumptions about frequent scale-to-zero. Do not build a live analytics budget on a mostly-idle database.
8. The attachment's $66/$186 floor and $0.30/hour/$25 per TB figures were not verified as a universal current quote. Provider, region, tier, replica count and active hours matter.
9. ClickHouse distinguishes Basic/single-replica testing workloads from production Scale workloads. A small Basic price is not equivalent to an HA production configuration.
10. Self-hosted ClickHouse can be clustered, but orchestrating state, replicas and recovery on a general PaaS is additional engineering. It is not automatically limited to one node or automatically highly available.

## Hosting recommendation and costs

Keep API, auth, billing, site configuration, notes and goals on Railway/PostgreSQL. Evaluate ClickHouse Cloud for the analytical tables when benchmarks justify it. That is an added analytics service, not a wholesale replacement for Railway.

Options:
- Existing Railway/Postgres: lowest migration effort; the six-month model budgets $78-$253/month, or $87-$436 under its higher-variable-cost case. Those are modeled operating costs, not validated capacity.
- Self-hosted ClickHouse on Railway: for illustration, 8GB average RAM + 1 average vCPU + 100GB volume costs $115/month before networking, backups, other services or redundancy. A second comparable node roughly doubles those resources. This is a resource example, not a minimum sizing recommendation.
- Managed ClickHouse Cloud: obtain a selected-region production quote. As a sensitivity example ONLY, $0.30 per billable compute-unit hour at 730 active hours is $219/month per unit, or $438 for two units, before storage/transfer. The $0.30 rate comes from the supplied research and is unverified; do not treat this as a ClickHouse quote. Railway API/worker and transactional DB costs remain, though analytics load shifts away.
- A larger or better-managed Postgres deployment can extend runway and improve operations, but does not eliminate our Python reducer's memory use or segment expansion. Adding another analytics vendor now would require the same workload evaluation.

Cloud economics can be reasonable as shared costs: $438 of analytics compute spread across 100 accounts is $4.38/account before other services. At ten accounts it is $43.80/account. Avoid paying for redundant capacity before it provides a measured reliability or performance benefit, but do not use the cheapest single-node configuration as an HA comparison.

## Current code limits and migration scope

The reducer in server/app/scheduler/nightly_reduce.py selects all raw reports for the requested dates across all sites and materializes them with scalars().all(). It should process bounded site/day jobs with controlled concurrency before scaling the launch workload. This is a concrete memory limitation independent of database brand.

server/app/segment_rollups.py enumerates many supported dimension combinations and stores metric rows. Measure amplification for catalogs, campaigns and long date ranges. A columnar engine can reduce scan/storage costs, but moving the same Python aggregation loop unchanged will not realize its main benefits.

Suggested sequence:
1. Add per-site job duration, peak worker memory, accepted report count and rollup-row/storage-growth measurements.
2. Bound reduction by site/day and batch database writes; verify restart/idempotency/purge invariants.
3. Benchmark 681K, 2M, 6M and 17M monthly pageview equivalents with 2-3 reports/pageview, ecommerce cardinality, a traffic burst and concurrent dashboards.
4. Test the same workload in ClickHouse Cloud, including deletion/import replacement, DP publication, sessionization and forecast reads.
5. Shadow-write/query and reconcile results before switching analytics reads; keep a rollback path.

A scoped benchmark/prototype is days of engineering; a reliable migration with ingestion, query rewrites, backfill, reconciliation and rollout is more plausibly several weeks. Existing purged raw history cannot be reconstructed as event data, so import the durable history at its existing granularity.

Suggested evaluation triggers, not universal capacity limits: dashboard p95 above 1 second after query tuning; worker memory routinely above 70% of its limit; reducer backlog missing freshness targets; sustained database I/O saturation; or measured ClickHouse total cost undercutting Postgres plus reducer costs at equivalent reliability. At 10-20M aggregate monthly pageviews, prioritize the benchmark, not an automatic migration.

## Enterprise contact line and EU residency

Keep Pro off the public pricing page for now. Suggested copy:
"Need SSO or EU hosting? Contact us to discuss your requirements."
Use this as a conversation invitation; do not claim availability before provisioning and testing.

A standard DPA should be available to customers where Valid acts as processor, rather than being an enterprise-only paid feature. Bespoke negotiated legal terms can require a custom agreement.

EU data residency does not require ClickHouse. Railway offers an Amsterdam region, and ClickHouse offers EU deployment choices. Define the scope: analytics data at rest, analytics processing, or all customer data. Place ingestion, worker, analytics storage and backups accordingly; account for logs, monitoring, support access and subprocessors. Hosting the database in Europe while receiving raw traffic in a US API does not provide EU-only processing.

For an early EU customer, price a regional deployment separately based on its actual shared/dedicated resource floor and operational support. A public "email us" invitation does not require immediately operating an unused EU stack.

## Sources and verification limits

- Railway resource pricing: https://docs.railway.com/pricing/plans
- Railway billing/minimum: https://docs.railway.com/pricing/understanding-your-bill
- Railway EU region: https://docs.railway.com/deployments/regions
- ClickHouse pricing: https://clickhouse.com/pricing
- ClickHouse tier/replica rationale: https://clickhouse.com/blog/evolution-of-clickhouse-cloud-new-features-superior-performance-tailored-offerings
- ClickHouse capacity sizing: https://clickhouse.com/resources/engineering/high-concurrency-sizing-user-analytics
- Plausible pricing: https://plausible.io/#pricing
- Fathom pricing/event counting: https://usefathom.com/pricing
- EU controller/processor contractual clauses: https://eur-lex.europa.eu/legal-content/EN/ALL/?uri=CELEX%3A32021D0915

The supplied competitor dollar table is directional input, not independently verified at every traffic tier. Billing frequency, site allowances and whether custom events count against volume can change comparisons. Fathom explicitly counts custom events against its allowance. Validate every exact competitor price before publishing a comparison.

Previous raw-table size observations do not by themselves prove pathological bloat: indexes, free reusable pages and estimated live-row statistics also affect size. Measure dead tuples and vacuum statistics before deciding on maintenance.

