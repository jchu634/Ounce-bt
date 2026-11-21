// @vitest-environment jsdom
import { act, createRef } from "react";
import {
  createMemoryHistory,
  createRootRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import {
  SettingsDialog,
  type SettingsDialogHandle,
} from "@/src/components/settings/dialog";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { CapturePreview } from "@/src/components/panels/capture-preview";
import { ConnectionPanel } from "@/src/components/panels/connection";
import { MacroRunPanel } from "@/src/components/panels/macro-runner";
import { ManualControl } from "@/src/components/panels/manual-control";
import { CaptureDeviceSettings } from "@/src/components/settings/capture-device-settings";
import { CaptureProvider } from "@/src/hooks/use-capture";
import { SocketProvider } from "@/src/hooks/use-socket";
import type { BluetoothStatus } from "@/src/lib/bluetooth";
import { DEFAULT_CONTROLLER_COLOURS } from "@/src/lib/controller-colours";
import type { AdapterInputStatus, ServerFrame } from "@/src/lib/types";
import { socket } from "@/src/lib/ws";
import type { BluetoothControllerType } from "@/src/lib/controller-variants";

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
  localStorage.removeItem("ounce-bt.audio-input");
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function button(label: string): HTMLButtonElement {
  const match = Array.from(document.querySelectorAll("button")).find(
    (element) =>
      element.getAttribute("aria-label") === label ||
      element.textContent?.trim() === label,
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

it("selects a Joy-Con Bluetooth output and saves its body and button colours", async () => {
  let controllerType: BluetoothControllerType = "pro";
  let palette = { body: "#1122AA", buttons: "#000000" };
  const inventory = () => ({
    adapters: [{
      id: "primary",
      transport: "usb:0",
      controller_id: null,
      preset: null,
      macro_mode: false,
      local_address: "12:34:56:78:9A:BC",
      error: null,
      controller_type: controllerType,
    }],
    controllers: [],
    controllers_available: true,
  });
  const fetchRequest = vi.fn(async (path: string, init?: RequestInit) => {
    if (path === "/api/adapters") return Response.json(inventory());
    if (path === "/api/bluetooth") {
      return Response.json({
        available: true, state: "disconnected", pairing: false, address: null,
        player_number: null, peers: [], names: {}, failure_id: 0, failure: null,
      } satisfies BluetoothStatus);
    }
    if (path === "/api/adapters/primary/type") {
      controllerType = "joycon_l";
      return Response.json(inventory());
    }
    if (path === "/api/presets") return Response.json({ presets: [], active: null });
    if (path === "/api/config") return Response.json({ vibration_enabled: true });
    if (path.startsWith("/api/adapters/primary/colours")) {
      if (init?.method === "PATCH") palette = JSON.parse(String(init.body));
      return Response.json({
        controller_colours: controllerType === "pro" ? DEFAULT_CONTROLLER_COLOURS : palette,
        colours_reconnect_required: false,
      });
    }
    return Response.json({}, { status: 404 });
  });
  vi.stubGlobal("fetch", fetchRequest);
  vi.spyOn(socket, "start").mockImplementation(() => {});
  await act(async () => {
    root.render(
      <SocketProvider>
        <ConnectionPanel onEditPreset={() => {}} />
      </SocketProvider>,
    );
  });
  expect(container.querySelector('[aria-label="Bluetooth controller type"]')).toBeNull();
  await act(async () => button("Controller settings").click());
  expect(document.querySelector('[aria-label="Joy-Con orientation"]')).toBeNull();
  await chooseOption("Bluetooth controller type", "Joy-Con L");
  expect(fetchRequest).toHaveBeenCalledWith(
    "/api/adapters/primary/type",
    expect.objectContaining({ body: '{"controller_type":"joycon_l"}' }),
  );
  await act(async () => button("Close").click());
  expect(container.querySelector('svg[viewBox="6 19 52 26"]')).not.toBeNull();
  await act(async () => button("Edit controller colours").click());
  expect(document.querySelector('[role="dialog"]')?.textContent).toContain("Joy-Con L");
  expect(document.querySelector('[role="dialog"]')?.textContent).not.toContain("Left grip");
  await act(async () => button("Reset to default").click());
  await act(async () => button("Save").click());
  expect(palette).toEqual({ body: "#00B9D6", buttons: "#001E1E" });
  expect(container.querySelector('[data-region="body"]')?.getAttribute("fill")).toBe("#00B9D6");
});

it("keeps adapter settings scoped to the card and supports range selection", async () => {
  const makeAdapter = (
    id: string,
    transport: string,
    controller_id: number | null,
  ) => ({
    id,
    transport,
    controller_id,
    preset: "xbox",
    macro_mode: false,
    local_address: null,
    error: null,
  });
  const primary = makeAdapter("primary", "usb:0", 1);
  let secondary = makeAdapter("adapter-2", "usb:1", null);
  const inventory = () => ({
    adapters: [
      primary,
      secondary,
      makeAdapter("adapter-3", "usb:2", null),
      makeAdapter("adapter-4", "usb:3", null),
    ],
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
    if (path === "/api/presets")
      return Response.json({ presets: [], active: "xbox" });
    if (path === "/api/config")
      return Response.json({ vibration_enabled: true });
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
    root.render(
      <SocketProvider>
        <ConnectionPanel onEditPreset={() => {}} />
      </SocketProvider>,
    );
  });
  const cards = container.querySelectorAll("article");
  expect(cards).toHaveLength(4);
  expect(
    cards[1].querySelector('[data-region="body"]')?.getAttribute("fill"),
  ).toBe("#1122AA");
  expect(
    container.querySelector('[aria-label="Select controller"]'),
  ).toBeNull();

  const selectCard = button("Send manual and macro input through usb:1");
  await act(async () => selectCard.click());
  expect(send).toHaveBeenCalledWith({
    type: "select_adapter",
    adapter_id: "adapter-2",
  });
  await act(async () =>
    receive?.({
      type: "status",
      mode: "manual",
      macro: null,
      adapter_id: "adapter-2",
    }),
  );
  expect(selectCard.getAttribute("aria-pressed")).toBe("true");

  await act(async () =>
    cards[1]
      .querySelector<HTMLButtonElement>('[aria-label="Controller settings"]')
      ?.click(),
  );
  expect(document.querySelector('[role="dialog"]')?.textContent).toContain(
    "usb:1",
  );
  await chooseOption("Select controller", "Second Pad");
  expect(fetchRequest).toHaveBeenCalledWith(
    "/api/adapters/adapter-2/controller",
    expect.objectContaining({ body: JSON.stringify({ controller_id: 2 }) }),
  );
  expect(cards[1].querySelector("h3")?.textContent).toBe("Second Pad");
  expect(send).toHaveBeenCalledTimes(1);

  const firstCard = button("Send manual and macro input through usb:0");
  const lastCard = button("Send manual and macro input through usb:3");
  const manual: AdapterInputStatus = { mode: "manual", macro: null };
  await act(async () =>
    lastCard.dispatchEvent(new MouseEvent("click", { bubbles: true, shiftKey: true })),
  );
  expect(send).toHaveBeenLastCalledWith({
    type: "select_adapters",
    adapter_ids: ["adapter-2", "adapter-3", "adapter-4"],
  });
  await act(async () =>
    receive?.({
      type: "status",
      ...manual,
      adapter_id: "adapter-2",
      adapter_statuses: { "adapter-2": manual, "adapter-3": manual, "adapter-4": manual },
    }),
  );
  expect(selectCard.getAttribute("aria-pressed")).toBe("true");
  expect(lastCard.getAttribute("aria-pressed")).toBe("true");
  expect(firstCard.getAttribute("aria-pressed")).toBe("false");

  await act(async () =>
    firstCard.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Enter", bubbles: true, ctrlKey: true, shiftKey: true }),
    ),
  );
  expect(send).toHaveBeenLastCalledWith({
    type: "select_adapters",
    adapter_ids: ["primary", "adapter-2", "adapter-3", "adapter-4"],
  });

  await act(async () =>
    lastCard.dispatchEvent(new MouseEvent("click", { bubbles: true, ctrlKey: true })),
  );
  expect(send).toHaveBeenLastCalledWith({
    type: "select_adapters",
    adapter_ids: ["primary", "adapter-2", "adapter-3"],
  });
  await act(async () =>
    selectCard.dispatchEvent(new MouseEvent("click", { bubbles: true, ctrlKey: true })),
  );
  expect(send).toHaveBeenLastCalledWith({
    type: "select_adapters",
    adapter_ids: ["primary", "adapter-3"],
  });

  await act(async () => firstCard.click());
  expect(send).toHaveBeenLastCalledWith({ type: "select_adapter", adapter_id: "primary" });
  const commands = send.mock.calls.length;
  await act(async () =>
    firstCard.dispatchEvent(new MouseEvent("click", { bubbles: true, ctrlKey: true })),
  );
  expect(send).toHaveBeenCalledTimes(commands);
});

it("offers controls based on the state of every selected adapter", async () => {
  vi.spyOn(window, "scrollTo").mockImplementation(() => {});
  vi.spyOn(socket, "start").mockImplementation(() => {});
  vi.spyOn(socket, "getState").mockReturnValue("open");
  const send = vi.spyOn(socket, "send").mockReturnValue(true);
  let receive: ((frame: ServerFrame) => void) | undefined;
  vi.spyOn(socket, "onFrame").mockImplementation((handler) => {
    receive = handler;
    return () => {};
  });
  const routeTree = createRootRoute({
    component: () => (
      <SocketProvider>
        <ManualControl />
        <MacroRunPanel
          names={["first", "second"]}
          listError={null}
          onRetry={() => {}}
          selected={null}
          onSelect={() => {}}
        />
      </SocketProvider>
    ),
  });
  const router = createRouter({ routeTree, history: createMemoryHistory() });
  await act(async () => {
    await router.load();
    root.render(<RouterProvider router={router} />);
  });

  const running: AdapterInputStatus = {
    mode: "macro",
    macro: { name: "first", state: "running" },
  };
  const paused: AdapterInputStatus = {
    mode: "macro",
    macro: { name: "second", state: "paused" },
  };
  const showStatus = async (secondary: AdapterInputStatus) => {
    await act(async () =>
      receive?.({
        type: "status",
        ...running,
        adapter_id: "primary",
        adapter_statuses: { primary: running, "adapter-2": secondary },
      }),
    );
  };

  await showStatus({ mode: "manual", macro: null });
  expect(button("Home").disabled).toBe(false);
  expect(button("Run").disabled).toBe(false);
  expect(button("Pause").disabled).toBe(false);
  await act(async () =>
    button("Home").dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })),
  );
  expect(send).toHaveBeenLastCalledWith({
    type: "state",
    buttons: ["HOME"],
    left: [0, 0],
    right: [0, 0],
  });

  await showStatus(paused);
  expect(button("Home").disabled).toBe(true);
  expect(button("Home").getAttribute("aria-pressed")).toBe("false");
  expect(button("Run").disabled).toBe(true);
  expect(button("Pause").disabled).toBe(false);
  await act(async () => button("Resume").click());
  expect(send).toHaveBeenLastCalledWith({ type: "macro", op: "resume" });
  await act(async () => button("Stop").click());
  expect(send).toHaveBeenLastCalledWith({ type: "macro", op: "cancel" });
});

it.each([
  { audioId: "", native: false },
  { audioId: "capture-audio", native: true },
])("starts and stops capture with native monitoring set to $native", async ({ audioId, native }) => {
  localStorage.setItem("ounce-bt.audio-input", audioId);
  const stopTrack = vi.fn();
  const track = Object.assign(new EventTarget(), {
    stop: stopTrack,
    readyState: "live",
  });
  const audioTrack = { label: "Capture card audio", stop: vi.fn() };
  const stream = {
    getTracks: () => [track, audioTrack],
    getVideoTracks: () => [track],
    getAudioTracks: () => [audioTrack],
  };
  const getUserMedia = vi.fn().mockResolvedValue(stream);
  const api = {
    start_capture_audio: vi.fn().mockResolvedValue(1),
    set_capture_volume: vi.fn().mockResolvedValue(undefined),
    stop_capture_audio: vi.fn().mockResolvedValue(undefined),
  };
  if (native) {
    vi.stubGlobal("pywebview", { api });
    vi.stubGlobal("MediaStream", class {
      readonly tracks: unknown[];

      constructor(tracks: unknown[]) {
        this.tracks = tracks;
      }
    });
  }
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
    audio: {
      ...(audioId ? { deviceId: { exact: audioId } } : {}),
      echoCancellation: { exact: false },
      noiseSuppression: { exact: false },
      autoGainControl: { exact: false },
    },
  });
  const video = container.querySelector("video");
  if (!video) throw new Error("Missing capture video");
  if (native) {
    expect(api.start_capture_audio).toHaveBeenCalledWith("Capture card audio");
    expect(video.srcObject).toEqual({ tracks: [track] });
    expect(audioTrack.stop).toHaveBeenCalledOnce();
    Object.defineProperty(video, "paused", { value: false, configurable: true });
    video.volume = 0.5;
    await act(async () => { video.dispatchEvent(new Event("volumechange")); });
    expect(api.set_capture_volume).toHaveBeenLastCalledWith(1, 0.5);
    video.muted = true;
    await act(async () => { video.dispatchEvent(new Event("volumechange")); });
    expect(api.set_capture_volume).toHaveBeenLastCalledWith(1, 0);
  } else {
    expect(video.srcObject).toBe(stream);
  }
  expect(button("Stop capture input").disabled).toBe(false);

  await act(async () => button("Stop capture input").click());
  expect(stopTrack).toHaveBeenCalledOnce();
  expect(audioTrack.stop).toHaveBeenCalledTimes(native ? 2 : 1);
  if (native) expect(api.stop_capture_audio).toHaveBeenCalledWith(1);
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

it("opens the settings camera preview without capturing audio", async () => {
  localStorage.setItem("ounce-bt.audio-input", "capture-audio");
  const stop = vi.fn();
  const getUserMedia = vi.fn().mockResolvedValue({ getTracks: () => [{ stop }] });
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: { getUserMedia },
  });

  await act(async () => root.render(
    <CaptureProvider>
      <CaptureDeviceSettings
        disabled={false}
        draftInputId="capture-card"
        onDraftInputChange={() => {}}
      />
    </CaptureProvider>,
  ));
  await act(async () => button("Show preview").click());
  expect(getUserMedia).toHaveBeenCalledWith({
    video: { deviceId: { exact: "capture-card" } },
    audio: false,
  });
  await act(async () => button("Hide preview").click());
  expect(stop).toHaveBeenCalledOnce();
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
  expect(button("Reset").disabled).toBe(true);
  await act(async () => button("Reset to default").click());
  await act(async () => button("Reset").click());
  expect(
    document
      .querySelector('[role="dialog"] [data-region="body"]')
      ?.getAttribute("fill"),
  ).toBe("#FF3344");
  expect(button("Save").disabled).toBe(true);
  await act(async () => button("Reset to default").click());
  expect(cardBodyColour()).toBe("#FF3344");
  await act(async () => button("Close").click());
  await act(async () => button("Discard changes").click());
  expect(cardBodyColour()).toBe("#FF3344");

  await act(async () => button("Edit controller colours").click());
  await act(async () => button("Reset to default").click());
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
