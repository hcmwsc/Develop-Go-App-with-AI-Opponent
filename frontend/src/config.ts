// API base URL resolution: dev uses Vite proxy (same origin), production
// reads from VITE_API_URL (set at build time for web/mobile/desktop).
const API_URL = import.meta.env.VITE_API_URL || "";

export const config = {
  apiUrl: API_URL,
  // Whether to use the dev proxy (empty API_URL => same origin / proxy)
  useProxy: API_URL === "",
};

export function endpoint(path: string): string {
  if (!path.startsWith("/")) path = "/" + path;
  return config.apiUrl + path;
}
