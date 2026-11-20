import { useEffect, useState } from "react";
import { Effect } from "effect";
import { GearSixIcon, PencilSimpleIcon } from "@phosphor-icons/react";
import { Button } from "@/src/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/src/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/src/components/ui/select";
import type { useControllers } from "@/src/hooks/use-controllers";
import { useMacroRunner } from "@/src/hooks/use-macro-runner";
import { listPresets } from "@/src/lib/api";
import { errorMessage } from "@/src/lib/errors";
import type { PresetInfo } from "@/src/lib/types";
import { VibrationSetting } from "./vibration-setting";

export function ControllerMappingDialog({
  controller,
  onEditPreset,
}: {
  controller: ReturnType<typeof useControllers>;
  onEditPreset: (preset: PresetInfo) => void;
}) {
  const [open, setOpen] = useState(false);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger
        render={
          <Button
            variant="ghost"
            size="icon-sm"
            className="rounded-lg"
            aria-label="Controller settings"
            title="Controller settings"
          />
        }
      >
        <GearSixIcon weight="fill" />
      </DialogTrigger>
      <DialogContent className="gap-4 bg-background sm:max-w-xl">
        <DialogHeader className="pr-8">
          <DialogTitle>Controller settings</DialogTitle>
        </DialogHeader>
        {open && (
          <MappingControls
            controller={controller}
            onEditPreset={(preset) => {
              setOpen(false);
              onEditPreset(preset);
            }}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}

function MappingControls({
  controller,
  onEditPreset,
}: {
  controller: ReturnType<typeof useControllers>;
  onEditPreset: (preset: PresetInfo) => void;
}) {
  const { available, controllers, active, activeInfo, preset, pending, error, update } = controller;
  const { macroActive } = useMacroRunner();
  const [presets, setPresets] = useState<Effect.Success<ReturnType<typeof listPresets>> | null>(
    null,
  );
  const [loadError, setLoadError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let disposed = false;
    void Effect.runPromise(listPresets())
      .then((result) => {
        if (!disposed) {
          setPresets(result);
          setLoadError(null);
        }
      })
      .catch((cause: unknown) => {
        if (!disposed) setLoadError(errorMessage(cause));
      });
    return () => {
      disposed = true;
    };
  }, [attempt]);

  const changing = pending !== null;
  const activePreset = presets?.presets.find(
    (entry) => entry.filename === (preset ?? presets.active),
  );

  return (
    <div className="space-y-4" aria-busy={changing}>
      <div className="space-y-3">
        <div className="grid grid-cols-[7.5rem_minmax(0,1fr)] items-center gap-x-2 gap-y-1">
          <p className="text-sm font-medium">Controller</p>
          <Select
            value={active}
            disabled={!available || controllers.length === 0 || changing || macroActive}
            onValueChange={(value) => {
              if (value !== null && value !== active) void update({ kind: "selecting", id: value });
            }}
          >
            <SelectTrigger className="w-full min-w-0" aria-label="Select controller">
              <SelectValue placeholder="No controllers detected">
                {activeInfo ? <span className="truncate">{activeInfo.name}</span> : null}
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              {controllers.map((entry) => (
                <SelectItem key={entry.guid} value={entry.guid}>
                  {entry.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {!available && (
            <p className="col-start-2 text-xs text-muted-foreground">
              Controller service unavailable.
            </p>
          )}
        </div>
        <div className="grid grid-cols-[7.5rem_minmax(0,1fr)] items-center gap-x-2 gap-y-1">
          <p className="text-sm font-medium">Mapping preset</p>
          <div className="flex min-w-0 items-center gap-1">
            <Select
              value={activePreset?.filename ?? null}
              disabled={changing || macroActive || !!loadError || !presets?.presets.length}
              onValueChange={(value) => {
                if (value !== null && value !== activePreset?.filename) {
                  void update({ kind: "applying", preset: value });
                }
              }}
            >
              <SelectTrigger className="w-full min-w-0" aria-label="Mapping preset">
                <SelectValue
                  placeholder={presets || loadError ? "No preset selected" : "Loading presets…"}
                >
                  {activePreset ? <span className="truncate">{activePreset.name}</span> : null}
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                {presets?.presets.map((entry) => (
                  <SelectItem key={entry.filename} value={entry.filename}>
                    {entry.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button
              type="button"
              size="icon"
              variant="ghost"
              aria-label="Edit mapping preset"
              title="Edit mapping preset"
              disabled={!activePreset || changing}
              onClick={() => {
                if (activePreset) onEditPreset(activePreset);
              }}
            >
              <PencilSimpleIcon />
            </Button>
          </div>
          {loadError && (
            <div className="col-start-2 flex items-center justify-between gap-2">
              <p role="alert" className="text-sm text-destructive">
                {loadError}
              </p>
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setPresets(null);
                  setLoadError(null);
                  setAttempt((current) => current + 1);
                }}
              >
                Retry
              </Button>
            </div>
          )}
        </div>
      </div>
      <VibrationSetting controllerGuid={activeInfo?.guid ?? null} />
      {pending && (
        <p role="status">{pending === "applying" ? "Applying preset…" : "Switching controller…"}</p>
      )}
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      {macroActive && (
        <p className="text-xs text-muted-foreground">
          Controller and preset changes are locked while a macro runs.
        </p>
      )}
    </div>
  );
}
