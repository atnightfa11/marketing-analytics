# Pricing And Entitlements

Valid's commercial launch tiers are designed around the line between one-project analytics and business operations.

## Solo - $10/month

Solo is for one owner-operated project.

- 1 website
- Unlimited pageviews for normal website traffic
- 12 months of aggregate analytics history
- Notes and annotations
- Basic forecasting for pageviews, visitors, and sessions when enough history exists
- No historical imports
- No Slack/email anomaly alerts
- No team/site access management beyond the owner

## Standard - $29/month

Standard is for business operations.

- 3 websites included
- Additional websites: $5/site/month
- Unlimited pageviews for normal website traffic
- Forever aggregate analytics retention
- Historical data imports
- Slack/email anomaly alerts
- Forecasting for pageviews, visitors, sessions, conversions, and revenue when enough history exists
- Team/site access management

## Early Adopter Standard

Early Adopter Standard may be offered at $19/month for the first 50-100 customers.

Grandfather the price while the subscription remains active, not unlimited expansion. Early Adopter Standard should still include 3 sites; additional sites are billed at the normal additional-site rate.

## Fair Use Boundary

Marketing should keep the headline simple:

> Unlimited pageviews*

Recommended footnote:

> *For normal website traffic. High-volume, abusive, bot-heavy, resale, or infrastructure-impacting use may require a higher plan.

Operational definition:

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
- Solo served aggregate history is limited to 365 days.
- Standard includes 3 sites in the entitlement response. Charging $5/additional site requires the deferred Stripe/account-billing pass.
- Additional-site billing, Customer Portal, payment-failure policy, and webhook event idempotency remain the deferred Stripe/account-billing pass.
