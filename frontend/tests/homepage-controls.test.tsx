// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { CapturePreview } from "@/src/components/panels/capture-preview";
import { CaptureProvider } from "@/src/hooks/use-capture";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

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
