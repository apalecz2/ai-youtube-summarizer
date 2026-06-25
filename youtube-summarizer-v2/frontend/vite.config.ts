import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev, proxy API + health to the FastAPI backend so the browser talks to a
// single origin (localhost:5173). That makes the session cookie "just work" and
// avoids CORS entirely during development.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true },
      "/health": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
  build: {
    // The backend serves this directory (FRONTEND_DIST) in production.
    outDir: "dist",
  },
});
