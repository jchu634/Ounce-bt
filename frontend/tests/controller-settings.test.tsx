// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { Effect } from "effect";
import { ControllerSettings } from "@/src/components/settings/controller-settings";
import { getPreset } from "@/src/lib/api";
import type { PresetInfo } from "@/src/lib/types";
import type { JsonEditorProps } from "@/src/components/editors/json-editor";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const presetContents = JSON.stringify({
  version: 2,
  name: "Loaded preset",
  mappings: {
    pro: {},
    joycon_l: { left_stick: { x_axis: 0, y_axis: 1 } },
    joycon_r: { right_stick: { x_axis: 0, y_axis: 1 } },
    combined: {},
  },
});

vi.mock("@/src/components/settings/vibration-setting", () => ({ VibrationSetting: () => null }));
vi.mock("@/src/components/settings/controller-preset-picker", () => ({ PresetPicker: () => null }));
vi.mock("@/src/components/editors/json-editor", () => ({
  JsonEditor: ({ value }: JsonEditorProps) => <pre data-testid="json">{value}</pre>,
}));
vi.mock("@/src/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/src/lib/api")>()),
  getPreset: vi.fn((name: string) =>
    Effect.succeed({ name, contents: presetContents }),
  ),
}));

const container = document.createElement("div");
document.body.append(container);
let root = createRoot(container);

afterEach(async () => {
  await act(async () => root.unmount());
  root = createRoot(container);
  vi.clearAllMocks();
});

async function renderPresets(presets: PresetInfo[]) {
  await act(async () => {
    root.render(
      <ControllerSettings
        presets={presets}
        loading={false}
        listError={null}
        onRefresh={() => {}}
      />,
    );
  });
}

const activePreset: PresetInfo = {
  filename: "xbox",
  name: "Xbox",
  builtin: true,
  description: "Xbox mapping",
  active: true,
};

describe("active preset selection", () => {
  it("loads the active preset when the list arrives after the editor mounts", async () => {
    await renderPresets([]);
    expect(getPreset).not.toHaveBeenCalled();
    await renderPresets([activePreset]);
    expect(getPreset).toHaveBeenCalledWith("xbox");
    const jsonButton = Array.from(container.querySelectorAll("button")).find((button) =>
      button.textContent?.includes("JSON Editor"),
    );
    expect(jsonButton).toBeDefined();
    await act(async () => jsonButton?.click());
    expect(container.querySelector('[data-testid="json"]')?.textContent).toBe(
      presetContents,
    );
  });

  it("keeps the loaded editor when the preset list is refreshed", async () => {
    await renderPresets([activePreset]);
    await renderPresets([{ ...activePreset }]);
    expect(getPreset).toHaveBeenCalledTimes(1);
  });

  it("switches output mappings and displays each controller's controls", async () => {
    await renderPresets([activePreset]);
    const group = container.querySelector('[aria-label="Output controller"]');
    const choose = async (label: string) => {
      const button = [...(group?.querySelectorAll("button") ?? [])].find(
        (item) => item.textContent === label,
      );
      expect(button).toBeDefined();
      await act(async () => button?.click());
    };
    const control = (label: string) => container.querySelector(
      `[aria-label="Physical input for ${label}"]`,
    );
    expect(control("SL")).toBeNull();
    expect(control("SR")).toBeNull();
    await choose("Joy-Con L");
    expect(control("SL")).not.toBeNull();
    expect(control("SR")).not.toBeNull();
    expect(control("A")).toBeNull();
    await choose("Joy-Con R");
    expect(control("SL")).not.toBeNull();
    expect(control("SR")).not.toBeNull();
    expect(control("D-pad up")).toBeNull();
    await choose("Joycons");
    expect(control("SL")).not.toBeNull();
    expect(control("SR")).not.toBeNull();
    expect(control("Left Joy-Con SL")).toBeNull();
    expect(control("Right Joy-Con SL")).toBeNull();
    expect(control("A")).not.toBeNull();
    expect(control("D-pad up")).not.toBeNull();
  });

  it("maps a whole stick in the Sticks panel and keeps Pro and Joy-Con edits independent", async () => {
    await renderPresets([activePreset]);
    const select = async (label: string, option: string) => {
      const trigger = container.querySelector<HTMLButtonElement>(`button[aria-label="${label}"]`);
      expect(trigger).not.toBeNull();
      await act(async () => trigger?.click());
      const item = [...document.querySelectorAll<HTMLElement>('[role="option"]')].find(
        (choice) => choice.textContent === option,
      );
      expect(item?.querySelector("svg")).not.toBeNull();
      await act(async () => item?.click());
    };
    const proStick = container.querySelector('[aria-label="Physical stick for left stick"]');
    expect(proStick?.closest("section")?.querySelector("h4")?.textContent).toBe("Sticks");
    await select("Physical stick for left stick", "Right stick");
    await select("Output controller", "Joy-Con R");
    expect(container.querySelector('[aria-label="Physical stick for left stick"]')).toBeNull();
    expect(container.querySelector('[aria-label="Physical stick for right stick"]')?.getAttribute("title"))
      .toBe("Right stick maps to left stick");
    await select("Physical stick for right stick", "Right stick");
    const jsonButton = [...container.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("JSON Editor"),
    );
    await act(async () => jsonButton?.click());
    const contents = container.querySelector('[data-testid="json"]')?.textContent;
    expect(JSON.parse(contents ?? "{}")).toMatchObject({
      mappings: {
        pro: { left_stick: { x_axis: 2, y_axis: 3 } },
        joycon_l: { left_stick: { x_axis: 0, y_axis: 1 } },
        joycon_r: { right_stick: { x_axis: 2, y_axis: 3 } },
      },
    });
  });
});
