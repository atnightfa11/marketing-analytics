import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { addWebsite, pendingSiteSetup, type SiteProvisioning } from "../api";
import { fontBody, fontHeading } from "../styles/typography";

export function AddWebsite() {
  const [requestId, setRequestId] = useState(() => crypto.randomUUID() as string);
  const [name, setName] = useState("");
  const [domain, setDomain] = useState("");
  const [approved, setApproved] = useState(false);
  const [approvalRequired, setApprovalRequired] = useState(false);
  const [pending, setPending] = useState(false);
  const [loading, setLoading] = useState(true);
  const [setupCheckFailed, setSetupCheckFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<SiteProvisioning | null>(null);
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    let active = true;
    pendingSiteSetup().then((row) => {
      if (!active || !row) return;
      setRequestId(row.request_id); setName(row.site_name); setDomain(row.site_domain); setPending(true);
    }).catch(() => { if (active) { setSetupCheckFailed(true); setError("Unable to check pending setup. Reload before continuing."); } })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError("");
    try {
      setResult(await addWebsite({ request_id: requestId, site_name: name, site_domain: domain,
                                  approved_monthly_increase_usd: approved ? 5 : 0 }));
    } catch (err) {
      const failure = err as { response?: { data?: { detail?: string }; status?: number } };
      const responseDetail = failure.response?.data?.detail;
      const detail = typeof responseDetail === "string" ? responseDetail : "Setup could not be confirmed. Retry with the same website details.";
      if (detail.includes("adds $5/month")) { setApprovalRequired(true); return; }
      if (!failure.response || failure.response.status === 502) setPending(true);
      setError(detail);
    } finally { setBusy(false); }
  };
  const snippet = result?.site_key ? `<script defer src="https://app.validanalytics.io/validanalytics.global.js" data-valid-site-id="${result.site_id}" data-valid-site-key="${result.site_key}" data-valid-api-base="https://api.validanalytics.io" data-valid-autoconversions="true"></script>` : "";
  return <main className="mx-auto max-w-2xl px-6 py-10" style={fontBody}>
    <Link to="/sites" className="text-sm underline">Back to websites</Link>
    <h1 className="mb-6 mt-6 text-2xl" style={fontHeading}>{result ? "Install Valid" : "Add a website"}</h1>
    <section className="rounded-lg border border-[var(--border-default)] bg-[var(--surface-card)] p-6">
      {result ? <>
        <h2 className="font-semibold">{result.site_name}</h2>
        <p className="mt-2 text-sm text-[var(--text-muted)]">Add this script to your website, then review the installation.</p>
        <pre className="my-5 overflow-x-auto whitespace-pre-wrap break-all rounded bg-[var(--surface-page)] p-4 text-xs">{snippet}</pre>
        <div className="flex flex-wrap gap-4">
          <button className="rounded bg-[var(--color-primary)] px-4 py-2 text-sm text-white"
            onClick={() => { void navigator.clipboard.writeText(snippet).then(() => setCopied(true)).catch(() => setError("Clipboard unavailable. Select the script to copy it.")); }}>
            {copied ? "Copied" : "Copy script"}
          </button>
          <Link className="rounded border border-[var(--border-default)] px-4 py-2 text-sm" to={`/site/${encodeURIComponent(result.site_id)}/settings`}>Review installation</Link>
        </div>
      </> : <form className="space-y-5" onSubmit={submit}>
        <label className="block text-sm">Website name<input required maxLength={255} readOnly={pending}
          className="mt-2 h-10 w-full rounded border border-[var(--border-default)] bg-[var(--surface-page)] px-3"
          value={name} onChange={(e) => setName(e.target.value)} /></label>
        <label className="block text-sm">Domain<input required maxLength={255} readOnly={pending} placeholder="example.com"
          className="mt-2 h-10 w-full rounded border border-[var(--border-default)] bg-[var(--surface-page)] px-3"
          value={domain} onChange={(e) => setDomain(e.target.value)} /></label>
        {approvalRequired && <label className="flex items-start gap-2 text-sm"><input type="checkbox" required checked={approved} onChange={(e) => setApproved(e.target.checked)} />
          Add this website for $5/month, starting with my next invoice.</label>}
        <button disabled={loading || busy || setupCheckFailed} className="rounded bg-[var(--color-primary)] px-4 py-2 text-sm text-white disabled:opacity-60">
          {loading ? "Checking account..." : busy ? "Setting up..." : pending ? "Resume setup" : "Add website"}
        </button>
      </form>}
      {error && <p role="alert" className="mt-4 text-sm text-[#8B2635]">{error}</p>}
    </section>
  </main>;
}
