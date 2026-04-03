import { fileURLToPath } from "url";
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

const repoRoot = fileURLToPath(new URL("../", import.meta.url));

/** 开发 / preview 时代理目标：优先 BACKEND_PROXY_TARGET，否则 127.0.0.1:BACKEND_PROXY_PORT，默认 8000 */
function resolveBackendProxyTarget(env: Record<string, string>): string {
  const target = (env.BACKEND_PROXY_TARGET || "").trim().replace(/\/$/, "");
  if (target) return target;
  const port = (env.BACKEND_PROXY_PORT || "8000").trim() || "8000";
  return `http://127.0.0.1:${port}`;
}

// 开发时代理到后端，避免 CORS；生产构建请与 API 同域或配置 VITE_API_BASE
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, repoRoot, "");
  const backend = resolveBackendProxyTarget(env);
  const proxy = {
    "/api": { target: backend, changeOrigin: true },
    "/mock-server": { target: backend, changeOrigin: true },
    "/health": { target: backend, changeOrigin: true },
    "/docs": { target: backend, changeOrigin: true },
    "/openapi.json": { target: backend, changeOrigin: true },
  };

  return {
    plugins: [react()],
    envDir: repoRoot,
    server: {
      port: 5173,
      proxy,
    },
    preview: {
      proxy,
    },
  };
});
