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
      "/pmtiles-proxy": {
        target: "https://pbcc.blob.core.windows.net",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/pmtiles-proxy/, "/pbcc-pmtiles"),
      },
    },
  },
});
