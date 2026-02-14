import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      "/site": "http://localhost:8000",
      "/tiles": "http://localhost:8000",
      "/opt": "http://localhost:8000",
      "/docs": "http://localhost:8000",
      "/grid": "http://localhost:8000",
      "/nom": "http://localhost:8000",
      "/planning": "http://localhost:8000",
      "/inventory": "http://localhost:8000",
      "/analytics": "http://localhost:8000",
      "/tenders": "http://localhost:8000",
      "/chat": "http://localhost:8000",
      "/health": "http://localhost:8000",
      "/electricity": "http://localhost:8000",
      "/job": "http://localhost:8000",
      "/jobs": "http://localhost:8000",
      "/geeflow": "http://localhost:8000",
      "/pmtiles-proxy": {
        target: "https://pbcc.blob.core.windows.net",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/pmtiles-proxy/, "/pbcc-pmtiles"),
      },
    },
  },
});
