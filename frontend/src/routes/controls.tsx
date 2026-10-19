import { useState } from "react";
import { createFileRoute, Navigate, useRouter } from "@tanstack/react-router";
import { useSelector } from "@tanstack/react-store";
import { MacroRunPanel } from "@/src/components/panels/macro-runner";
import { ManualControl } from "@/src/components/panels/manual-control";
import {
  ConnectionStatus,
  ConnectionToggleButton,
  SwitchConnection,
} from "@/src/components/panels/connection";
import { useSwitchConnection } from "@/src/lib/switch-connection";
import { loadMacroList } from "@/src/lib/load-macro-list";
import { SettingsDialog } from "@/src/components/settings/dialog";
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
  const switchConnection = useSwitchConnection();

  return (
    <div className="flex h-full w-full flex-col gap-6 px-4">
      <div className="flex flex-wrap items-center justify-end gap-2">
        <SettingsDialog className="static" />
      </div>
      <main className="mx-auto w-full max-w-7xl pb-6">
        <h1 className="mb-6 text-2xl font-semibold">Controller</h1>
        <div className="mb-6 space-y-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-4">
              <h2 className="text-lg font-semibold">Connection</h2>
              <ConnectionStatus
                status={switchConnection.status}
                statusError={switchConnection.statusError}
              />
            </div>
            <ConnectionToggleButton
              status={switchConnection.status}
              address={switchConnection.selected}
              disabled={switchConnection.disabled}
              busy={switchConnection.busy}
              onReconnect={() =>
                void switchConnection.update("POST", { address: switchConnection.selected })
              }
              onDisconnect={() => void switchConnection.update("POST", { action: "disconnect" })}
            />
          </div>
          <div className="min-w-0">
            <SwitchConnection connection={switchConnection} />
          </div>
        </div>
        <div className="grid items-start gap-6 xl:grid-cols-2">
          <div className="min-w-0 rounded-md border border-border bg-card p-4">
            <MacroRunPanel
              names={macroList.kind === "loaded" ? macroList.names : []}
              listError={macroList.kind === "error" ? macroList.message : null}
              onRetry={() => void router.invalidate()}
              selected={selectedMacro}
              onSelect={setSelectedMacro}
            />
          </div>
          <div className="min-w-0 overflow-x-auto">
            <ManualControl />
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
