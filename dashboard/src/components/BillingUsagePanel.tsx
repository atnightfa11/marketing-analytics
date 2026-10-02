import { useEffect, useState } from "react";
import { BillingUsage, fetchBillingUsage, requestPageviewCapacity } from "../api";

export function BillingUsagePanel({ siteId, token }: { siteId: string; token?: string }) {
  const [usage, setUsage] = useState<BillingUsage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [millions, setMillions] = useState("1");
  const [sending, setSending] = useState(false);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let cancelled = false;
    setUsage(null);
    setError(null);
    fetchBillingUsage(siteId, token).then((result) => {
      if (!cancelled) setUsage(result);
    }).catch(() => {
      if (!cancelled) setError("Usage is unavailable. Your subscription has not changed.");
    });
    return () => { cancelled = true; };
  }, [siteId, token, retry]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!usage) return;
    setSending(true);
    setError(null);
    try {
      const pending = await requestPageviewCapacity(siteId, Number(millions), token);
      setUsage({ ...usage, pending_request: pending });
    } catch {
      setError("Could not confirm the request. Refresh usage to check its status before trying again.");
    } finally {
      setSending(false);
    }
  }
  const period = usage?.current_period;
  const capacity = usage?.total_pageview_capacity;
  const over = Boolean(period && capacity && period.accepted_pageviews > capacity);
  const requested = Number(millions);
  const valid = Number.isInteger(requested) && requested >= 1 && requested <= 100;
  const date = (value: string) => new Date(value).toLocaleDateString(undefined, { month: "short", day: "numeric", timeZone: "UTC" });
  const number = (value: number) => value.toLocaleString();
  return (
    <div className="mt-5 border-t border-[var(--border-default)] pt-5 text-sm text-[var(--text-secondary)]">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-semibold text-[var(--text-primary)]">Account pageviews</h3>
        <button type="button" onClick={() => setRetry((value) => value + 1)} disabled={sending}
          className="text-[var(--color-accent)] disabled:opacity-50">Refresh</button>
      </div>
      {error && <p role="status" className="mt-2">{error}</p>}
      {!usage && !error && <p className="mt-2 text-[var(--text-muted)]">Loading usage...</p>}
      {usage && <>
        <p className="mt-3 text-lg tabular-nums text-[var(--text-primary)]">
          {period ? number(period.accepted_pageviews) : "No usage recorded"}
          {capacity !== null && capacity !== undefined && <span className="ml-2 text-sm text-[var(--text-muted)]">/ {number(capacity)} pageviews per month</span>}
        </p>
        {period && <p className="mt-1 text-xs text-[var(--text-muted)]">
          {date(period.period_start)} to {date(new Date(new Date(period.period_end).getTime() - 1).toISOString())} (UTC).
          {period.period_basis === "stripe_period" ? " Subscription period." : " Calendar-month estimate; billing dates are not confirmed."}
          {" "}Recorded since {date(period.first_recorded_at)}; counts may be partial.
        </p>}
        <p className="mt-2 text-xs text-[var(--text-muted)]">Accepted pageviews across your sites, before privacy noise. No automatic overage charges.</p>
        {usage.ambiguous_subscriptions && <p className="mt-2">Multiple subscriptions need review before we can show one account allowance. Contact info@validanalytics.io.</p>}
        {over && <p className="mt-3">Recorded traffic is above your included capacity. Collection continues. An isolated spike does not change your subscription; sustained growth may call for an approved upgrade.</p>}
        {usage.pending_request ? <p role="status" className="mt-4">
          Request received: +{number(usage.pending_request.additional_millions * 1_000_000)} pageviews/month for an additional ${usage.pending_request.monthly_price_usd}/month. Awaiting review; your subscription has not changed.
        </p> : usage.can_request_capacity && <form onSubmit={(event) => void submit(event)} className="mt-4">
          <h4 className="font-medium">Request additional monthly capacity</h4>
          <div className="mt-2 flex flex-wrap items-end gap-3">
            <div>
              <label htmlFor="capacity-millions" className="mb-1 block text-xs text-[var(--text-muted)]">Additional millions of pageviews</label>
              <input id="capacity-millions" type="number" min={1} max={100} step={1} value={millions}
                onChange={(event) => setMillions(event.target.value)} disabled={sending}
                className="h-10 w-28 rounded border border-[var(--border-default)] bg-[var(--surface-card)] px-3 text-[var(--text-primary)]" />
            </div>
            <button disabled={sending || !valid} className="min-h-[40px] rounded bg-[var(--color-primary)] px-4 text-white disabled:opacity-50" type="submit">
              {sending ? "Sending..." : "Request capacity"}
            </button>
          </div>
          <p className="mt-2 text-xs text-[var(--text-muted)]">{valid ? `+$${requested * usage.additional_million_price_usd}/month, before tax. ` : ""}We'll confirm pricing and timing with you before changing billing. Extra sites share this capacity.</p>
        </form>}
      </>}
    </div>
  );
}
