import { useEffect, useState, type ReactNode } from "react";
import { BrowserRouter, Link, Navigate, Route, Routes, useLocation } from "react-router-dom";
import * as api from "./api/client";
import { ApiErrorModalHost } from "./components/ApiErrorModalHost";
import { ServiceList } from "./pages/ServiceList";
import { EndpointCasesPage } from "./pages/EndpointCasesPage";
import { ServiceDetail } from "./pages/ServiceDetail";
import { SuiteDetail } from "./pages/SuiteDetail";
import { RunDetail } from "./pages/RunDetail";
import { MockScenarioList } from "./pages/MockScenarioList";
import { MockScenarioDetail } from "./pages/MockScenarioDetail";
import { AgentTestList } from "./pages/AgentTestList";
import { AgentScenarioDetail } from "./pages/AgentScenarioDetail";

function NavLink({ to, children }: { to: string; children: ReactNode }) {
  const { pathname } = useLocation();
  const active = to === "/" ? pathname === "/" : pathname.startsWith(to);
  return (
    <Link to={to} className={`nav-link ${active ? "nav-active" : ""}`}>{children}</Link>
  );
}

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
        <NavLink to="/">服务</NavLink>
        <NavLink to="/mock">Mock 数据</NavLink>
        <NavLink to="/agent-test">Agent 测试</NavLink>
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
          <Route path="/mock" element={<MockScenarioList />} />
          <Route path="/mock/:scenarioId" element={<MockScenarioDetail />} />
          <Route path="/agent-test" element={<AgentTestList />} />
          <Route path="/agent-test/scenarios/:scenarioId" element={<AgentScenarioDetail />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  );
}
