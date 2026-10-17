import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// сборка кладётся в пакет бэкенда и раздаётся FastAPI; никаких CDN и внешних шрифтов
export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    outDir: "../src/jana_address/static",
    emptyOutDir: true,
  },
  server: {
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
});
