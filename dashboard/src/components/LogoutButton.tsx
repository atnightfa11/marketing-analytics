import type { FC } from "react";
import { useNavigate } from "react-router-dom";

import { useAuth } from "../hooks/useAuth";
import { fontBody } from "../styles/typography";

export const LogoutButton: FC<{ className?: string }> = ({ className }) => {
  const { token, authEnabled, logout } = useAuth();
  const navigate = useNavigate();

  if (!authEnabled || !token) return null;

  return (
    <button
      type="button"
      onClick={() => {
        logout();
        navigate("/", { replace: true });
      }}
      className={className ?? "border border-gray-200 bg-white px-2 py-1 text-[10px] uppercase tracking-[0.2em] text-gray-500 hover:border-gray-300 hover:text-[#1F2937]"}
      style={fontBody}
    >
      Log out
    </button>
  );
};
