import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";
export default defineConfig({
    resolve: {
        alias: { "@": path.resolve(__dirname, "src") },
    },
    plugins: [react()],
    server: {
        port: 5173,
        proxy: {
            "/api": {
                target: "http://localhost:8000",
                changeOrigin: false,
                rewrite: (p) => p.replace(/^\/api/, ""),
            },
        },
    },
    build: {
        outDir: "dist",
    },
});
