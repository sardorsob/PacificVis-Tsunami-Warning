import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  publicDir: "demo-public",
  server: { host: "127.0.0.1", open: "/samples.html?sample=paired-atlas" },
  build: {
    outDir: "dist/samples",
    rollupOptions: { input: ["samples.html", "demos.html"] },
  },
});
