// @vitest-environment jsdom
import { act, createRef } from "react";
import {
  SettingsDialog,
  type SettingsDialogHandle,
} from "@/src/components/settings/dialog";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { CapturePreview } from "@/src/components/panels/capture-preview";
import { ConnectionPanel } from "@/src/components/panels/connection";
import { CaptureProvider } from "@/src/hooks/use-capture";
import { SocketProvider } from "@/src/hooks/use-socket";
import type { BluetoothStatus } from "@/src/lib/bluetooth";
import { DEFAULT_CONTROLLER_COLOURS } from "@/src/lib/controller-colours";
import type { ServerFrame } from "@/src/lib/types";
import { socket } from "@/src/lib/ws";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
vi.hoisted(() => {
  vi.stubGlobal("matchMedia", () => ({
    matches: false,
    addEventListener() {},
    removeEventListener() {},
  }));
});

let container: HTMLElement;
let root: Root;

beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      disconnect() {}
    },
  );
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  Reflect.deleteProperty(navigator, "mediaDevices");
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function button(label: string): HTMLButtonElement {
  const match = Array.from(document.querySelectorAll("button")).find(
    (element) =>
      element.getAttribute("aria-label") === label ||
      element.textContent === label,
  );
  if (!match) throw new Error(`Missing button: ${label}`);
  return match;
}

async function chooseOption(label: string, name: string) {
  await act(async () => button(label).click());
  const option = Array.from(
    document.querySelectorAll<HTMLElement>('[role="option"]'),
  ).find((entry) => entry.textContent === name);
  if (!option) throw new Error(`Missing option: ${name}`);
  await act(async () => option.click());
}

it("keeps per-adapter settings in the dialog and selects input from the card", async () => {
  const makeAdapter = (id: string, transport: string, controller_id: number | null) => ({
    id, transport, controller_id, preset: "xbox", macro_mode: false,
    local_address: null, error: null,
  });
  const primary = makeAdapter("primary", "usb:0", 1);
  let secondary = makeAdapter("adapter-2", "usb:1", null);
  const inventory = () => ({
    adapters: [primary, secondary],
    controllers_available: true,
    controllers: [
      { id: 1, guid: "first", name: "First Pad" },
      { id: 2, guid: "second", name: "Second Pad" },
    ],
  });
  const fetchRequest = vi.fn(async (path: string) => {
    if (path === "/api/adapters") return Response.json(inventory());
    if (path === "/api/adapters/adapter-2/controller") {
      secondary = { ...secondary, controller_id: 2 };
      return Response.json(inventory());
    }
    if (path.endsWith("/colours")) {
      return Response.json({
        controller_colours: {
          ...DEFAULT_CONTROLLER_COLOURS,
          body: path.includes("adapter-2") ? "#1122AA" : "#AA2211",
        },
        colours_reconnect_required: false,
      });
    }
    if (path === "/api/presets") return Response.json({ presets: [], active: "xbox" });
    if (path === "/api/config") return Response.json({ vibration_enabled: true });
    return Response.json({}, { status: 404 });
  });
  vi.stubGlobal("fetch", fetchRequest);
  vi.spyOn(socket, "start").mockImplementation(() => {});
  const send = vi.spyOn(socket, "send").mockReturnValue(true);
  let receive: ((frame: ServerFrame) => void) | undefined;
  vi.spyOn(socket, "onFrame").mockImplementation((handler) => {
    receive = handler;
    return () => {};
  });
  await act(async () => {
    root.render(<SocketProvider><ConnectionPanel onEditPreset={() => {}} /></SocketProvider>);
  });
  const cards = container.querySelectorAll("article");
  expect(cards).toHaveLength(2);
  expect(cards[1].querySelector('[data-region="body"]')?.getAttribute("fill")).toBe("#1122AA");
  expect(container.querySelector('[aria-label="Select controller"]')).toBeNull();

  const selectCard = button("Send manual and macro input through usb:1");
  await act(async () => selectCard.click());
  expect(send).toHaveBeenCalledWith({ type: "select_adapter", adapter_id: "adapter-2" });
  await act(async () => receive?.({ type: "status", mode: "manual", macro: null, adapter_id: "adapter-2" }));
  expect(selectCard.getAttribute("aria-pressed")).toBe("true");

  await act(async () => cards[1].querySelector<HTMLButtonElement>('[aria-label="Controller settings"]')?.click());
  expect(document.querySelector('[role="dialog"]')?.textContent).toContain("usb:1");
  await chooseOption("Select controller", "Second Pad");
  expect(fetchRequest).toHaveBeenCalledWith(
    "/api/adapters/adapter-2/controller",
    expect.objectContaining({ body: JSON.stringify({ controller_id: 2 }) }),
  );
  expect(cards[1].querySelector("h3")?.textContent).toBe("Second Pad");
  expect(send).toHaveBeenCalledTimes(1);
});

it("starts capture from the player and disables Stop after releasing the stream", async () => {
  const stopTrack = vi.fn();
  const track = Object.assign(new EventTarget(), {
    stop: stopTrack,
    readyState: "live",
  });
  const stream = { getTracks: () => [track], getVideoTracks: () => [track] };
  const getUserMedia = vi.fn().mockResolvedValue(stream);
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: {
      getUserMedia,
      enumerateDevices: async () => [
        { kind: "videoinput", deviceId: "capture-card" },
      ],
    },
  });

  await act(async () => {
    root.render(
      <CaptureProvider>
        <CapturePreview />
      </CaptureProvider>,
    );
  });

  expect(container.textContent).toContain("Capture card is idle");
  expect(button("Stop capture input").disabled).toBe(true);
  expect(getUserMedia).not.toHaveBeenCalled();

  await act(async () => button("Start capture input").click());
  expect(getUserMedia).toHaveBeenCalledWith({
    video: { deviceId: { exact: "capture-card" } },
    audio: true,
  });
  expect(container.querySelector("video")?.srcObject).toBe(stream);
  expect(button("Stop capture input").disabled).toBe(false);

  await act(async () => button("Stop capture input").click());
  expect(stopTrack).toHaveBeenCalledOnce();
  expect(container.querySelector("video")?.srcObject).toBeNull();
  expect(button("Stop capture input").disabled).toBe(true);
  expect(button("Start capture input").disabled).toBe(false);

  await act(async () => button("Start capture input").click());
  await act(async () => {
    track.readyState = "ended";
    track.dispatchEvent(new Event("ended"));
  });
  expect(button("Stop capture input").disabled).toBe(true);
  expect(container.querySelector("video")?.srcObject).toBeNull();
});

it("opens controller settings and sends actions for the card’s saved profile", async () => {
  const address = "12:34:56:78:9A:BC";
  let colours = { ...DEFAULT_CONTROLLER_COLOURS, body: "#FF3344" };
  let preset = "xbox";
  let vibrationEnabled = true;
  const controllerVibration: Record<string, boolean> = {};
  const controllerStatus = {
    available: true,
    active: "test-pad",
    controllers: [
      { guid: "test-pad", name: "Test Gamepad" },
      { guid: "second-pad", name: "Second Gamepad" },
    ],
  };
  const status: BluetoothStatus = {
    available: true,
    pairing: false,
    state: "disconnected",
    address: null,
    peers: [address],
    names: { [address]: "Living room Switch" },
    failure_id: 0,
    failure: null,
  };
  const fetchRequest = vi.fn(async (path: string, init?: RequestInit) => {
    if (path === "/api/config") {
      if (init?.method === "PATCH") {
        const change = JSON.parse(String(init.body));
        if (change.controller_colours) colours = DEFAULT_CONTROLLER_COLOURS;
        if (typeof change.vibration_enabled === "boolean")
          vibrationEnabled = change.vibration_enabled;
        Object.assign(controllerVibration, change.controller_vibration);
        return Response.json({
          config: {
            controller_colours: colours,
            vibration_enabled: vibrationEnabled,
            controller_vibration: controllerVibration,
          },
          colours_reconnect_required: true,
        });
      }
      return Response.json({
        controller_colours: colours,
        vibration_enabled: vibrationEnabled,
        controller_vibration: controllerVibration,
      });
    }
    if (path === "/api/bluetooth") {
      return Response.json(
        init?.method === "POST"
          ? { ...status, state: "connected", address }
          : status,
      );
    }
    if (path === "/api/controllers") {
      return Response.json({ ...controllerStatus, preset });
    }
    if (path === "/api/controllers/active" && init?.method === "PUT") {
      controllerStatus.active = "second-pad";
      preset = "xbox";
      return Response.json({ ...controllerStatus, preset });
    }
    if (path === "/api/presets") {
      return Response.json({
        active: preset,
        presets: [
          {
            filename: "xbox",
            name: "Xbox",
            active: preset === "xbox",
            builtin: true,
          },
          {
            filename: "custom",
            name: "Custom mapping",
            active: preset === "custom",
            builtin: false,
          },
        ],
      });
    }
    if (path === "/api/presets/custom/activate" && init?.method === "POST") {
      preset = "custom";
      return Response.json({
        ...controllerStatus,
        preset,
        applied: "Custom mapping",
      });
    }
    return Response.json({}, { status: 404 });
  });
  vi.stubGlobal("fetch", fetchRequest);
  vi.spyOn(socket, "start").mockImplementation(() => {});
  const settings = createRef<SettingsDialogHandle>();
  await act(async () => {
    root.render(
      <SocketProvider>
        <CaptureProvider>
          <SettingsDialog ref={settings} />
          <ConnectionPanel
            onEditPreset={(preset) => settings.current?.openPreset(preset)}
          />
        </CaptureProvider>
      </SocketProvider>,
    );
  });

  expect(container.textContent).toContain("Test Gamepad");
  expect(container.textContent).toContain("Living room Switch");
  await act(async () => button("Reconnect controller").click());
  expect(fetchRequest).toHaveBeenCalledWith(
    "/api/bluetooth",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ address }),
    }),
  );
  expect(button("Disconnect controller").disabled).toBe(false);

  function cardBodyColour() {
    return button("Edit controller colours")
      .querySelector('[data-region="body"]')
      ?.getAttribute("fill");
  }

  expect(cardBodyColour()).toBe("#FF3344");
  expect(container.querySelector("h3")?.parentElement?.textContent).toContain(
    "Connected",
  );
  await act(async () => button("Edit controller colours").click());
  expect(document.querySelector('[role="dialog"]')?.textContent).toContain(
    "Controller colours",
  );
  await act(async () => button("Reset").click());
  expect(cardBodyColour()).toBe("#FF3344");
  await act(async () => button("Close").click());
  await act(async () => button("Discard changes").click());
  expect(cardBodyColour()).toBe("#FF3344");

  await act(async () => button("Edit controller colours").click());
  await act(async () => button("Reset").click());
  await act(async () => button("Save").click());
  expect(cardBodyColour()).toBe(DEFAULT_CONTROLLER_COLOURS.body);
  expect(document.body.textContent).toContain(
    "Reconnect to apply them on the Switch.",
  );
  await act(async () => button("Close").click());

  await act(async () => button("Controller settings").click());
  expect(document.querySelector('[role="dialog"]')?.textContent).toContain(
    "Controller settings",
  );
  expect(button("Select controller").textContent).toContain("Test Gamepad");
  expect(button("Mapping preset").textContent).toContain("Xbox");
  await chooseOption("Mapping preset", "Custom mapping");
  expect(fetchRequest).toHaveBeenCalledWith(
    "/api/presets/custom/activate",
    expect.objectContaining({ method: "POST" }),
  );
  expect(button("Mapping preset").textContent).toContain("Custom mapping");
  await chooseOption("Select controller", "Second Gamepad");
  expect(fetchRequest).toHaveBeenCalledWith(
    "/api/controllers/active",
    expect.objectContaining({
      method: "PUT",
      body: JSON.stringify({ guid: "second-pad" }),
    }),
  );
  expect(container.querySelector("h3")?.textContent).toBe("Second Gamepad");
  expect(button("Mapping preset").textContent).toContain("Xbox");

  const vibration = () =>
    document.querySelector<HTMLElement>('[role="checkbox"]');
  await act(async () => vibration()?.click());
  expect(fetchRequest).toHaveBeenCalledWith(
    "/api/config",
    expect.objectContaining({
      method: "PATCH",
      body: JSON.stringify({ controller_vibration: { "second-pad": false } }),
    }),
  );
  await act(async () => button("Edit mapping preset").click());
  expect(fetchRequest).toHaveBeenCalledWith(
    "/api/presets/xbox",
    expect.anything(),
  );
  expect(
    document.querySelector('[role="tabpanel"]:not([hidden])')?.textContent,
  ).toContain("Vibration (All Controllers)");
  await act(async () => vibration()?.click());
  expect(vibrationEnabled).toBe(false);
  await act(async () => button("Close").click());
  await act(async () => button("Controller settings").click());
  expect(
    document.querySelector('[aria-label="Controller vibration unavailable"]'),
  ).not.toBeNull();
  expect(vibration()?.matches(":disabled, [aria-disabled=true]")).toBe(true);
  await act(async () => button("Close").click());
  await act(async () => button("General Settings").click());
  expect(document.querySelector('[role="tablist"]')?.textContent).toBe(
    "GeneralControllerCredits",
  );
  await act(async () => button("Controller").click());
  expect(
    document.querySelector('[role="tabpanel"]:not([hidden])')?.textContent,
  ).toContain("Presets");
  expect(document.querySelector('[aria-label="Select controller"]')).toBeNull();
  await act(async () => button("Close").click());

  await act(async () => button("Delete Switch profile").click());
  expect(document.querySelector('[role="dialog"]')?.textContent).toContain(
    "Living room Switch",
  );
  await act(async () => button("Delete profile").click());
  expect(fetchRequest).toHaveBeenCalledWith(
    "/api/bluetooth",
    expect.objectContaining({
      method: "DELETE",
      body: JSON.stringify({ address }),
    }),
  );
});
