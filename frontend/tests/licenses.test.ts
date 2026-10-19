import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { getLicenseText } from "../src/lib/licenses";

describe("license text", () => {
  it.each([
    "bumble",
    "inputs",
    "pygame-ce",
    "pywebview",
    "starlette",
    "uvicorn",
    "websockets",
    "nxbt",
    "nxbt-typenoob",
    "react",
    "vite",
    "typescript",
    "tanstack-router",
    "tanstack-store",
    "tailwindcss",
    "base-ui",
    "shadcn-ui",
    "phosphor-icons",
    "blockly",
    "videojs",
    "effect",
    "pierre-diffs",
  ])("loads the complete %s Markdown file without changing its text", (slug) => {
    const source = readFileSync(new URL(`../src/licenses/${slug}.md`, import.meta.url), "utf8");
    expect(source.length).toBeGreaterThan(500);
    expect(getLicenseText(slug)).toBe(source);
  });

  it.each(["missing", "toString", "__proto__", "../MIT", "MIT.md"])(
    "does not resolve an unknown slug %s",
    (slug) => {
      expect(getLicenseText(slug)).toBeUndefined();
    },
  );
});
