import { useEffect, useState, type ReactNode } from "react";
import { BrowserRouter, Link, Navigate, Route, Routes } from "react-router-dom";
import * as api from "./api/client";
import { ApiErrorModalHost } from "./components/ApiErrorModalHost";
import { ServiceList } from "./pages/ServiceList";
import { EndpointCasesPage } from "./pages/EndpointCasesPage";
import { ServiceDetail } from "./pages/ServiceDetail";
import { SuiteDetail } from "./pages/SuiteDetail";
import { RunDetail } from "./pages/RunDetail";

function Layout({ children }: { children: ReactNode }) {
  const [health, setHealth] = useState<string | null>(null);

  useEffect(() => {
    api
      .health()
      .then((h) => setHealth(h.status))
      .catch(() => setHealth("不可达"));
  }, []);

  return (
    <div className="app-shell">
      <ApiErrorModalHost />
      <header className="top-nav">
        <h1>API 测试编排控制台</h1>
        <Link to="/">服务</Link>
        <span className="health">后端 /health: {health ?? "…"}</span>
      </header>
      {children}
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/" element={<ServiceList />} />
          <Route path="/services/:serviceId" element={<ServiceDetail />} />
          <Route path="/services/:serviceId/endpoints/:endpointId" element={<EndpointCasesPage />} />
          <Route path="/suites/:suiteId" element={<SuiteDetail />} />
          <Route path="/runs/:runId" element={<RunDetail />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  );
}
