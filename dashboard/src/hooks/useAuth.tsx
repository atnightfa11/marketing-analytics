import { createContext, useCallback, useContext, useMemo, useState } from "react";

interface AuthContextValue {
  token: string | null;
  login: (username: string, password: string) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem("ma_token"));

  const login = useCallback((username: string, password: string) => {
    const mockToken = btoa(`${username}:${password}:${Date.now()}`);
    localStorage.setItem("ma_token", mockToken);
    setToken(mockToken);
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem("ma_token");
    setToken(null);
  }, []);

  const value = useMemo(() => ({ token, login, logout }), [token, login, logout]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export const useAuth = (): AuthContextValue => {
  const value = useContext(AuthContext);
  if (!value) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return value;
};
