import React from "react";
import ReactDOM from "react-dom/client";
import "./index.css";
import { App } from "./App";
import { AuthProvider } from "./hooks/useAuth";

const rootElement = document.getElementById("root");

if (!rootElement) {
  throw new Error("Failed to find root element");
}

ReactDOM.createRoot(rootElement).render(
  <React.StrictMode>
    <AuthProvider>
      <App />
    </AuthProvider>
  </React.StrictMode>
);
