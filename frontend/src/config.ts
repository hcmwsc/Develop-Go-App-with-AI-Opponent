// API base URL resolution:
// - Build time: VITE_API_URL (set for web/mobile/desktop)
// - Runtime override: localStorage("weiqi_api_url") lets mobile users
//   point the app at their own backend without rebuilding.
// - Empty => same origin (dev proxy or FastAPI static mount).
//   IMPORTANT: In Capacitor/WebView the same-origin fallback does NOT
//   work — Capacitor serves from http://localhost/ which only returns
//   the bundled frontend HTML, never the real backend.  We detect this
//   and report a clear "backend not configured" error instead of a
//   confusing "Unexpected token '<' is not valid JSON".
const BUILD_API_URL = import.meta.env.VITE_API_URL || "";

function isCapacitor(): boolean {
  return typeof window !== "undefined" &&
    !!(window as any).Capacitor ||
    !!(window as any).__CAPACITOR__;
}

function resolveApiUrl(): string {
  try {
    const stored = localStorage.getItem("weiqi_api_url");
    if (stored !== null && stored.trim()) return stored.trim();
  } catch {
    // localStorage not available (SSR / restricted context)
  }
  return BUILD_API_URL;
}

export function hasBackendConfigured(): boolean {
  return resolveApiUrl() !== "";
}

export function needsBackendConfig(): boolean {
  return isCapacitor() && !hasBackendConfigured();
}

export const config = {
  get apiUrl(): string {
    return resolveApiUrl();
  },
  useProxy: BUILD_API_URL === "",
};

export function setApiUrl(url: string): void {
  try {
    if (url && url.trim()) localStorage.setItem("weiqi_api_url", url.trim());
    else localStorage.removeItem("weiqi_api_url");
  } catch {
    // ignore
  }
}

export function endpoint(path: string): string {
  if (!path.startsWith("/")) path = "/" + path;
  const base = resolveApiUrl();
  // Capacitor WebView has no proxy; must have an explicit backend URL.
  if (!base && isCapacitor()) {
    throw new Error("后端地址未配置：请在「服务器设置」中填写电脑 IP:端口，如 http://192.168.1.100:8000");
  }
  return base + path;
}
