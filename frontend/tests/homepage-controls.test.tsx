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
import { toast, Toaster } from "@/src/components/ui/toast";

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
  Reflect.deleteProperty(navigator, "permissions");
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
      const paired = init?.method === "PUT";
      return Response.json({
        available: true, state: paired ? "connected" : "disconnected", pairing: false, address: null,
        player_number: null, peers: [], names: {}, failure_id: 0, failure: null,
        grip_reminder_id: paired ? 1 : 0,
      } satisfies BluetoothStatus);
    }
    if (path === "/api/adapters/primary/type") {
      controllerType = "joycon_l";
      return Response.json(inventory());
    }
    if (path === "/api/presets") return Response.json({ presets: [], active: null });
    if (path === "/api/config") return Response.json({ vibration_enabled: true, motion_enabled: true });
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
  const addToast = vi.spyOn(toast, "add");
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
  await act(async () => button("Close").click());
  await act(async () => button("Start pairing").click());
  expect(addToast).toHaveBeenCalledWith(expect.objectContaining({
    type: "info",
    description: expect.stringContaining("Press SL and SR macro"),
  }));
});

it("shows Joy-Con rail buttons above the triggers only when the selection includes Joy-Cons", async () => {
  vi.spyOn(socket, "start").mockImplementation(() => {});
  vi.spyOn(socket, "getState").mockReturnValue("open");
  const send = vi.spyOn(socket, "send").mockReturnValue(true);
  let receive: ((frame: ServerFrame) => void) | undefined;
  vi.spyOn(socket, "onFrame").mockImplementation((handler) => {
    receive = handler;
    return () => {};
  });
  await act(async () => root.render(<SocketProvider><ManualControl /></SocketProvider>));
  expect(container.querySelector('[aria-label="Joy-Con rail buttons"]')).toBeNull();
  await act(async () => receive?.({
    type: "status", mode: "manual", macro: null, has_joycons: true,
  }));
  const rails = container.querySelector('[aria-label="Joy-Con rail buttons"]');
  expect(rails?.nextElementSibling?.getAttribute("aria-label")).toBe("Triggers");
  expect(container.querySelector('[aria-label="SL + SR"]')).toBeNull();
  const grip = button("SL");
  expect(rails?.contains(button("SR"))).toBe(true);
  expect(rails?.contains(button("L"))).toBe(false);
  await act(async () => grip.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })));
  expect(send).toHaveBeenLastCalledWith({
    type: "state", buttons: ["SL"], left: [0, 0], right: [0, 0],
  });
  await act(async () => grip.dispatchEvent(new KeyboardEvent("keyup", { key: "Enter", bubbles: true })));
  expect(send).toHaveBeenLastCalledWith({
    type: "state", buttons: [], left: [0, 0], right: [0, 0],
  });
  await act(async () => receive?.({ type: "status", mode: "manual", macro: null }));
  expect(container.querySelector('[aria-label="Joy-Con rail buttons"]')).toBeNull();
});

it("reports incompatible macro controls through an error toast", async () => {
  vi.spyOn(socket, "start").mockImplementation(() => {});
  const addToast = vi.spyOn(toast, "add");
  let receive: ((frame: ServerFrame) => void) | undefined;
  vi.spyOn(socket, "onFrame").mockImplementation((handler) => {
    receive = handler;
    return () => {};
  });
  await act(async () => root.render(<SocketProvider><Toaster /></SocketProvider>));
  await act(async () => receive?.({
    type: "error",
    code: "macro_capability",
    message: "Macro is incompatible with the selected controller",
    detail: "Joy-Con (L) has no right stick.",
  }));
  expect(addToast).toHaveBeenCalledWith(expect.objectContaining({
    type: "error",
    description: "Joy-Con (L) has no right stick.",
  }));
  expect(document.querySelector('[data-slot="toast-description"]')?.textContent)
    .toBe("Joy-Con (L) has no right stick.");
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
    cards[0].querySelector('[aria-label="Select controller"]')?.textContent,
  ).toContain("First Pad");

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
  await act(async () => button("Close").click());
  await act(async () =>
    cards[1]
      .querySelector<HTMLButtonElement>('[aria-label="Select controller"]')
      ?.click(),
  );
  await act(async () => {
    const option = Array.from(
      document.querySelectorAll<HTMLElement>('[role="option"]'),
    ).find((el) => el.textContent?.trim() === "Second Pad");
    if (!option) throw new Error("Missing option: Second Pad");
    option.click();
  });
  expect(fetchRequest).toHaveBeenCalledWith(
    "/api/adapters/adapter-2/controller",
    expect.objectContaining({ body: JSON.stringify({ controller_id: 2 }) }),
  );
  expect(
    cards[1].querySelector('[aria-label="Select controller"]')?.textContent,
  ).toContain("Second Pad");
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
    video: {
      deviceId: { exact: "capture-card" },
      width: { ideal: 1920 },
      height: { ideal: 1080 },
      frameRate: { ideal: 60 },
    },
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
    video: {
      deviceId: { exact: "capture-card" },
      width: { ideal: 1920 },
      height: { ideal: 1080 },
      frameRate: { ideal: 60 },
    },
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
  let motionEnabled = true;
  const controllerVibration: Record<string, boolean> = {};
  const controllerMotion: Record<string, boolean> = {};
  const controllerStatus = {
    available: true,
    active: "test-pad",
    controllers: [
      { instance_id: 1, guid: "test-pad", name: "Test Gamepad", has_gyro: true },
      { instance_id: 2, guid: "second-pad", name: "Second Gamepad", has_gyro: true },
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
        if (typeof change.motion_enabled === "boolean")
          motionEnabled = change.motion_enabled;
        Object.assign(controllerVibration, change.controller_vibration);
        Object.assign(controllerMotion, change.controller_motion);
        return Response.json({
          config: {
            controller_colours: colours,
            vibration_enabled: vibrationEnabled,
            controller_vibration: controllerVibration,
            motion_enabled: motionEnabled,
            controller_motion: controllerMotion,
          },
          colours_reconnect_required: true,
        });
      }
      return Response.json({
        controller_colours: colours,
        vibration_enabled: vibrationEnabled,
        controller_vibration: controllerVibration,
        motion_enabled: motionEnabled,
        controller_motion: controllerMotion,
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
    if (path === "/api/adapters/primary/controller" && init?.method === "PUT") {
      controllerStatus.active = "second-pad";
      preset = "xbox";
      return Response.json({
        adapters: [],
        controllers: controllerStatus.controllers.map((c) => ({
          id: c.instance_id,
          name: c.name,
          guid: c.guid,
          has_gyro: c.has_gyro,
        })),
        controllers_available: true,
      });
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
  expect(container.querySelector("article")?.textContent).toContain(
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
    "/api/adapters/primary/controller",
    expect.objectContaining({
      method: "PUT",
      body: JSON.stringify({ controller_id: 2 }),
    }),
  );
  expect(
    container.querySelector('[aria-label="Select controller"]')?.textContent,
  ).toContain("Second Gamepad");
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
    "GeneralControllerAdvancedCredits",
  );
  await act(async () => button("Controller").click());
  expect(
    document.querySelector('[role="tabpanel"]:not([hidden])')?.textContent,
  ).toContain("Presets");
  expect(
    document.querySelector('[role="dialog"] [aria-label="Select controller"]'),
  ).toBeNull();
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

it("pairs and unpairs two Joy-Con adapters and switches between Combined and Individual input modes", async () => {
  type AdapterEntry = {
    id: string;
    transport: string;
    controller_id: number | null;
    preset: string | null;
    macro_mode: boolean;
    local_address: string | null;
    error: string | null;
    controller_type: BluetoothControllerType;
    combined_with: string | null;
    combined_input_mode: "combined" | "individual";
  };
  let adapters: AdapterEntry[] = [
    {
      id: "primary",
      transport: "usb:0",
      controller_id: 1,
      preset: "xbox",
      macro_mode: false,
      local_address: "02:00:00:00:00:01",
      error: null,
      controller_type: "pro",
      combined_with: null,
      combined_input_mode: "combined",
    },
    {
      id: "adapter-2",
      transport: "usb:1",
      controller_id: 2,
      preset: "switch",
      macro_mode: false,
      local_address: "02:00:00:00:00:02",
      error: null,
      controller_type: "joycon_l",
      combined_with: null,
      combined_input_mode: "combined",
    },
    {
      id: "adapter-3",
      transport: "usb:2",
      controller_id: null,
      preset: "playstation",
      macro_mode: false,
      local_address: "02:00:00:00:00:03",
      error: null,
      controller_type: "joycon_r",
      combined_with: null,
      combined_input_mode: "combined",
    },
  ];
  const controllers = [
    { id: 1, guid: "pad-1", name: "Xbox Controller" },
    { id: 2, guid: "pad-2", name: "DualSense Wireless" },
    { id: 3, guid: "pad-3", name: "Joy-Con (R)" },
  ];
  let joyconPairingEnabled = false;
  const inventory = () => ({
    adapters,
    controllers,
    controllers_available: true,
    joycon_pairing_enabled: joyconPairingEnabled,
  });
  const btStatus: BluetoothStatus = {
    available: true,
    pairing: false,
    state: "disconnected",
    address: null,
    player_number: null,
    peers: [],
    names: {},
    failure_id: 0,
    failure: null,
  };
  const fetchRequest = vi.fn(async (path: string, init?: RequestInit) => {
    if (path === "/api/adapters") return Response.json(inventory());
    if (path === "/api/bluetooth" || path.endsWith("/bluetooth")) return Response.json(btStatus);
    if (path === "/api/adapters/pair" && init?.method === "POST") {
      adapters = adapters.map((entry) =>
        entry.id === "adapter-2"
          ? { ...entry, combined_with: "adapter-3", combined_input_mode: "combined" }
          : entry.id === "adapter-3"
            ? { ...entry, combined_with: "adapter-2", combined_input_mode: "combined" }
            : entry,
      );
      return Response.json(inventory());
    }
    if (path === "/api/adapters/adapter-2/pair-mode" && init?.method === "PUT") {
      const { input_mode } = JSON.parse(String(init.body)) as {
        input_mode: "combined" | "individual";
      };
      adapters = adapters.map((entry) =>
        entry.id === "adapter-2" || entry.id === "adapter-3"
          ? { ...entry, combined_input_mode: input_mode }
          : entry,
      );
      return Response.json(inventory());
    }
    if (path === "/api/adapters/adapter-2/pair" && init?.method === "DELETE") {
      adapters = adapters.map((entry) =>
        entry.id === "adapter-2" || entry.id === "adapter-3"
          ? { ...entry, combined_with: null, combined_input_mode: "combined" }
          : entry,
      );
      return Response.json(inventory());
    }
    const presetMatch = path.match(/^\/api\/adapters\/([^/]+)\/preset\/([^/]+)$/);
    if (presetMatch && init?.method === "POST") {
      const [, id, presetName] = presetMatch;
      adapters = adapters.map((entry) =>
        entry.id === id ? { ...entry, preset: presetName } : entry,
      );
      return Response.json(inventory());
    }
    if (path.includes("/colours")) {
      return Response.json({
        controller_colours: DEFAULT_CONTROLLER_COLOURS,
        colours_reconnect_required: false,
      });
    }
    if (path === "/api/presets") {
      return Response.json({
        active: "xbox",
        presets: [
          { filename: "xbox", name: "Xbox", active: true, builtin: true },
          { filename: "switch", name: "Switch", active: false, builtin: true },
          { filename: "playstation", name: "PlayStation", active: false, builtin: true },
        ],
      });
    }
    if (path === "/api/config") {
      if (init?.method === "PATCH") {
        const change = JSON.parse(String(init.body)) as { joycon_pairing_enabled?: boolean };
        if (typeof change.joycon_pairing_enabled === "boolean") {
          joyconPairingEnabled = change.joycon_pairing_enabled;
        }
        return Response.json({
          config: {
            vibration_enabled: true,
            motion_enabled: true,
            joycon_pairing_enabled: joyconPairingEnabled,
          },
          colours_reconnect_required: false,
        });
      }
      return Response.json({
        vibration_enabled: true,
        motion_enabled: true,
        joycon_pairing_enabled: joyconPairingEnabled,
      });
    }
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
        <CaptureProvider>
          <SettingsDialog />
          <ConnectionPanel onEditPreset={() => {}} />
        </CaptureProvider>
      </SocketProvider>,
    );
  });

  // Joy-Con pairing is locked behind the Advanced settings tab by default.
  expect(
    Array.from(container.querySelectorAll("button")).find((el) => el.textContent?.trim() === "Pair"),
  ).toBeUndefined();

  await act(async () => button("General Settings").click());
  await act(async () => button("Advanced").click());
  const advancedPanel = document.querySelector('[role="tabpanel"]:not([hidden])');
  expect(advancedPanel?.textContent).toContain("not quite stable");
  const pairingCheckbox = advancedPanel?.querySelector<HTMLElement>('[role="checkbox"]');
  if (!pairingCheckbox) throw new Error("Missing Joy-Con pairing checkbox");
  await act(async () => pairingCheckbox.click());
  expect(fetchRequest).toHaveBeenCalledWith(
    "/api/config",
    expect.objectContaining({
      method: "PATCH",
      body: JSON.stringify({ joycon_pairing_enabled: true }),
    }),
  );
  await act(async () => button("Close").click());

  const manual: AdapterInputStatus = { mode: "manual", macro: null };
  // Selecting Pro + Joy-Con L keeps Pair disabled.
  await act(async () =>
    receive?.({
      type: "status",
      ...manual,
      adapter_id: "primary",
      adapter_statuses: { primary: manual, "adapter-2": manual },
    }),
  );
  expect(button("Pair").disabled).toBe(true);

  // Selecting Joy-Con L + Joy-Con R enables Pair.
  await act(async () =>
    receive?.({
      type: "status",
      ...manual,
      adapter_id: "adapter-2",
      adapter_statuses: { "adapter-2": manual, "adapter-3": manual },
    }),
  );
  expect(button("Pair").disabled).toBe(false);
  await act(async () => button("Pair").click());
  expect(fetchRequest).toHaveBeenCalledWith(
    "/api/adapters/pair",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ adapter_ids: ["adapter-2", "adapter-3"] }),
    }),
  );

  // Clicking either paired Joy-Con card selects both adapters together.
  await act(async () => button("Send manual and macro input through usb:2").click());
  expect(send).toHaveBeenLastCalledWith({
    type: "select_adapters",
    adapter_ids: ["adapter-2", "adapter-3"],
  });
  await act(async () => button("Send manual and macro input through usb:1").click());
  expect(send).toHaveBeenLastCalledWith({
    type: "select_adapters",
    adapter_ids: ["adapter-2", "adapter-3"],
  });
  // Ctrl-clicking primary adds it, then Ctrl-clicking either paired card toggles both paired cards out.
  await act(async () =>
    button("Send manual and macro input through usb:0").dispatchEvent(
      new MouseEvent("click", { bubbles: true, ctrlKey: true }),
    ),
  );
  expect(send).toHaveBeenLastCalledWith({
    type: "select_adapters",
    adapter_ids: ["primary", "adapter-2", "adapter-3"],
  });
  await act(async () =>
    button("Send manual and macro input through usb:2").dispatchEvent(
      new MouseEvent("click", { bubbles: true, ctrlKey: true }),
    ),
  );
  expect(send).toHaveBeenLastCalledWith({
    type: "select_adapter",
    adapter_id: "primary",
  });
  // Re-select the pair so Unpair header state is verified below.
  await act(async () =>
    receive?.({
      type: "status",
      ...manual,
      adapter_id: "primary",
      adapter_statuses: { primary: manual },
    }),
  );
  await act(async () =>
    receive?.({
      type: "status",
      ...manual,
      adapter_id: "adapter-2",
      adapter_statuses: { "adapter-2": manual, "adapter-3": manual },
    }),
  );

  // In default Combined mode, both icons render combined pair with opposite side greyed out.
  const cards = container.querySelectorAll("article");
  expect(cards).toHaveLength(3);
  expect(cards[1].querySelector('[data-side="joycon_r"][data-inactive="true"]')).not.toBeNull();
  expect(cards[2].querySelector('[data-side="joycon_l"][data-inactive="true"]')).not.toBeNull();
  expect(cards[2].querySelector("h3")?.textContent).toContain("Shared with DualSense Wireless");
  expect(button("Combined").getAttribute("aria-pressed")).toBe("true");
  expect(button("Individual").getAttribute("aria-pressed")).toBe("false");
  // Header button switches to Unpair when both paired cards are selected.
  expect(button("Unpair").disabled).toBe(false);

  // Switch to Individual mode -> single upright icons and partner preset dropdown in each dialog.
  await act(async () => button("Individual").click());
  expect(fetchRequest).toHaveBeenCalledWith(
    "/api/adapters/adapter-2/pair-mode",
    expect.objectContaining({
      method: "PUT",
      body: JSON.stringify({ input_mode: "individual" }),
    }),
  );
  expect(cards[1].querySelector('svg[viewBox="19 6 26 52"]')).not.toBeNull();
  expect(cards[2].querySelector('svg[viewBox="19 6 26 52"]')).not.toBeNull();

  // Open Left Joy-Con dialog -> includes Mapped preset heading and Joycon (L) / Joycon (R) dropdowns.
  await act(async () =>
    cards[1].querySelector<HTMLButtonElement>('[aria-label="Controller settings"]')?.click(),
  );
  expect(document.querySelector('[role="dialog"]')?.textContent).toContain("Mapped preset");
  expect(button("Joycon (L)").textContent).toContain("Switch");
  expect(button("Joycon (R)").textContent).toContain("PlayStation");
  await chooseOption("Joycon (R)", "Xbox");
  expect(fetchRequest).toHaveBeenCalledWith(
    "/api/adapters/adapter-3/preset/xbox",
    expect.objectContaining({ method: "POST" }),
  );
  await act(async () => button("Close").click());

  // Open Right Joy-Con dialog -> includes Mapped preset heading and Joycon (L) / Joycon (R) dropdowns.
  await act(async () =>
    cards[2].querySelector<HTMLButtonElement>('[aria-label="Controller settings"]')?.click(),
  );
  expect(document.querySelector('[role="dialog"]')?.textContent).toContain("Mapped preset");
  expect(button("Joycon (L)").textContent).toContain("Switch");
  expect(button("Joycon (R)").textContent).toContain("Xbox");
  await act(async () => button("Close").click());

  // Clicking the far-right unlink button requires confirmation before calling DELETE.
  await act(async () => button("Unpair usb:1 and usb:2").click());
  expect(document.querySelector('[role="dialog"]')?.textContent).toContain(
    "Unpair Joy-Con adapters?",
  );
  const dialogButtons = Array.from(
    document.querySelectorAll<HTMLButtonElement>('[role="dialog"] button'),
  );
  const confirmUnpair = dialogButtons.find((el) => el.textContent?.trim() === "Unpair");
  if (!confirmUnpair) throw new Error("Missing confirm Unpair button");
  await act(async () => confirmUnpair.click());
  expect(fetchRequest).toHaveBeenCalledWith(
    "/api/adapters/adapter-2/pair",
    expect.objectContaining({ method: "DELETE" }),
  );
  expect(container.querySelector('[aria-label="Paired Joy-Con input mode"]')).toBeNull();
});

it("syncs settings camera selection after requesting camera access and surfaces request errors", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string) => {
      if (path === "/api/config") return Response.json({ debug_enabled: false });
      return Response.json({}, { status: 404 });
    }),
  );
  const stop = vi.fn();
  const getUserMedia = vi
    .fn()
    .mockRejectedValueOnce(new DOMException("No camera", "NotFoundError"))
    .mockResolvedValueOnce({ getTracks: () => [{ stop }] });
  let granted = false;
  Object.defineProperty(navigator, "permissions", {
    configurable: true,
    value: {
      query: vi.fn(async () => ({ state: "prompt", onchange: null })),
    },
  });
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: {
      getUserMedia: vi.fn(async (constraints: MediaStreamConstraints) => {
        const stream = await getUserMedia(constraints);
        granted = true;
        return stream;
      }),
      enumerateDevices: vi.fn(async () =>
        granted
          ? [{ kind: "videoinput", deviceId: "usb-capture", label: "USB Video" }]
          : [{ kind: "videoinput", deviceId: "", label: "" }],
      ),
    },
  });

  await act(async () => {
    root.render(
      <CaptureProvider>
        <SettingsDialog />
      </CaptureProvider>,
    );
  });

  await act(async () => button("General Settings").click());
  expect(button("Show preview").disabled).toBe(true);
  expect(button("Request camera access").getAttribute("type")).toBe("button");

  // A non-permission failure shows an alert without marking permission denied.
  await act(async () => button("Request camera access").click());
  expect(document.querySelector('[role="alert"]')?.textContent).toBe(
    "No matching camera found.",
  );
  expect(button("Request camera access").disabled).toBe(false);

  // Once camera access succeeds, the dropdown and preview update cleanly with no unsaved diff.
  await act(async () => button("Request camera access").click());
  expect(stop).toHaveBeenCalledOnce();
  expect(button("Show preview").disabled).toBe(false);
  expect(button("Save input settings").disabled).toBe(true);
  expect(document.body.textContent).toContain("USB Video");

  // Closing settings does not trigger the unsaved changes confirmation.
  await act(async () => button("Close").click());
  expect(document.body.textContent).not.toContain("Leave without saving?");
});
