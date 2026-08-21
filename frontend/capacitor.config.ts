import type { CapacitorConfig } from "@capacitor/cli";

// Capacitor wraps the Vite build output into native iOS/Android shells.
// Configure API URL at build time via VITE_API_URL (cloud backend) so the
// mobile app talks to the server instead of localhost.
const config: CapacitorConfig = {
  appId: "com.weiqi.app",
  appName: "围棋 AI",
  webDir: "dist",
  bundledWebRuntime: false,
  server: {
    // Allow cleartext only in dev; production should use HTTPS backend.
    cleartext: true,
    // Use http scheme so WebView can make HTTP API requests without
    // mixed-content blocking (https→http is blocked by default).
    androidScheme: "http",
  },
};

export default config;
