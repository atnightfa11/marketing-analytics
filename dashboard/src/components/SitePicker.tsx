import type { FC } from "react";

import type { DashboardSiteSummary } from "../api";
import { LAST_SITE_ID_STORAGE_KEY } from "../constants";
import { fontBody, fontHeading, fontMeta } from "../styles/typography";
import { LogoutButton } from "./LogoutButton";

const formatSiteHost = (site: DashboardSiteSummary): string => {
  const raw = site.allowed_origin || site.site_id;
  try {
    return new URL(raw).hostname || raw;
  } catch {
    return raw.replace(/^https?:\/\//, "").replace(/\/$/, "");
  }
};

export const SitePicker: FC<{ sites: DashboardSiteSummary[]; error?: string | null }> = ({ sites, error }) => {
  const lastSiteId =
    typeof window !== "undefined" ? localStorage.getItem(LAST_SITE_ID_STORAGE_KEY) : null;

  return (
    <div className="min-h-screen bg-[#F7F8FA] px-6 py-8 text-[#111827]">
      <main className="mx-auto max-w-5xl">
        <header className="mb-8 flex flex-wrap items-start justify-between gap-4">
          <div>
            <a href="/" className="text-[28px] font-bold tracking-[-0.01em] text-[#111827]" style={fontHeading}>
              Valid
            </a>
            <div className="mt-2 text-[11px] font-semibold uppercase tracking-[0.24em] text-[#737B8C]" style={fontMeta}>
              Select a site
            </div>
          </div>
          <LogoutButton />
        </header>

        <section className="rounded-lg border border-[#DDE1E7] bg-white p-5 shadow-sm">
          <div className="flex flex-wrap items-end justify-between gap-3 border-b border-[#EEF1F4] pb-4">
            <div>
              <h1 className="text-xl font-semibold text-[#111827]" style={fontHeading}>
                Your dashboards
              </h1>
              <p className="mt-1 text-sm text-[#6B7280]" style={fontBody}>
                Choose the account you want to view.
              </p>
            </div>
            <span className="text-[11px] font-semibold uppercase tracking-[0.2em] text-[#737B8C]" style={fontMeta}>
              {sites.length} {sites.length === 1 ? "site" : "sites"}
            </span>
          </div>

          {error && (
            <div className="mt-4 rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700" style={fontBody}>
              {error}
            </div>
          )}

          {sites.length === 0 ? (
            <div className="py-10 text-center text-sm text-[#6B7280]" style={fontBody}>
              No dashboards are available for this login.
            </div>
          ) : (
            <div className="divide-y divide-[#EEF1F4]">
              {sites.map((site) => {
                const isRecent = site.site_id === lastSiteId;
                return (
                  <a
                    key={site.site_id}
                    href={`/site/${encodeURIComponent(site.site_id)}`}
                    className="group flex flex-wrap items-center justify-between gap-4 py-4 text-left hover:bg-[#FAFBFC]"
                  >
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="truncate text-base font-semibold text-[#111827]" style={fontHeading}>
                          {site.site_name || site.site_id}
                        </span>
                        {isRecent && (
                          <span className="rounded border border-[#DDE1E7] bg-[#F7F8FA] px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-[#737B8C]" style={fontMeta}>
                            Recent
                          </span>
                        )}
                        <span className="rounded border border-[#E5E7EB] bg-white px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-[#737B8C]" style={fontMeta}>
                          {site.plan}
                        </span>
                      </div>
                      <div className="mt-1 truncate text-sm text-[#6B7280]" style={fontBody}>
                        {formatSiteHost(site)}
                      </div>
                      <div className="mt-1 truncate text-[11px] text-[#9CA3AF]" style={fontMeta}>
                        {site.site_id}
                      </div>
                    </div>
                    <span className="text-sm font-semibold text-[#5B55FF] group-hover:text-[#4338CA]" style={fontBody}>
                      Open dashboard -&gt;
                    </span>
                  </a>
                );
              })}
            </div>
          )}
        </section>
      </main>
    </div>
  );
};
