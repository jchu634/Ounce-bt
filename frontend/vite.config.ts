import { defineConfig } from "vite";
import tailwindcss from "@tailwindcss/vite";
import react, { reactCompilerPreset } from "@vitejs/plugin-react";
import babel from "@rolldown/plugin-babel";
import path from "path";
import { readFileSync } from "node:fs";
import { tanstackRouter } from "@tanstack/router-plugin/vite";

const appVersion = readFileSync(new URL("../pyproject.toml", import.meta.url), "utf8").match(
  /^version\s*=\s*"([^"]+)"/m,
)?.[1];
if (!appVersion) throw new Error("Application version is missing from pyproject.toml");

// https://vite.dev/config/
export default defineConfig({
  define: {
    "import.meta.env.VITE_APP_VERSION": JSON.stringify(appVersion),
  },
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
