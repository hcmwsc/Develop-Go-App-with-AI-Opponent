import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";
// https://vitejs.dev/config/
export default defineConfig({
    plugins: [react()],
    resolve: {
        alias: {
            "@": path.resolve(__dirname, "./src"),
        },
    },
    server: {
        port: 5173,
        host: true,
        // Proxy /api to the FastAPI backend during development.
        proxy: {
            "/api": {
                target: process.env.VITE_API_URL || "http://127.0.0.1:8000",
                changeOrigin: true,
            },
            "/health": {
                target: process.env.VITE_API_URL || "http://127.0.0.1:8000",
                changeOrigin: true,
            },
        },
    },
    build: {
        outDir: "dist",
        sourcemap: true,
    },
});
