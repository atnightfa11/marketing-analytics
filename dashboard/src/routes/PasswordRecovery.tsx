import { useEffect, useState, type FormEvent } from "react";
import { confirmPasswordReset, requestPasswordReset } from "../api";
import { fontBody, fontHeading } from "../styles/typography";

export function PasswordRecovery() {
  const [token] = useState(() => new URLSearchParams(window.location.hash.slice(1)).get("token") ?? "");
  const resetting = window.location.pathname === "/reset-password";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    if (window.location.hash) window.history.replaceState(null, "", window.location.pathname);
  }, []);
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError("");
    try {
      const result = resetting ? await confirmPasswordReset(token, password) : await requestPasswordReset(email);
      setMessage(result.message);
      setPassword("");
      if (resetting) window.dispatchEvent(new Event("valid-auth-expired"));
    } catch (err) {
      const response = err as { response?: { data?: { detail?: string } } };
      const detail = response.response?.data?.detail;
      setError(typeof detail === "string" ? detail : "Unable to complete your request. Please try again.");
    } finally { setBusy(false); }
  };
  return <main className="mx-auto flex min-h-screen max-w-md items-center px-6 py-12" style={fontBody}>
    <section className="w-full rounded-lg border border-[var(--border-default)] bg-[var(--surface-card)] p-6">
      <a href="/" className="text-sm text-[var(--text-muted)]">Valid</a>
      <h1 className="mt-4 text-2xl" style={fontHeading}>{resetting ? "Reset password" : "Forgot password?"}</h1>
      {message ? <p role="status" className="mt-5 text-sm">{message}</p> : resetting && !token ?
        <p className="mt-5 text-sm">This link is incomplete. <a className="underline" href="/forgot-password">Request a new link</a>.</p> :
        <form className="mt-6 space-y-4" onSubmit={submit}>
          <label className="block text-sm">{resetting ? "New password" : "Email address"}
            <input className="mt-2 h-10 w-full rounded border border-[var(--border-default)] bg-[var(--surface-page)] px-3"
              type={resetting ? "password" : "email"} autoComplete={resetting ? "new-password" : "email"}
              minLength={resetting ? 8 : undefined} maxLength={resetting ? 128 : 255}
              value={resetting ? password : email} required
              onChange={(event) => resetting ? setPassword(event.target.value) : setEmail(event.target.value)} />
          </label>
          {error && <p role="alert" className="text-sm text-[#8B2635]">{error}</p>}
          <button disabled={busy} className="h-10 w-full rounded bg-[var(--color-primary)] px-4 text-sm text-white disabled:opacity-60">
            {busy ? "Please wait..." : resetting ? "Update password" : "Send reset link"}
          </button>
        </form>}
      <a className="mt-5 inline-block text-sm underline" href="/">Back to sign in</a>
    </section>
  </main>;
}
