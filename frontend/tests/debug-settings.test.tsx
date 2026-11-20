// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { Effect } from "effect";
import Credits from "@/src/components/settings/credits";
import { DebugSettings } from "@/src/components/settings/debug-settings";
import { saveDebugAndRestart } from "@/src/lib/api";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
vi.mock("@/src/lib/api", () => ({
  getConfig: () =>
    Effect.succeed({
      nolog: false,
      bumble_logging: true,
      ws_auth_required: true,
      macro_rate_hz: 120,
      tick_rate_hz: 132,
    }),
  getDebugStatus: () =>
    Effect.succeed({
      bd_address: "98:B6:E9:12:34:56",
      bluetooth: { state: "disconnected", pairing: false },
      acl_connected: false,
      hid_control_ready: false,
      hid_interrupt_ready: false,
      switch_devices: [{ address: "AA:BB:CC:DD:EE:FF", name: "Living room Switch" }],
      restart_available: true,
      address_regeneration_available: true,
    }),
  saveDebugAndRestart: vi.fn(() => Effect.succeed({ restarting: true })),
}));
const container = document.createElement("div");
document.body.append(container);
let root = createRoot(container);
afterEach(async () => {
  await act(async () => root.unmount());
  root = createRoot(container);
  vi.clearAllMocks();
});
async function clickText(text: string) {
  const button = Array.from(document.querySelectorAll("button")).find(
    (node) => node.textContent === text,
  );
  if (!button) throw new Error(`Missing button: ${text}`);
  await act(async () => button.click());
}
describe("debug settings", () => {
  it("toggles only after ten presses on the first plain Ounce-bt text", async () => {
    const toggle = vi.fn();
    await act(async () => root.render(<Credits onToggleDebug={toggle} />));
    const name = Array.from(container.querySelectorAll("span")).find(
      (node) => node.textContent === "Ounce-bt",
    );
    if (!name) throw new Error("Missing credits text");
    expect(name.closest("a, button")).toBeNull();
    await act(async () => {
      for (let i = 0; i < 9; i++) name.click();
    });
    expect(toggle).not.toHaveBeenCalled();
    await act(async () => name.click());
    expect(toggle).toHaveBeenCalledTimes(1);
    await act(async () => {
      for (let i = 0; i < 10; i++) name.click();
    });
    expect(toggle).toHaveBeenCalledTimes(2);
  });
  it("shows named Switch addresses and keeps JSON collapsed initially", async () => {
    const hide = vi.fn();
    await act(async () =>
      root.render(<DebugSettings active onStateChange={() => {}} onHideDebug={hide} />),
    );
    expect(container.textContent).toContain("Living room Switch");
    expect(container.textContent).toContain("AA:BB:CC:DD:EE:FF");
    expect(container.querySelector("details")?.open).toBe(false);
    const visibility = container.querySelector<HTMLElement>("#debug-visible");
    await act(async () => visibility?.click());
    expect(hide).toHaveBeenCalledOnce();
    expect(saveDebugAndRestart).not.toHaveBeenCalled();
  });
  it("steps rates with buttons, keyboard and wheel without saving", async () => {
    await act(async () =>
      root.render(<DebugSettings active onStateChange={() => {}} onHideDebug={() => {}} />),
    );
    const input = container.querySelector<HTMLInputElement>("#debug-macro-rate");
    if (!input) throw new Error("Missing macro rate input");
    const increment = container.querySelector<HTMLButtonElement>(
      '[aria-label="Increase macro rate, hz"]',
    );
    const decrement = container.querySelector<HTMLButtonElement>(
      '[aria-label="Decrease macro rate, hz"]',
    );
    if (!increment || !decrement) throw new Error("Missing rate buttons");
    await act(async () => increment.click());
    expect(input.value).toBe("121");
    await act(async () => decrement.click());
    expect(input.value).toBe("120");
    await act(async () => input.focus());
    await act(async () => {
      input.dispatchEvent(
        new WheelEvent("wheel", { deltaY: -100, bubbles: true, cancelable: true }),
      );
    });
    expect(input.value).toBe("121");
    await act(async () => {
      input.dispatchEvent(
        new WheelEvent("wheel", { deltaY: 100, bubbles: true, cancelable: true }),
      );
    });
    expect(input.value).toBe("120");
    await act(async () => {
      input.dispatchEvent(new KeyboardEvent("keydown", { key: "End", bubbles: true }));
    });
    expect(input.value).toBe("1,000");
    await act(async () => increment.click());
    expect(input.value).toBe("1,000");
    expect(saveDebugAndRestart).not.toHaveBeenCalled();
  });
  it("grays out Bumble logging without clearing its saved checkbox state", async () => {
    await act(async () =>
      root.render(<DebugSettings active onStateChange={() => {}} onHideDebug={() => {}} />),
    );
    const logging = container.querySelector<HTMLInputElement>("#debug-logging");
    const bumble = container.querySelector<HTMLInputElement>("#debug-bumble");
    if (!logging || !bumble) throw new Error("Missing logging controls");
    expect(bumble.checked).toBe(true);
    await act(async () => logging.click());
    expect(bumble.disabled).toBe(true);
    expect(bumble.checked).toBe(true);
    expect(
      container
        .querySelector('label[for="debug-bumble"]')
        ?.parentElement?.parentElement?.classList.contains("opacity-50"),
    ).toBe(true);
    await act(async () => bumble.click());
    expect(bumble.checked).toBe(true);
    await act(async () => logging.click());
    expect(bumble.disabled).toBe(false);
    expect(bumble.checked).toBe(true);
    expect(
      container
        .querySelector('label[for="debug-bumble"]')
        ?.parentElement?.parentElement?.classList.contains("opacity-50"),
    ).toBe(false);
  });
  it("keeps edits local until restart confirmation and lets the user back out", async () => {
    await act(async () =>
      root.render(<DebugSettings active onStateChange={() => {}} onHideDebug={() => {}} />),
    );
    expect(container.textContent).toContain("98:B6:E9:12:34:56");
    await clickText("Regenerate BD address");
    await clickText("Save debug settings");
    expect(document.body.textContent).toContain(
      "All saved Switch devices and pairing keys will be deleted",
    );
    expect(saveDebugAndRestart).not.toHaveBeenCalled();
    await clickText("Back");
    expect(saveDebugAndRestart).not.toHaveBeenCalled();
    await clickText("Save debug settings");
    await clickText("Save and restart");
    expect(saveDebugAndRestart).toHaveBeenCalledExactlyOnceWith(
      {
        nolog: false,
        bumble_logging: true,
        ws_auth_required: true,
        macro_rate_hz: 120,
        tick_rate_hz: 132,
      },
      true,
    );
  });
});
