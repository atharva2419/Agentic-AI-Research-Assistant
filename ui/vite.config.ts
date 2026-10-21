import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // In development the UI runs on Vite (5173) and the API on uvicorn (8000). The proxy makes
    // /api look same-origin to the browser, so no CORS setup is needed.
    proxy: { "/api": "http://localhost:8000" },
  },
  test: {
    environment: "jsdom",
  },
});
