import { useState, type FC, type FormEvent } from "react";

import { useAuth } from "../hooks/useAuth";
import { fontBody, fontHeading } from "../styles/typography";

export const LoginGate: FC = () => {
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    setIsSubmitting(true);
    try {
      await login(username, password);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#F9FAFB]">
      <main className="mx-auto flex min-h-screen max-w-md items-center px-6 py-12">
        <section className="w-full border border-gray-200 bg-white p-6">
          <h1 className="text-2xl text-[#1F2937]" style={fontHeading}>
            Sign In
          </h1>
          <p className="mt-2 text-sm text-gray-600" style={fontBody}>
            Dashboard access is restricted.
          </p>
          <form className="mt-6 space-y-4" onSubmit={handleSubmit}>
            <div>
              <label className="mb-1 block text-xs uppercase tracking-[0.2em] text-gray-500" style={fontBody}>
                Username
              </label>
              <input
                type="text"
                aria-label="Username"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                className="w-full border border-gray-300 px-3 py-2 text-sm text-[#111827]"
                style={fontBody}
                required
              />
            </div>
            <div>
              <label className="mb-1 block text-xs uppercase tracking-[0.2em] text-gray-500" style={fontBody}>
                Password
              </label>
              <input
                type="password"
                aria-label="Password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                className="w-full border border-gray-300 px-3 py-2 text-sm text-[#111827]"
                style={fontBody}
                required
              />
            </div>
            {error && (
              <p className="text-sm text-rose-600" style={fontBody}>
                {error}
              </p>
            )}
            <button
              type="submit"
              disabled={isSubmitting}
              className="w-full border border-gray-900 bg-gray-900 px-4 py-2 text-sm text-white disabled:opacity-60"
              style={fontBody}
            >
              {isSubmitting ? "Signing in..." : "Sign In"}
            </button>
          </form>
        </section>
      </main>
    </div>
  );
};
