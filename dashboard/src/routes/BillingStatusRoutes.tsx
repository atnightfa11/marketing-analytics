import type { FC } from "react";
import { useSearchParams } from "react-router-dom";

import { LogoutButton } from "../components/LogoutButton";
import { fontBody, fontHeading, fontMeta } from "../styles/typography";

export const BillingSuccess: FC = () => {
  const [searchParams] = useSearchParams();
  const sessionId = searchParams.get("session_id");

  return (
    <div className="min-h-screen bg-[#F9FAFB] print-bg">
      <header className="border-b border-gray-200 bg-white">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-3">
          <a href="/" className="text-xl font-semibold text-[#1F2937]" style={fontHeading}>
            Valid
          </a>
          <LogoutButton />
        </div>
      </header>
      <main className="mx-auto max-w-3xl px-6 pb-10 pt-10">
        <section className="border border-gray-200 bg-white p-6">
          <h1 className="text-2xl text-[#1F2937]" style={fontHeading}>
            Billing Confirmed
          </h1>
          <p className="mt-3 text-sm text-gray-700" style={fontBody}>
            Your subscription update was accepted. We have received the Stripe session and are syncing your site plan.
          </p>
          {sessionId ? (
            <p className="mt-3 text-xs text-gray-500" style={fontBody}>
              Session ID: <span className="meta-number" style={fontMeta}>{sessionId}</span>
            </p>
          ) : null}
          <div className="mt-6 flex flex-wrap gap-3">
            <a
              href="/"
              className="inline-flex items-center border border-gray-900 bg-gray-900 px-4 py-2 text-sm text-white"
              style={fontBody}
            >
              Open Dashboard
            </a>
            <a href="/settings" className="inline-flex items-center border border-gray-300 px-4 py-2 text-sm" style={fontBody}>
              Billing Settings
            </a>
          </div>
        </section>
      </main>
    </div>
  );
};

export const BillingCancel: FC = () => (
  <div className="min-h-screen bg-[#F9FAFB] print-bg">
    <header className="border-b border-gray-200 bg-white">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-3">
        <a href="/" className="text-xl font-semibold text-[#1F2937]" style={fontHeading}>
          Valid
        </a>
        <LogoutButton />
      </div>
    </header>
    <main className="mx-auto max-w-3xl px-6 pb-10 pt-10">
      <section className="border border-gray-200 bg-white p-6">
        <h1 className="text-2xl text-[#1F2937]" style={fontHeading}>
          Billing Update Canceled
        </h1>
        <p className="mt-3 text-sm text-gray-700" style={fontBody}>
          No change was made to your subscription. You can return anytime to retry checkout.
        </p>
        <div className="mt-6 flex flex-wrap gap-3">
          <a
            href="/"
            className="inline-flex items-center border border-gray-900 bg-gray-900 px-4 py-2 text-sm text-white"
            style={fontBody}
          >
            Back to Dashboard
          </a>
          <a href="/settings" className="inline-flex items-center border border-gray-300 px-4 py-2 text-sm" style={fontBody}>
            Review Billing
          </a>
        </div>
      </section>
    </main>
  </div>
);
