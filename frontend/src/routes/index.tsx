import { useRef, useState } from "react";
import { SettingsDialog, type SettingsDialogHandle } from "@/src/components/settings/dialog";
import { createFileRoute, Navigate, useRouter } from "@tanstack/react-router";
import { CapturePreview } from "@/src/components/panels/capture-preview";
import { MacroRunPanel } from "@/src/components/panels/macro-runner";
import { ManualControl } from "@/src/components/panels/manual-control";
import { ConnectionPanel } from "@/src/components/panels/connection";
import { useSelector } from "@tanstack/react-store";
import { loadMacroList } from "@/src/lib/load-macro-list";
import { generalSettingsStore } from "@/src/stores/general-settings";
import "@/src/App.css";

function Homepage() {
  const controlsOnlyHomepage = useSelector(
    generalSettingsStore,
    (settings) => settings.controlsOnlyHomepage,
  );
  return controlsOnlyHomepage ? <Navigate to="/controls" replace /> : <PreviewPage />;
}

function PreviewPage() {
  const macroList = Route.useLoaderData();
  const router = useRouter();
  const [selectedMacro, setSelectedMacro] = useState<string | null>(null);
  const settings = useRef<SettingsDialogHandle>(null);

  return (
    <div className="flex h-full w-full flex-col gap-6 bg-background p-4">
      <SettingsDialog ref={settings} />
      <div className="flex w-full flex-col items-start gap-4 lg:flex-row">
        <div className="flex w-full min-w-0 items-center justify-center lg:sticky lg:top-4 lg:h-[calc(100dvh-6rem)] lg:flex-1">
          <CapturePreview />
        </div>
        <div className="flex w-full min-w-0 flex-col space-y-4 lg:w-1/3 lg:shrink-0">
          <ConnectionPanel onEditPreset={(preset) => settings.current?.openPreset(preset)} />
          <MacroRunPanel
            names={macroList.kind === "loaded" ? macroList.names : []}
            listError={macroList.kind === "error" ? macroList.message : null}
            onRetry={() => void router.invalidate()}
            selected={selectedMacro}
            onSelect={setSelectedMacro}
          />
          <div className="min-w-0">
            <h2 className="mb-2 text-left text-lg font-semibold">Manual control</h2>
            <ManualControl />
          </div>
        </div>
      </div>
    </div>
  );
}

export const Route = createFileRoute("/")({
  loader: loadMacroList,
  component: Homepage,
});
