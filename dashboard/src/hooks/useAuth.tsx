import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

const API_BASE =
  import.meta.env.VITE_API_BASE_URL ??
  (typeof window !== "undefined" && window.location.hostname.endsWith("validanalytics.io")
    ? "https://api.validanalytics.io"
    : typeof window !== "undefined" && ["localhost", "127.0.0.1"].includes(window.location.hostname)
      ? `${window.location.protocol}//${window.location.hostname}:8000`
      : "http://localhost:8000");
const TOKEN_STORAGE_KEY = "ma_token";
const COOKIE_SESSION_TOKEN = "cookie-session";

interface AuthContextValue {
  token: string | null;
  authEnabled: boolean;
  ready: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [token, setToken] = useState<string | null>(null);
  const [authEnabled, setAuthEnabled] = useState(true);
  const [ready, setReady] = useState(false);

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_STORAGE_KEY);
    void fetch(`${API_BASE}/api/auth/logout`, {
      method: "POST",
      credentials: "include",
    });
    setToken(null);
  }, []);

  useEffect(() => {
    const handleExpiredSession = () => {
      localStorage.removeItem(TOKEN_STORAGE_KEY);
      setToken(null);
    };
    window.addEventListener("valid-auth-expired", handleExpiredSession);
    return () => window.removeEventListener("valid-auth-expired", handleExpiredSession);
  }, []);

  useEffect(() => {
    let mounted = true;
    const init = async () => {
      try {
        const statusResp = await fetch(`${API_BASE}/api/auth/status`, { credentials: "include" });
        if (!statusResp.ok) {
          throw new Error("Failed to fetch auth status");
        }
        const statusBody = (await statusResp.json()) as { enabled: boolean };
        if (!mounted) return;
        setAuthEnabled(Boolean(statusBody.enabled));
        if (!statusBody.enabled) {
          setReady(true);
          return;
        }

        const meResp = await fetch(`${API_BASE}/api/auth/me`, {
          credentials: "include",
        });
        if (!mounted) return;
        if (!meResp.ok) {
          localStorage.removeItem(TOKEN_STORAGE_KEY);
          setToken(null);
        } else {
          setToken(COOKIE_SESSION_TOKEN);
        }
      } catch {
        if (!mounted) return;
        setAuthEnabled(true);
      } finally {
        if (mounted) setReady(true);
      }
    };

    void init();
    return () => {
      mounted = false;
    };
  }, [logout]);

  const login = useCallback(async (username: string, password: string) => {
    const response = await fetch(`${API_BASE}/api/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ username, password }),
    });
    if (!response.ok) {
      let message = "Login failed";
      try {
        const body = (await response.json()) as { detail?: string };
        if (body.detail) message = body.detail;
      } catch {
        // ignore parse failures
      }
      throw new Error(message);
    }
    await response.json();
    localStorage.removeItem(TOKEN_STORAGE_KEY);
    setToken(COOKIE_SESSION_TOKEN);
  }, []);

  const value = useMemo(
    () => ({ token, authEnabled, ready, login, logout }),
    [token, authEnabled, ready, login, logout]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export const useAuth = (): AuthContextValue => {
  const value = useContext(AuthContext);
  if (!value) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return value;
};
