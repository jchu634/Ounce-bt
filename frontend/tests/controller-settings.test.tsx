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

vi.mock("@/src/components/settings/controller-panel", () => ({ ControllerPanel: () => null }));
vi.mock("@/src/components/settings/vibration-setting", () => ({ VibrationSetting: () => null }));
vi.mock("@/src/components/settings/controller-preset-picker", () => ({ PresetPicker: () => null }));
vi.mock("@/src/components/editors/json-editor", () => ({
  JsonEditor: ({ value }: JsonEditorProps) => <pre data-testid="json">{value}</pre>,
}));
vi.mock("@/src/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/src/lib/api")>()),
  getPreset: vi.fn((name: string) =>
    Effect.succeed({ name, contents: '{"name":"Loaded preset"}' }),
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
      '{"name":"Loaded preset"}',
    );
  });

  it("keeps the loaded editor when the preset list is refreshed", async () => {
    await renderPresets([activePreset]);
    await renderPresets([{ ...activePreset }]);
    expect(getPreset).toHaveBeenCalledTimes(1);
  });
});
