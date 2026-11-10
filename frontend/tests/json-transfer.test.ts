import { afterEach, describe, expect, it, vi } from "vitest";
import { downloadJson, importJsonFiles, shareJson } from "@/src/lib/json-transfer";

afterEach(() => vi.unstubAllGlobals());

describe("JSON import", () => {
  it("imports multiple macros without overwriting existing or same-batch names", async () => {
    const fetch = vi
      .fn<typeof globalThis.fetch>()
      .mockResolvedValueOnce(Response.json({ names: ["Example"] }))
      .mockImplementation(async () => Response.json({ saved: true }));
    vi.stubGlobal("fetch", fetch);
    const contents = '{"version":1,"actions":[]}';
    const result = await importJsonFiles("macro", [
      new File([`\uFEFF${contents}`], "example.json"),
      new File([contents], "example.JSON"),
    ]);
    expect(result).toEqual({ imported: ["example 2", "example 3"], errors: [] });
    expect(fetch.mock.calls.slice(1).map(([url]) => url)).toEqual([
      "/api/macros/example%202",
      "/api/macros/example%203",
    ]);
    expect(fetch.mock.calls[1]?.[1]?.body).toBe(JSON.stringify({ contents }));
  });

  it("protects built-in presets and continues after an invalid file", async () => {
    const fetch = vi
      .fn<typeof globalThis.fetch>()
      .mockResolvedValueOnce(Response.json({ presets: [{ filename: "xbox" }] }))
      .mockResolvedValueOnce(Response.json({ error: "Invalid preset" }, { status: 400 }))
      .mockResolvedValueOnce(Response.json({ saved: true }));
    vi.stubGlobal("fetch", fetch);
    const result = await importJsonFiles("preset", [
      new File(["invalid"], "bad.json"),
      new File(['{"name":"Xbox copy"}'], "xbox.json"),
    ]);
    expect(result.imported).toEqual(["xbox 2"]);
    expect(result.errors).toHaveLength(1);
    expect(result.errors[0]).toContain("bad.json: ");
    expect(fetch.mock.calls[2]?.[0]).toBe("/api/presets/xbox%202");
  });

  it("converts filenames to valid names and keeps suffixes within 64 characters", async () => {
    const base = "a".repeat(64);
    const fetch = vi
      .fn<typeof globalThis.fetch>()
      .mockResolvedValueOnce(Response.json({ names: [base] }))
      .mockImplementation(async () => Response.json({ saved: true }));
    vi.stubGlobal("fetch", fetch);
    const result = await importJsonFiles("macro", [
      new File(["{}"], `${base}.json`),
      new File(["{}"], "...🎮.json"),
    ]);
    expect(result.imported).toEqual([`${"a".repeat(62)} 2`, "Imported"]);
  });

  it("does not save anything if the existing list cannot be loaded", async () => {
    const fetch = vi
      .fn<typeof globalThis.fetch>()
      .mockResolvedValue(Response.json({ error: "Unavailable" }, { status: 503 }));
    vi.stubGlobal("fetch", fetch);
    await expect(importJsonFiles("macro", [new File(["{}"], "test.json")])).rejects.toBeDefined();
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});

describe("JSON Save As", () => {
  it("opens the picker during the click and writes the current JSON", async () => {
    const write = vi.fn().mockResolvedValue(undefined);
    const close = vi.fn().mockResolvedValue(undefined);
    const picker = vi.fn().mockResolvedValue({ createWritable: async () => ({ write, close }) });
    vi.stubGlobal("window", { showSaveFilePicker: picker });
    const pending = downloadJson("My macro", '{"actions":[]}');
    expect(picker).toHaveBeenCalledWith({
      suggestedName: "My macro.json",
      types: [{ description: "JSON files", accept: { "application/json": [".json"] } }],
    });
    await pending;
    expect(write).toHaveBeenCalledWith('{"actions":[]}');
    expect(close).toHaveBeenCalledTimes(1);
  });

  it("uses the desktop save dialog when the bridge is available", async () => {
    const save = vi.fn().mockResolvedValue(true);
    const picker = vi.fn();
    vi.stubGlobal("window", {
      pywebview: { api: { save_json: save } },
      showSaveFilePicker: picker,
    });
    await downloadJson("Preset", "{}");
    expect(save).toHaveBeenCalledWith("Preset", "{}");
    expect(picker).not.toHaveBeenCalled();
  });

  it("ignores picker cancellation", async () => {
    vi.stubGlobal("window", {
      showSaveFilePicker: vi.fn().mockRejectedValue(new DOMException("Cancelled", "AbortError")),
    });
    await expect(downloadJson("Preset", "{}")).resolves.toBeUndefined();
  });

  it("aborts a failed write and reports the error", async () => {
    const abort = vi.fn().mockResolvedValue(undefined);
    const close = vi.fn();
    vi.stubGlobal("window", {
      showSaveFilePicker: async () => ({
        createWritable: async () => ({
          write: async () => {
            throw new Error("Disk full");
          },
          close,
          abort,
        }),
      }),
    });
    await expect(downloadJson("Preset", "{}")).rejects.toThrow("Disk full");
    expect(abort).toHaveBeenCalledTimes(1);
    expect(close).not.toHaveBeenCalled();
  });

  it("reports unsupported pickers rather than silently saving to Downloads", async () => {
    vi.stubGlobal("window", {});
    await expect(downloadJson("Preset", "{}")).rejects.toThrow("Save As is unavailable");
  });
});

describe("JSON sharing", () => {
  it("shares JSON text during the user gesture even when file support is advertised", async () => {
    const share = vi.fn(async (data: ShareData) => {
      if (data.files) throw new DOMException("Permission denied", "NotAllowedError");
    });
    vi.stubGlobal("navigator", { share, canShare: () => true });
    const contents = '{"version":1,"actions":[]}';
    const pending = shareJson("My macro", contents);
    expect(share).toHaveBeenCalledTimes(1);
    expect(share).toHaveBeenCalledWith({ title: "My macro", text: contents });
    await pending;
  });

  it("shares JSON text when files are unsupported", async () => {
    const share = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { share, canShare: () => false });
    await shareJson("Preset", "{}");
    expect(share).toHaveBeenCalledWith({ title: "Preset", text: "{}" });
  });

  it("ignores cancellation but reports sharing failures", async () => {
    const share = vi
      .fn()
      .mockRejectedValueOnce(new DOMException("Cancelled", "AbortError"))
      .mockRejectedValueOnce(new DOMException("Denied", "NotAllowedError"));
    vi.stubGlobal("navigator", { share });
    await expect(shareJson("Preset", "{}")).resolves.toBeUndefined();
    await expect(shareJson("Preset", "{}")).rejects.toThrow("Denied");
  });

  it("reports unsupported sharing and invalid JSON", async () => {
    vi.stubGlobal("navigator", {});
    await expect(shareJson("Preset", "{}")).rejects.toThrow("not available");
    const share = vi.fn();
    vi.stubGlobal("navigator", { share });
    await expect(shareJson("Preset", "invalid")).rejects.toThrow("Fix the JSON");
    expect(share).not.toHaveBeenCalled();
  });
});
