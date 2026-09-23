/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev: Vite on 5173 proxies /api to FastAPI on 8756 (section 3).
// Prod: `vite build` emits ./dist, which FastAPI serves as static files.
export default defineConfig({
  plugins: [react()],
  server: {
    // Bind 0.0.0.0 so a Windows browser can reach Vite across the WSL2 network
    // boundary (127.0.0.1 inside the VM is not visible from Windows). The /api
    // proxy runs inside WSL, so localhost:8756 there still resolves correctly.
    host: true,
    port: 5173,
    proxy: {
      "/api": "http://localhost:8756",
    },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
