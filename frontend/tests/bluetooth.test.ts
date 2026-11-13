import { afterEach, describe, expect, it, vi } from "vitest";
import {
  BluetoothDisconnectingError,
  connectionDetail,
  deviceName,
  requestStatus,
  type BluetoothStatus,
} from "@/src/lib/bluetooth";

afterEach(() => vi.unstubAllGlobals());

describe("Bluetooth status requests", () => {
  it.each(["disconnected", "disconnecting"])("accepts saved addresses while %s", async (state) => {
    const status = {
      available: true,
      pairing: false,
      state,
      address: null,
      peers: ["12:34:56:78:90:AB/P"],
      names: { "12:34:56:78:90:AB/P": "Switch Device 1" },
      failure_id: 0,
      failure: null,
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(status)));
    await expect(requestStatus()).resolves.toEqual(status);
  });

  it("identifies disconnect conflicts so the UI can show a wait warning", async () => {
    const message = "The previous connection is still closing. Please wait a moment.";
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockImplementation(async () =>
          Response.json({ error: message, code: "disconnecting" }, { status: 409 }),
        ),
    );
    await expect(requestStatus()).rejects.toBeInstanceOf(BluetoothDisconnectingError);
    await expect(requestStatus()).rejects.toThrow(message);
  });

  it("shows saved names and reconnect targets without exposing addresses as labels", () => {
    const address = "12:34:56:78:90:AB/P";
    const status: BluetoothStatus = {
      available: true,
      pairing: false,
      state: "reconnecting",
      address,
      peers: [address, "AB:CD:EF:12:34:56/P"],
      names: { [address]: "Living room Switch" },
      failure_id: 0,
      failure: null,
    };
    expect(deviceName(status, address)).toBe("Living room Switch");
    expect(deviceName(status, status.peers[1])).toBe("Switch Device 2");
    expect(connectionDetail(status)).toBe(`Reconnecting to ${address}`);
  });

  it("rejects malformed device names", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        Response.json({
          available: true,
          pairing: false,
          state: "disconnected",
          address: null,
          peers: [],
          names: { address: 123 },
          failure_id: 0,
          failure: null,
        }),
      ),
    );
    await expect(requestStatus()).rejects.toThrow("Invalid Bluetooth status response");
  });

  it("identifies a backend that has not loaded the new route", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("Not found", { status: 404 })));
    await expect(requestStatus()).rejects.toThrow("does not support Bluetooth controls");
  });

  it("preserves a backend Bluetooth error", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          Response.json({ error: "Cannot read saved Bluetooth devices" }, { status: 503 }),
        ),
    );
    await expect(requestStatus()).rejects.toThrow("Cannot read saved Bluetooth devices");
  });

  it("distinguishes network failures from invalid status data", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    await expect(requestStatus()).rejects.toThrow("Cannot reach the backend");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ available: true })));
    await expect(requestStatus()).rejects.toThrow("Invalid Bluetooth status response");
  });

  it("explains an HTML fallback instead of claiming the backend is offline", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("<!DOCTYPE html>")));
    await expect(requestStatus()).rejects.toThrow("invalid response (HTTP 200)");
  });
});
