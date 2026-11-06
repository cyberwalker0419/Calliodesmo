import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  resolve: {
    alias: { "@": path.resolve(__dirname, "src") },
  },
  plugins: [react()],
  test: {
    globals: true,
    environment: "jsdom",
    // Node 26 + jsdom 25：不透明 origin 下 localStorage 不可用，固定 http 源
    environmentOptions: { jsdom: { url: "http://localhost/" } },
    setupFiles: ["./vitest.setup.ts"],
    css: false,
    // e2e 由 playwright 运行（frontend/e2e/），vitest 仅收 src 单测
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
  },
});