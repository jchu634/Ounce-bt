import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/src/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/src/components/ui/tabs";
import { Button } from "@/src/components/ui/button";
import { useSelector } from "@tanstack/react-store";
import {
  generalSettingsStore,
  setControlsOnlyHomepage,
  setHideManualControl,
  setTheme,
} from "@/src/stores/general-settings";
import { cn } from "cn";
import { GearSixIcon } from "@phosphor-icons/react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Effect } from "effect";
import { useCaptureControls, useCaptureInput } from "@/src/hooks/use-capture";

import { Checkbox } from "@/src/components/ui/checkbox";
import { ToggleGroup, ToggleGroupItem } from "@/src/components/ui/toggle-group";
import { Separator } from "@/src/components/ui/separator";
import { Label } from "@/src/components/ui/label";

import { AudioInputSettings } from "@/src/components/settings/audio-input-settings";
import type { PresetEditorHandle } from "@/src/components/editors/preset-editor";
import { ControllerSettings } from "@/src/components/settings/controller-settings";
import { CaptureDeviceSettings } from "@/src/components/settings/capture-device-settings";
import { AppearanceSettings } from "@/src/components/settings/appearance-settings";
import Credits from "@/src/components/settings/credits";

import { DebugSettings } from "@/src/components/settings/debug-settings";

import { getConfig, patchConfig, listPresets } from "@/src/lib/api";
import { errorMessage } from "@/src/lib/errors";
import type { PresetInfo } from "@/src/lib/types";

const SETTINGS_DESCRIPTIONS: Record<string, string> = {
  general: "General settings.",
  controller: "Choose a controller and manage its mapping presets.",
  appearance: "Choose how your controller appears on the Switch.",
  credits: "Acknowledgements and Licenses",
  debug: "Inspect connection states and change debug settings.",
};

export function SettingsDialog({ className }: { className?: string }) {
  const [open, setOpen] = useState(false);
  const [debugEnabled, setDebugEnabled] = useState(false);
  const [debugError, setDebugError] = useState<string | null>(null);
  const debugTogglePending = useRef(false);
  const [debugState, setDebugState] = useState({ dirty: false, saving: false });
  const [debugSession, setDebugSession] = useState(0);
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    void Effect.runPromise(getConfig())
      .then((config) => {
        if (!cancelled) setDebugEnabled(config.debug_enabled === true);
      })
      .catch((error: unknown) => {
        if (!cancelled) setDebugError(errorMessage(error));
      });
    return () => {
      cancelled = true;
    };
  }, [open]);

  async function toggleDebug() {
    if (debugTogglePending.current) return;
    debugTogglePending.current = true;
    try {
      const result = await Effect.runPromise(patchConfig({ debug_enabled: !debugEnabled }));
      setDebugEnabled(result.config.debug_enabled === true);
      if (result.config.debug_enabled !== true) {
        setCurrentTab("credits");
        setDebugState({ dirty: false, saving: false });
      }
      setDebugError(null);
    } catch (error) {
      setDebugError(errorMessage(error));
    } finally {
      debugTogglePending.current = false;
    }
  }
  const [discardPromptOpen, setDiscardPromptOpen] = useState(false);
  const [currentTab, setCurrentTab] = useState("general");
  const [presets, setPresets] = useState<PresetInfo[]>([]);
  const [presetsLoading, setPresetsLoading] = useState(false);
  const [presetsError, setPresetsError] = useState<string | null>(null);
  const presetRequestId = useRef(0);
  const controllerSettings = useRef<PresetEditorHandle | null>(null);
  const pendingDiscard = useRef<(() => void) | null>(null);
  const refreshPresets = useCallback(() => {
    const requestId = ++presetRequestId.current;
    setPresetsLoading(true);
    setPresetsError(null);
    void Effect.runPromise(listPresets())
      .then(({ presets }) => {
        if (requestId === presetRequestId.current) setPresets(presets);
      })
      .catch((error: unknown) => {
        if (requestId === presetRequestId.current) setPresetsError(errorMessage(error));
      })
      .finally(() => {
        if (requestId === presetRequestId.current) setPresetsLoading(false);
      });
  }, []);
  const controlsOnlyHomepage = useSelector(
    generalSettingsStore,
    (settings) => settings.controlsOnlyHomepage,
  );
  const hideManualControl = useSelector(
    generalSettingsStore,
    (settings) => settings.hideManualControl,
  );
  const theme = useSelector(generalSettingsStore, (settings) => settings.theme);
  const [appearanceState, setAppearanceState] = useState({ dirty: false, saving: false });
  const [appearanceSession, setAppearanceSession] = useState(0);
  const [draftControlsOnlyHomepage, setDraftControlsOnlyHomepage] = useState(controlsOnlyHomepage);
  const { selectedAudioInputId, selectedCameraInputId, selectInputs } = useCaptureInput();
  const [draftAudioInputId, setDraftAudioInputId] = useState(selectedAudioInputId);
  const [draftCaptureInputId, setDraftCaptureInputId] = useState(selectedCameraInputId);
  const { stop, starting } = useCaptureControls();
  const hasUnsavedInputChanges =
    draftAudioInputId !== selectedAudioInputId || draftCaptureInputId !== selectedCameraInputId;

  function closeSettings() {
    setOpen(false);
    if (draftControlsOnlyHomepage !== controlsOnlyHomepage) {
      if (draftControlsOnlyHomepage) stop();
      setControlsOnlyHomepage(draftControlsOnlyHomepage);
    }
  }

  function requestNavigation(navigate: () => void, closing = false) {
    if (appearanceState.saving || debugState.saving) return;
    const continueNavigation = () => {
      if (
        (currentTab === "appearance" && appearanceState.dirty) ||
        (currentTab === "debug" && debugState.dirty) ||
        (closing && (hasUnsavedInputChanges || appearanceState.dirty || debugState.dirty))
      ) {
        pendingDiscard.current = navigate;
        setDiscardPromptOpen(true);
        return;
      }
      navigate();
    };
    if (currentTab === "controller" && controllerSettings.current) {
      controllerSettings.current.requestNavigation(continueNavigation);
    } else {
      continueNavigation();
    }
  }

  return (
    <>
      <Dialog
        open={open}
        onOpenChange={(nextOpen) => {
          if (nextOpen) {
            setOpen(true);
            setAppearanceState({ dirty: false, saving: false });
            setAppearanceSession((session) => session + 1);
            if (currentTab === "controller") refreshPresets();
            setDraftControlsOnlyHomepage(controlsOnlyHomepage);
            setDraftAudioInputId(selectedAudioInputId);
            setDraftCaptureInputId(selectedCameraInputId);
            return;
          }

          requestNavigation(closeSettings, true);
        }}
      >
        <DialogTrigger
          render={
            <Button
              className={cn(
                "fixed top-5 right-4 z-40 bg-muted-foreground dark:text-gray-900 dark:hover:bg-red-800 dark:hover:text-white",
                className,
              )}
            />
          }
        >
          General Settings
          <GearSixIcon weight="fill" className="size-5" />
        </DialogTrigger>
        <DialogContent className="flex h-4/5 min-w-4/5 flex-col bg-background">
          <DialogHeader>
            <DialogTitle>Settings</DialogTitle>

            <DialogDescription>{SETTINGS_DESCRIPTIONS[currentTab]}</DialogDescription>
          </DialogHeader>
          <Tabs
            value={currentTab}
            onValueChange={(newTab) => {
              if (newTab === currentTab) return;
              requestNavigation(() => {
                setCurrentTab(newTab);
                if (newTab === "controller") refreshPresets();
              });
            }}
            orientation="vertical"
            className="min-h-0 min-w-0 flex-1 flex-col overflow-hidden sm:flex-row"
          >
            <TabsList className="shrink-0 max-sm:w-full max-sm:flex-row">
              <TabsTrigger value="general">General</TabsTrigger>
              <TabsTrigger value="controller">Controller</TabsTrigger>
              <TabsTrigger value="appearance">Appearance</TabsTrigger>
              <TabsTrigger value="credits">Credits</TabsTrigger>
              {debugEnabled && <TabsTrigger value="debug">Debug</TabsTrigger>}
            </TabsList>
            <TabsContent
              className="app-scrollbar min-h-0 min-w-0 space-y-4 overflow-x-hidden overflow-y-auto p-2"
              value="general"
            >
              <div className="flex flex-col gap-4">
                <h2 className="text-lg font-semibold text-foreground">Input Settings</h2>
                <AudioInputSettings
                  key={String(draftControlsOnlyHomepage)}
                  disabled={draftControlsOnlyHomepage}
                  selectedId={draftAudioInputId}
                  onSelectedIdChange={setDraftAudioInputId}
                />
                <CaptureDeviceSettings
                  disabled={draftControlsOnlyHomepage}
                  draftInputId={draftCaptureInputId}
                  onDraftInputChange={setDraftCaptureInputId}
                />
                <Button
                  disabled={
                    draftControlsOnlyHomepage ||
                    (draftAudioInputId === selectedAudioInputId &&
                      draftCaptureInputId === selectedCameraInputId)
                  }
                  onClick={() => {
                    selectInputs({
                      audioDeviceId: draftAudioInputId,
                      videoDeviceId: draftCaptureInputId,
                    });
                  }}
                  className="w-50 max-w-full"
                >
                  Save input settings
                </Button>
              </div>
              <Separator />
              <div className="flex w-full max-w-180 items-center justify-between gap-4">
                <div className="flex flex-col gap-1">
                  <Label htmlFor="controls-only-homepage">Controls-only homepage (WIP)</Label>
                  <p id="controls-only-description" className="text-sm text-muted-foreground">
                    Focus on macros and manual control without the capture card preview.
                  </p>
                </div>
                <Checkbox
                  id="controls-only-homepage"
                  aria-describedby="controls-only-description"
                  checked={draftControlsOnlyHomepage}
                  disabled={starting}
                  onCheckedChange={setDraftControlsOnlyHomepage}
                />
              </div>
              <div className="flex w-full max-w-180 items-center justify-between gap-4">
                <div className="flex flex-col gap-1">
                  <Label htmlFor="hide-manual-control">Hide manual control</Label>
                  <p id="hide-manual-control-description" className="text-sm text-muted-foreground">
                    Show only macros on the controls-only homepage.
                  </p>
                </div>
                <Checkbox
                  id="hide-manual-control"
                  aria-describedby="hide-manual-control-description"
                  checked={hideManualControl}
                  disabled={!draftControlsOnlyHomepage}
                  onCheckedChange={setHideManualControl}
                />
              </div>
              <Separator />
              <section className="flex flex-wrap items-center justify-between gap-4">
                <div className="space-y-1">
                  <Label id="theme-label">Theme</Label>
                  <p className="text-sm text-muted-foreground">
                    Choose light, dark, or follow your system setting.
                  </p>
                </div>
                <ToggleGroup
                  aria-labelledby="theme-label"
                  value={[theme]}
                  onValueChange={(values) => {
                    const selected = values.find(
                      (value) => value === "light" || value === "dark" || value === "system",
                    );
                    if (selected === "light" || selected === "dark" || selected === "system")
                      setTheme(selected);
                  }}
                  className="inline-flex rounded-md border border-input bg-background p-1"
                >
                  <ToggleGroupItem value="light">Light</ToggleGroupItem>
                  <ToggleGroupItem value="dark">Dark</ToggleGroupItem>
                  <ToggleGroupItem value="system">System</ToggleGroupItem>
                </ToggleGroup>
              </section>
            </TabsContent>
            <TabsContent
              className="app-scrollbar min-h-0 min-w-0 overflow-y-auto p-2"
              value="controller"
            >
              <ControllerSettings
                ref={controllerSettings}
                presets={presets}
                loading={presetsLoading}
                listError={presetsError}
                onRefresh={refreshPresets}
              />
            </TabsContent>
            <TabsContent
              className="app-scrollbar min-h-0 min-w-0 overflow-y-auto p-2"
              value="appearance"
              keepMounted
            >
              <AppearanceSettings key={appearanceSession} onStateChange={setAppearanceState} />
            </TabsContent>
            <TabsContent
              className="app-scrollbar min-h-0 min-w-0 overflow-y-auto p-2"
              value="credits"
            >
              <Credits onToggleDebug={() => void toggleDebug()} />
              {debugError && <p role="alert">{debugError}</p>}
            </TabsContent>
            {debugEnabled && (
              <TabsContent
                value="debug"
                keepMounted
                className="app-scrollbar min-h-0 min-w-0 overflow-y-auto p-2"
              >
                <DebugSettings
                  key={debugSession}
                  active={open && currentTab === "debug"}
                  onStateChange={setDebugState}
                  onHideDebug={() => requestNavigation(() => void toggleDebug())}
                />
              </TabsContent>
            )}
          </Tabs>
          <p className="shrink-0 text-right text-xs font-semibold text-muted-foreground">
            v{import.meta.env.VITE_APP_VERSION}
          </p>
        </DialogContent>
      </Dialog>
      <Dialog
        open={discardPromptOpen}
        onOpenChange={(nextOpen) => {
          setDiscardPromptOpen(nextOpen);
          if (!nextOpen) pendingDiscard.current = null;
        }}
      >
        <DialogContent showCloseButton={false}>
          <DialogHeader>
            <DialogTitle>Leave without saving?</DialogTitle>
            <DialogDescription>
              Your settings have unsaved changes. Leave and discard them?
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                pendingDiscard.current = null;
                setDiscardPromptOpen(false);
              }}
            >
              Keep editing
            </Button>
            <Button
              variant="destructive"
              onClick={() => {
                const navigate = pendingDiscard.current;
                pendingDiscard.current = null;
                setDiscardPromptOpen(false);
                setAppearanceState({ dirty: false, saving: false });
                setAppearanceSession((session) => session + 1);
                setDebugState({ dirty: false, saving: false });
                setDebugSession((session) => session + 1);
                navigate?.();
              }}
            >
              Leave without saving
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
