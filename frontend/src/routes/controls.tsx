import { useRef, useState } from "react";
import { SettingsDialog, type SettingsDialogHandle } from "@/src/components/settings/dialog";
import { createFileRoute, Navigate, useRouter } from "@tanstack/react-router";
import { useSelector } from "@tanstack/react-store";
import { MacroRunPanel } from "@/src/components/panels/macro-runner";
import { ManualControl } from "@/src/components/panels/manual-control";
import { ConnectionPanel } from "@/src/components/panels/connection";
import { loadMacroList } from "@/src/lib/load-macro-list";
import { generalSettingsStore } from "@/src/stores/general-settings";
import "@/src/App.css";

function ControlsHomepage() {
  const controlsOnlyHomepage = useSelector(
    generalSettingsStore,
    (settings) => settings.controlsOnlyHomepage,
  );
  return controlsOnlyHomepage ? <ControlsPage /> : <Navigate to="/" replace />;
}

function ControlsPage() {
  const macroList = Route.useLoaderData();
  const router = useRouter();
  const [selectedMacro, setSelectedMacro] = useState<string | null>(null);
  const settings = useRef<SettingsDialogHandle>(null);
  const hideManualControl = useSelector(
    generalSettingsStore,
    (settings) => settings.hideManualControl,
  );

  return (
    <div className="flex h-full w-full flex-col gap-6 p-4">
      <SettingsDialog ref={settings} />
      <main className="mx-auto w-full max-w-7xl space-y-6 pb-6">
        <div className="max-w-xl">
          <ConnectionPanel onEditPreset={(preset) => settings.current?.openPreset(preset)} />
        </div>
        <div
          className={
            hideManualControl ? "grid min-h-104" : "grid items-stretch gap-6 xl:grid-cols-2"
          }
        >
          {!hideManualControl && (
            <div className="min-w-0 overflow-x-auto">
              <h2 className="mb-2 text-left text-lg font-semibold">Manual control</h2>
              <ManualControl />
            </div>
          )}
          <div className={hideManualControl ? "min-w-0" : "h-72 min-w-0 xl:h-auto"}>
            <MacroRunPanel
              fillHeight
              names={macroList.kind === "loaded" ? macroList.names : []}
              listError={macroList.kind === "error" ? macroList.message : null}
              onRetry={() => void router.invalidate()}
              selected={selectedMacro}
              onSelect={setSelectedMacro}
            />
          </div>
        </div>
      </main>
    </div>
  );
}

export const Route = createFileRoute("/controls")({
  loader: loadMacroList,
  component: ControlsHomepage,
});
