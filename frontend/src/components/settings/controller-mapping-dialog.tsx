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
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/src/components/ui/select";
import { listPresets } from "@/src/lib/api";
import { errorMessage } from "@/src/lib/errors";
import type { PresetInfo } from "@/src/lib/types";
import { MotionSetting, VibrationSetting } from "./vibration-setting";
import { ControllerVariantIcon } from "./controller-preview";
import type { ControllerVariant } from "@/src/lib/controller-variants";

export type PartnerPresetSettings = {
  label: string;
  preset: string | null;
  macroMode: boolean;
  applyPreset: (preset: string) => void;
};

export type MappingSettings = {
  available: boolean;
  options: { id: string; name: string; disabled?: boolean }[];
  active: string | null;
  controllerGuid: string | null;
  hasGyro?: boolean;
  preset: string | null;
  pending: "selecting" | "applying" | null;
  error: string | null;
  macroMode: boolean;
  allowUnassign: boolean;
  selectController: (id: string | null) => void;
  applyPreset: (preset: string) => void;
  partnerPreset?: PartnerPresetSettings;
};

export function ControllerMappingDialog({
  controller,
  onEditPreset,
  usbAdapter,
  bluetoothOutput,
}: {
  controller?: MappingSettings;
  onEditPreset: (preset: PresetInfo) => void;
  usbAdapter?: { transport: string; address: string | null };
  bluetoothOutput?: {
    value: string;
    options: {
      value: string;
      label: string;
      variant: ControllerVariant;
      disabled?: boolean;
    }[];
    disabled: boolean;
    error: string | null;
    select: (value: string) => void;
  };
}) {
  const [open, setOpen] = useState(false);
  const selectedOutput = bluetoothOutput?.options.find(
    (option) => option.value === bluetoothOutput.value,
  );

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger
        render={
          <Button
            variant="ghost"
            size="icon-sm"
            className="action-hover rounded-lg"
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
        {usbAdapter && (
          <div className="grid grid-cols-[7.5rem_minmax(0,1fr)] gap-x-2 gap-y-1 text-sm">
            <p className="font-medium">USB adapter</p>
            <p className="font-mono break-all">{usbAdapter.transport}</p>
            {usbAdapter.address && (
              <p className="col-start-2 font-mono text-xs text-muted-foreground">
                {usbAdapter.address}
              </p>
            )}
          </div>
        )}
        {bluetoothOutput && (
          <div className="grid grid-cols-[7.5rem_minmax(0,1fr)] items-center gap-x-2 gap-y-1">
            <p className="text-sm font-medium">Controller type</p>
            <Select
              value={bluetoothOutput.value}
              disabled={bluetoothOutput.disabled}
              onValueChange={(value) => {
                if (value !== null) bluetoothOutput.select(value);
              }}
            >
              <SelectTrigger
                className="w-full min-w-0"
                aria-label="Bluetooth controller type"
              >
                <SelectValue>
                  {selectedOutput && (
                    <>
                      <ControllerVariantIcon variant={selectedOutput.variant} />
                      <span className="truncate">{selectedOutput.label}</span>
                    </>
                  )}
                </SelectValue>
              </SelectTrigger>
              <SelectContent align="start">
                <SelectGroup>
                  {bluetoothOutput.options.map(
                    ({ value, variant, label, disabled }) => (
                      <SelectItem key={value} value={value} disabled={disabled}>
                        <ControllerVariantIcon variant={variant} />
                        {label}
                      </SelectItem>
                    ),
                  )}
                </SelectGroup>
              </SelectContent>
            </Select>
            {bluetoothOutput.error && (
              <p role="alert" className="col-start-2 text-sm text-destructive">
                {bluetoothOutput.error}
              </p>
            )}
          </div>
        )}
        {open && controller && (
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
  controller: MappingSettings;
  onEditPreset: (preset: PresetInfo) => void;
}) {
  const {
    available,
    options,
    active,
    controllerGuid,
    hasGyro,
    preset,
    pending,
    error,
    macroMode,
    allowUnassign,
    selectController,
    applyPreset,
    partnerPreset,
  } = controller;
  const activeName = options.find((option) => option.id === active)?.name;
  const selection = active ?? (allowUnassign ? "unassigned" : null);
  const [presets, setPresets] = useState<Effect.Success<
    ReturnType<typeof listPresets>
  > | null>(null);
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
  const activePartnerPreset = partnerPreset
    ? presets?.presets.find(
        (entry) => entry.filename === (partnerPreset.preset ?? presets.active),
      )
    : undefined;

  return (
    <div className="space-y-4" aria-busy={changing}>
      <div className="space-y-3">
        <div className="grid grid-cols-[7.5rem_minmax(0,1fr)] items-center gap-x-2 gap-y-1">
          <p className="text-sm font-medium">Controller</p>
          <Select
            value={selection}
            disabled={
              !available || options.length === 0 || changing || macroMode
            }
            onValueChange={(value) => {
              if (value !== null && value !== selection)
                selectController(value === "unassigned" ? null : value);
            }}
          >
            <SelectTrigger
              className="w-full min-w-0"
              aria-label="Select controller"
            >
              <SelectValue placeholder="No controller selected">
                {activeName ?? (allowUnassign ? "No controller" : null)}
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              {allowUnassign && (
                <SelectItem value="unassigned">No controller</SelectItem>
              )}
              {options.map((entry) => (
                <SelectItem
                  key={entry.id}
                  value={entry.id}
                  disabled={entry.disabled}
                >
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
              disabled={
                changing || macroMode || !!loadError || !presets?.presets.length
              }
              onValueChange={(value) => {
                if (value !== null && value !== activePreset?.filename) {
                  applyPreset(value);
                }
              }}
            >
              <SelectTrigger
                className="w-full min-w-0"
                aria-label="Mapping preset"
              >
                <SelectValue
                  placeholder={
                    presets || loadError
                      ? "No preset selected"
                      : "Loading presets…"
                  }
                >
                  {activePreset ? (
                    <span className="truncate">{activePreset.name}</span>
                  ) : null}
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
              className="action-hover"
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
        {partnerPreset && (
          <div className="grid grid-cols-[7.5rem_minmax(0,1fr)] items-center gap-x-2 gap-y-1">
            <p className="text-sm font-medium">{partnerPreset.label}</p>
            <div className="flex min-w-0 items-center gap-1">
              <Select
                value={activePartnerPreset?.filename ?? null}
                disabled={
                  changing ||
                  partnerPreset.macroMode ||
                  !!loadError ||
                  !presets?.presets.length
                }
                onValueChange={(value) => {
                  if (value !== null && value !== activePartnerPreset?.filename) {
                    partnerPreset.applyPreset(value);
                  }
                }}
              >
                <SelectTrigger
                  className="w-full min-w-0"
                  aria-label={partnerPreset.label}
                >
                  <SelectValue
                    placeholder={
                      presets || loadError
                        ? "No preset selected"
                        : "Loading presets…"
                    }
                  >
                    {activePartnerPreset ? (
                      <span className="truncate">{activePartnerPreset.name}</span>
                    ) : null}
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
                className="action-hover"
                aria-label={`Edit ${partnerPreset.label.toLowerCase()}`}
                title={`Edit ${partnerPreset.label.toLowerCase()}`}
                disabled={!activePartnerPreset || changing}
                onClick={() => {
                  if (activePartnerPreset) onEditPreset(activePartnerPreset);
                }}
              >
                <PencilSimpleIcon />
              </Button>
            </div>
          </div>
        )}
      </div>
      <div className="space-y-3">
        <VibrationSetting controllerGuid={controllerGuid} />
        <MotionSetting
          controllerGuid={controllerGuid}
          supported={hasGyro ?? true}
        />
      </div>
      {pending && (
        <p role="status">
          {pending === "applying"
            ? "Applying preset…"
            : "Switching controller…"}
        </p>
      )}
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      {macroMode && (
        <p className="text-xs text-muted-foreground">
          Controller and preset changes are locked while a macro runs.
        </p>
      )}
    </div>
  );
}
