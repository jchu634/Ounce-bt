import { useRef, useState } from "react";
import { VibrationSetting } from "@/src/components/settings/vibration-setting";
import { ControllerPanel } from "@/src/components/settings/controller-panel";
import { PresetEditor, type PresetEditorHandle } from "@/src/components/editors/preset-editor";
import { PresetPicker } from "@/src/components/settings/controller-preset-picker";
import type { PresetInfo } from "@/src/lib/types";

export function ControllerSettings({
  presets,
  loading,
  listError,
  onRefresh,
}: {
  presets: PresetInfo[];
  loading: boolean;
  listError: string | null;
  onRefresh: () => void;
}) {
  const [selection, setSelection] = useState<Pick<PresetInfo, "filename" | "builtin"> | null>();
  const selected = selection === undefined ? presets.find((preset) => preset.active) : selection;
  const selectedPreset = selected?.filename ?? null;
  const selectedBuiltin = selected?.builtin ?? false;
  const [editorSession, setEditorSession] = useState(0);
  const presetEditor = useRef<PresetEditorHandle | null>(null);

  function openPreset(name: string, builtin: boolean) {
    setEditorSession((session) => session + 1);
    setSelection({ filename: name, builtin });
  }

  function requestPreset(name: string, builtin: boolean) {
    if (name === selectedPreset) return;
    const navigate = () => openPreset(name, builtin);
    if (presetEditor.current === null) {
      navigate();
      return;
    }
    presetEditor.current.requestNavigation(navigate);
  }

  return (
    <div className="flex min-w-0 flex-col gap-6">
      <ControllerPanel />
      <VibrationSetting />

      <div className="space-y-4 2xl:flex 2xl:space-y-0 2xl:gap-x-4">
        <PresetPicker
          presets={presets}
          loading={loading}
          listError={listError}
          onRefresh={onRefresh}
          selected={selectedPreset}
          onSelect={(preset) => requestPreset(preset.filename, preset.builtin)}
          onDeleted={(name) => {
            if (selectedPreset === name) {
              setSelection(null);
            }
          }}
        />
        <PresetEditor
          key={`${editorSession}:${selectedPreset}`}
          ref={presetEditor}
          name={selectedPreset}
          builtin={selectedBuiltin}
          onSaved={(name) => {
            if (name !== selectedPreset || selectedBuiltin) openPreset(name, false);
            onRefresh();
          }}
        />
      </div>
    </div>
  );
}
