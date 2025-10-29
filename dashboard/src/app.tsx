import React, { Suspense, useEffect, useState } from "react";
import { BrowserRouter, Route, Routes, Navigate } from "react-router-dom";
import { fetchMetrics, fetchForecast, MetricStatistic, ForecastEntry } from "./api";
import { KPIGrid } from "./components/KPIGrid";
import { LiveGauge } from "./components/LiveGauge";
import { ForecastChart } from "./components/ForecastChart";
import { AlertsPanel } from "./components/AlertsPanel";
import { TopSources } from "./components/TopSources";
import { TopCountries } from "./components/TopCountries";
import { DeviceBreakdown } from "./components/DeviceBreakdown";
import { PrivacyControls } from "./components/PrivacyControls";
import { useAuth } from "./hooks/useAuth";
import en from "./locales/en.json";

const Overview: React.FC = () => {
  const { token } = useAuth();
  const [metrics, setMetrics] = useState<MetricStatistic[]>([]);
  const [forecast, setForecast] = useState<ForecastEntry[]>([]);
  useEffect(() => {
    if (!token) return;
    fetchMetrics(token).then(setMetrics).catch(console.error);
    fetchForecast(token, "pageviews").then(setForecast).catch(console.error);
  }, [token]);

  return (
    <div className="space-y-6 p-6">
      <KPIGrid metrics={metrics} />
      <LiveGauge />
      <ForecastChart metric="pageviews" data={forecast} />
    </div>
  );
};

const Charts: React.FC = () => (
  <div className="grid gap-6 p-6 md:grid-cols-2">
    <TopSources />
    <TopCountries />
    <DeviceBreakdown />
  </div>
);

const Alerts: React.FC = () => (
  <div className="p-6">
    <AlertsPanel />
  </div>
);

const Settings: React.FC = () => (
  <div className="p-6">
    <PrivacyControls />
  </div>
);

export const App: React.FC = () => {
  const { token, login } = useAuth();

  useEffect(() => {
    if (!token) {
      login("demo", "demo");
    }
  }, [token, login]);

  return (
    <BrowserRouter>
      <Suspense fallback={<div>{en.loading}</div>}>
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/charts" element={<Charts />} />
          <Route path="/alerts" element={<Alerts />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
};
