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
        setupFiles: ["./vitest.setup.ts"],
        css: false,
    },
});
