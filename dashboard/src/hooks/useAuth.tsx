import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
const TOKEN_STORAGE_KEY = "ma_token";

interface AuthContextValue {
  token: string | null;
  authEnabled: boolean;
  ready: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem(TOKEN_STORAGE_KEY));
  const [authEnabled, setAuthEnabled] = useState(false);
  const [ready, setReady] = useState(false);

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_STORAGE_KEY);
    setToken(null);
  }, []);

  useEffect(() => {
    let mounted = true;
    const init = async () => {
      try {
        const statusResp = await fetch(`${API_BASE}/api/auth/status`);
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

        const existingToken = localStorage.getItem(TOKEN_STORAGE_KEY);
        if (!existingToken) {
          setReady(true);
          return;
        }

        const meResp = await fetch(`${API_BASE}/api/auth/me`, {
          headers: { Authorization: `Bearer ${existingToken}` },
        });
        if (!mounted) return;
        if (!meResp.ok) {
          logout();
        } else {
          setToken(existingToken);
        }
      } catch {
        // Fail open for local/dev environments when auth endpoints are not reachable.
        if (!mounted) return;
        setAuthEnabled(false);
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
    const body = (await response.json()) as { access_token: string };
    localStorage.setItem(TOKEN_STORAGE_KEY, body.access_token);
    setToken(body.access_token);
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

