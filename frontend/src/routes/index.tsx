import { useState } from "react";
import { createFileRoute, Navigate, useRouter } from "@tanstack/react-router";
import { PlayIcon, SpinnerGapIcon, StopIcon, VideoCameraIcon } from "@phosphor-icons/react";
import { CapturePreview } from "@/src/components/panels/capture-preview";
import { MacroRunPanel } from "@/src/components/panels/macro-runner";
import { ManualControl } from "@/src/components/panels/manual-control";
import {
  ConnectionStatus,
  ConnectionToggleButton,
  SwitchConnection,
} from "@/src/components/panels/connection";
import { useSwitchConnection } from "@/src/lib/switch-connection";
import { Button } from "@/src/components/ui/button";
import { useCaptureControls, useCaptureInput } from "@/src/hooks/use-capture";
import { SettingsDialog } from "@/src/components/settings/dialog";
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
  const switchConnection = useSwitchConnection();
  const { selectedCameraInputId } = useCaptureInput();
  const { permission, requestAccess, requestingPermission, start, starting, stop, streaming } =
    useCaptureControls();
  const permissionGranted = permission === "granted" || permission === "unsupported";

  return (
    <div className="flex h-full w-full flex-col gap-6 bg-background px-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <SettingsDialog />
      </div>

      <div className="flex w-full flex-col items-start gap-4 lg:flex-row">
        <div className="flex w-full min-w-0 items-center justify-center lg:sticky lg:top-4 lg:h-[calc(100dvh-6rem)] lg:flex-1">
          <CapturePreview />
        </div>

        <div className="flex w-full min-w-0 flex-col space-y-4 lg:w-1/3 lg:shrink-0 lg:pt-8">
          <div className="flex items-center gap-4">
            <h2 className="text-lg font-semibold">Connection</h2>
            <ConnectionStatus
              status={switchConnection.status}
              statusError={switchConnection.statusError}
            />
          </div>
          <SwitchConnection connection={switchConnection} />
          <div className="flex gap-2">
            {permissionGranted ? (
              <Button
                onClick={streaming ? stop : () => void start(selectedCameraInputId)}
                variant={streaming ? "destructive" : "tertiary"}
                disabled={starting || !selectedCameraInputId}
                className="h-10 flex-1 text-sm 2xl:text-lg"
              >
                {starting ? (
                  <SpinnerGapIcon size={16} weight="bold" className="animate-spin" />
                ) : streaming ? (
                  <StopIcon size={16} weight="fill" />
                ) : (
                  <PlayIcon size={16} weight="fill" />
                )}
                {streaming ? "Stop Capture Input" : "Start Capture Input"}
              </Button>
            ) : (
              <Button
                className="h-10 min-w-0 flex-1"
                onClick={() => void requestAccess()}
                disabled={requestingPermission}
              >
                {requestingPermission ? (
                  <SpinnerGapIcon size={16} weight="bold" className="animate-spin" />
                ) : (
                  <VideoCameraIcon size={16} weight="fill" />
                )}
                Request camera access
              </Button>
            )}
            <ConnectionToggleButton
              status={switchConnection.status}
              address={switchConnection.selected}
              disabled={switchConnection.disabled}
              busy={switchConnection.busy}
              onReconnect={() =>
                void switchConnection.update("POST", {
                  address: switchConnection.selected,
                })
              }
              onDisconnect={() =>
                void switchConnection.update("POST", {
                  action: "disconnect",
                })
              }
              className="h-10 shrink-0 text-sm 2xl:text-lg"
            />
          </div>
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
