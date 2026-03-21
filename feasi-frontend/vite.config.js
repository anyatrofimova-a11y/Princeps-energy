import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          // Vendor: heavy 3D/map libs in separate chunks (loaded on demand)
          "vendor-three": ["three"],
          "vendor-r3f": ["@react-three/fiber", "@react-three/drei"],
          "vendor-mapbox": ["mapbox-gl"],
          "vendor-deck": ["@deck.gl/core", "@deck.gl/layers", "@deck.gl/mapbox"],
          "vendor-d3": ["d3-force"],
          // App chunks
          "react-core": ["react", "react-dom"],
        },
      },
    },
    chunkSizeWarningLimit: 800,
  },
  server: {
    port: 3000,
    proxy: {
      "/site": "http://localhost:8000",
      "/sites": "http://localhost:8000",
      "/tiles": "http://localhost:8000",
      "/opt": "http://localhost:8000",
      "/docs": "http://localhost:8000",
      "/grid": "http://localhost:8000",
      "/grid-efficiency": "http://localhost:8000",
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
      "/procurement": "http://localhost:8000",
      "/legacy": "http://localhost:8000",
      "/geoai": "http://localhost:8000",
      "/bess": "http://localhost:8000",
      "/bipv": "http://localhost:8000",
      "/classify": "http://localhost:8000",
      "/prospector": "http://localhost:8000",
      "/scoring": "http://localhost:8000",
      "/nged": "http://localhost:8000",
      "/eso": "http://localhost:8000",
      "/repd": "http://localhost:8000",
      "/workflows": "http://localhost:8000",
      "/energy_system": "http://localhost:8000",
      "/tracker": "http://localhost:8000",
      "/rag": "http://localhost:8000",
      "/notifications": "http://localhost:8000",
      "/hardware": "http://localhost:8000",
      "/teaser": "http://localhost:8000",
      "/alerts": "http://localhost:8000",
      "/api": "http://localhost:8000",
      "/ws": { target: "http://localhost:8000", ws: true },
      "/pmtiles-proxy": {
        target: "https://pbcc.blob.core.windows.net",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/pmtiles-proxy/, "/pbcc-pmtiles"),
      },
      "/vision": "http://localhost:8000",
      "/retrofit": "http://localhost:8000",
    },
  },
});
