import { afterEach, describe, expect, it, vi } from "vitest";
import { configureWebSocketAuth, websocketProtocols } from "./desktop";

afterEach(() => {
  configureWebSocketAuth(true);
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("desktop WebSocket authentication", () => {
  it("uses browser mode without a bridge", async () => {
    configureWebSocketAuth(false);
    expect(await websocketProtocols()).toEqual([]);
  });

  it("asks the native bridge again for each connection", async () => {
    const getToken = vi
      .fn()
      .mockResolvedValueOnce("a".repeat(43))
      .mockResolvedValueOnce("b".repeat(43));
    vi.stubGlobal("window", { pywebview: { api: { get_auth_token: getToken } } });
    expect(await websocketProtocols()).toEqual(["ounce-bt", `ounce-auth.${"a".repeat(43)}`]);
    expect(await websocketProtocols()).toEqual(["ounce-bt", `ounce-auth.${"b".repeat(43)}`]);
  });

  it("waits for pywebviewready before requesting the token", async () => {
    const target = new EventTarget();
    const browserWindow = Object.assign(target, { pywebview: {} });
    vi.stubGlobal("window", browserWindow);
    const pending = websocketProtocols();
    Object.assign(browserWindow.pywebview, { api: { get_auth_token: async () => "a".repeat(43) } });
    target.dispatchEvent(new Event("pywebviewready"));
    expect(await pending).toEqual(["ounce-bt", `ounce-auth.${"a".repeat(43)}`]);
  });

  it("fails closed when the bridge is missing", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("window", new EventTarget());
    const rejected = expect(websocketProtocols()).rejects.toThrow("bridge is unavailable");
    await vi.advanceTimersByTimeAsync(5000);
    await rejected;
  });

  it("rejects an invalid bridge token", async () => {
    vi.stubGlobal("window", { pywebview: { api: { get_auth_token: async () => "" } } });
    await expect(websocketProtocols()).rejects.toThrow("invalid token");
  });
});
