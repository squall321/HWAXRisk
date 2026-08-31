// Vite 설정 — base './' 로 자산 URL 을 상대화해 Caddy 서브패스(/apps/hwax_risk/) 마운트에서도 깨지지 않게 한다.
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  base: "./",
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
