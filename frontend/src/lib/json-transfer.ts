import { Effect } from "effect";
import { ApiError, listMacros, listPresets, putMacro, putPreset } from "./api";
import { errorMessage } from "./errors";
import { desktopApi } from "./desktop";

declare global {
  interface Window {
    showSaveFilePicker?: (options: {
      suggestedName: string;
      types: { description: string; accept: Record<string, string[]> }[];
    }) => Promise<FileSystemFileHandle>;
  }
}

export type ImportKind = "macro" | "preset";

function importName(filename: string, used: Set<string>): string {
  const base =
    filename
      .replace(/\.json$/i, "")
      .replace(/[^A-Za-z0-9 _-]/g, "_")
      .replace(/^[^A-Za-z0-9]+/, "")
      .trim()
      .slice(0, 64) || "Imported";
  let name = base;
  for (let copy = 2; used.has(name.toLowerCase()); copy += 1) {
    const suffix = ` ${copy}`;
    name = `${base.slice(0, 64 - suffix.length)}${suffix}`;
  }
  return name;
}

export async function importJsonFiles(kind: ImportKind, files: readonly File[]) {
  const existing =
    kind === "macro"
      ? (await Effect.runPromise(listMacros())).names
      : (await Effect.runPromise(listPresets())).presets.map((preset) => preset.filename);
  const used = new Set(existing.map((name) => name.toLowerCase()));
  const imported: string[] = [];
  const errors: string[] = [];
  for (const file of files) {
    try {
      const contents = (await file.text()).replace(/^\uFEFF/, "");
      const name = importName(file.name, used);
      await Effect.runPromise(
        kind === "macro" ? putMacro(name, contents) : putPreset(name, contents),
      );
      used.add(name.toLowerCase());
      imported.push(name);
    } catch (error) {
      const detail = error instanceof ApiError ? error.body?.detail : undefined;
      errors.push(`${file.name}: ${errorMessage(error)}${detail ? `: ${detail}` : ""}`);
    }
  }
  return { imported, errors };
}

export async function downloadJson(name: string, contents: string): Promise<void> {
  try {
    JSON.parse(contents);
  } catch {
    throw new Error("Fix the JSON before downloading.");
  }
  const api = desktopApi();
  if (api?.save_json) {
    await api.save_json(name, contents);
    return;
  }
  if (typeof window.showSaveFilePicker !== "function") {
    throw new Error(
      "Save As is unavailable in this browser. Open the app in Chrome, Edge, or the desktop application to choose a save location.",
    );
  }
  let handle: FileSystemFileHandle;
  try {
    handle = await window.showSaveFilePicker({
      suggestedName: `${name}.json`,
      types: [{ description: "JSON files", accept: { "application/json": [".json"] } }],
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") return;
    throw error;
  }
  const writable = await handle.createWritable();
  try {
    await writable.write(contents);
    await writable.close();
  } catch (error) {
    await writable.abort().catch(() => {});
    throw error;
  }
}

export async function shareJson(name: string, contents: string): Promise<void> {
  if (typeof navigator.share !== "function") {
    throw new Error(
      "Sharing is not available in this browser. Try a browser with sharing support over HTTPS.",
    );
  }
  try {
    JSON.parse(contents);
  } catch {
    throw new Error("Fix the JSON before sharing.");
  }
  try {
    // Chromium blocks .json attachments even when canShare accepts them.
    // Share the JSON as text without consuming activation on a failed file share.
    await navigator.share({ title: name, text: contents });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") return;
    throw error;
  }
}
