import { defineConfig } from "vite";
import tailwindcss from "@tailwindcss/vite";
import react, { reactCompilerPreset } from "@vitejs/plugin-react";
import babel from "@rolldown/plugin-babel";
import path from "path";
import { tanstackRouter } from "@tanstack/router-plugin/vite";

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    tanstackRouter({
      target: "react",
      autoCodeSplitting: true,
    }),
    react(),
    babel({ presets: [reactCompilerPreset()] }),
    tailwindcss(),
  ],
  base: "/",
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "./"),
    },
  },
  server: {
    proxy: {
      "/ws": {
        target: "ws://127.0.0.1:9127",
        ws: true,
        changeOrigin: true,
      },
      "/api": {
        target: "http://127.0.0.1:9127",
        changeOrigin: true,
      },
    },
  },
});
