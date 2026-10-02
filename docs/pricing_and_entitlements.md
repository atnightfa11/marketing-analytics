# Pricing And Entitlements

Valid's commercial launch tiers are designed around the line between one-project analytics and business operations.

## Solo - $10/month

Solo is for one website, including low-traffic businesses that need long-term history.

- 1 website
- 100K monthly accepted pageviews (advisory capacity, not a traffic cutoff)
- Aggregate analytics history while subscribed, with no 365-day read gate
- Notes and annotations
- Basic forecasting for pageviews, visitors, and sessions when enough history exists
- No historical imports
- No Slack/email anomaly alerts
- No team/site access management beyond the owner

## Standard - $29/month

Standard is for business operations.

- 3 websites included
- Additional websites: $5/site/month
- 1M monthly accepted pageviews pooled across the owner's sites
- Additional capacity: $15 per million pageviews/month, purchased as fixed recurring capacity after customer approval
- Aggregate analytics history while subscribed
- Historical data imports
- Slack/email anomaly alerts
- Forecasting for pageviews, visitors, sessions, conversions, and revenue when enough history exists
- Team/site access management

## Early Adopter Standard

Early Adopter Standard may be offered at $19/month for the first 50-100 customers.

Grandfather the price while the subscription remains active, not unlimited expansion. Early Adopter Standard should still include 3 sites; additional sites are billed at the normal additional-site rate.

## Predictable Billing And Responsible Use

Subscriptions have a fixed monthly capacity, not automatic metered overages. A single spike does not change billing or stop collection. Review sustained growth with the customer before an approved plan/capacity change. Additional sites share the account allowance and do not add pageviews. Account usage is counted before DP, excludes historical imports, and deduplicates accepted retries.

Operational policy:

- Do not silently throttle good-faith customers.
- Monitor unusually high event volume, bot-heavy traffic, storage growth, and processing cost.
- Contact the customer if one account's cost materially exceeds its subscription revenue or harms service reliability.
- Move agency/resale, very high-volume, or infrastructure-impacting customers to a higher plan or custom agreement.

## Implementation Notes

- Backend plan value `free` is the current internal representation for customer-facing Solo.
- Solo checkout uses `STRIPE_SOLO_PRICE_ID` and stores the site as backend plan `free` after the Stripe webhook links the customer/subscription.
- Standard checkout uses `STRIPE_STANDARD_PRICE_ID` and stores the site as backend plan `standard`.
- Early Adopter Standard checkout uses `STRIPE_EARLY_ADOPTER_STANDARD_PRICE_ID` when configured and also stores the site as backend plan `standard`.
- Standard entitlements are enforced server-side for historical imports, anomaly alerts, advanced forecast metrics, and site access management.
- Solo and Standard no longer have a plan-specific aggregate age cutoff. Per-request date-range bounds remain; customers can query older bounded intervals. This does not restore deleted data, extend raw retention, or implement post-cancellation deletion.
- Standard includes 3 sites. When a subscribed Standard owner has additional sites, Stripe is synced with `STRIPE_ADDITIONAL_SITE_PRICE_ID` at $5/site/month.
- The dashboard Plan & billing panel opens Stripe Customer Portal for self-serve payment-method updates and cancellation when a Stripe customer is linked.
- Stripe webhook events are persisted by `event.id` before processing so retries/replays do not re-run plan mutations.
- Payment failures keep paid entitlements during the configured grace period (`STRIPE_PAYMENT_FAILURE_GRACE_DAYS`, default 7), then the effective plan falls back to Solo until payment recovers.

## Capacity Rollout

- Settings > Plan & billing shows owner-only usage. Partial and provisional periods are labelled and are never used to charge or disable service.
- Existing subscribers use the Stripe portal, not a second Checkout subscription. Portal plan switching must include the configured Solo and Standard prices.
- Standard owners can request additional millions of monthly capacity. One pending request per owner is stored in `capacity_requests`, and internal ops destinations receive a notification. Request submission is not purchase authorization.
- Operators review the request, agree the total recurring price and effective date (including any proration/tax) with the customer, then update the existing Stripe subscription manually. This release does not implement automatic capacity checkout or automatic two-month-overage emails.
- Set optional `STRIPE_PAGEVIEW_CAPACITY_PRICE_ID` to the recurring monthly USD $15 per-million price on API and worker. Signed subscription webhooks recognize its quantity; extra-site items are not misread as base plans. No new price is required to keep existing subscriptions working.
- Pending requests: admin-token protected `GET /api/admin/billing/capacity-requests`. After manually fulfilling or declining one, `POST /api/admin/billing/capacity-requests/resolve` with `request_id` and `status` (`completed` or `declined`). Resolving a request does not modify Stripe or grant capacity. Stripe webhooks determine purchased capacity.
- Multiple active subscriptions for an owner require manual reconciliation; the API does not guess which one to modify or assign one misleading allowance.
- Notify existing customers before replacing their original unlimited terms. Advisory counts alone are not grounds for automatic charges.
