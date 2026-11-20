import { useEffect, useId, useState } from "react";
import { Effect } from "effect";
import { Checkbox } from "@/src/components/ui/checkbox";
import { Label } from "@/src/components/ui/label";
import { Button } from "@/src/components/ui/button";
import { getConfig, patchConfig } from "@/src/lib/api";
import { errorMessage } from "@/src/lib/errors";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/src/components/ui/tooltip";

function readVibration(config: Record<string, unknown>): boolean {
  if (typeof config.vibration_enabled !== "boolean") {
    throw new Error("Invalid vibration setting received from the server");
  }
  return config.vibration_enabled;
}

export function VibrationSetting({
  controllerGuid,
}: {
  controllerGuid?: string | null;
}) {
  const id = useId();
  const [config, setConfig] = useState<Record<string, unknown> | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let disposed = false;
    setError(null);
    void Effect.runPromise(getConfig())
      .then((config) => {
        readVibration(config);
        if (!disposed) {
          setConfig(config);
        }
      })
      .catch((cause: unknown) => {
        if (!disposed) setError(errorMessage(cause));
      });
    return () => {
      disposed = true;
    };
  }, [attempt]);

  async function save(value: boolean) {
    if (controllerGuid === null) return;
    setSaving(true);
    setError(null);
    try {
      const result = await Effect.runPromise(
        patchConfig(
          controllerGuid
            ? { controller_vibration: { [controllerGuid]: value } }
            : { vibration_enabled: value },
        ),
      );
      readVibration(result.config);
      setConfig(result.config);
    } catch (cause: unknown) {
      setError(errorMessage(cause));
    } finally {
      setSaving(false);
    }
  }

  const globalEnabled = config?.vibration_enabled === true;
  const individual = controllerGuid !== undefined;
  const globalDisabled = individual && config !== null && !globalEnabled;
  const disabledReason = globalDisabled
    ? "Enable Vibration (All Controllers) in Settings to change this controller’s vibration."
    : controllerGuid === null
      ? "Connect and select a controller to change its vibration."
      : null;
  const preferences = config?.controller_vibration;
  const preference =
    preferences && typeof preferences === "object"
      ? Object.entries(preferences).find(
          ([key]) => key === controllerGuid?.toLowerCase(),
        )?.[1]
      : undefined;
  const disabled =
    !config || saving || globalDisabled || controllerGuid === null;
  const checkbox = (
    <Checkbox
      id={id}
      checked={
        individual ? !!controllerGuid && preference !== false : globalEnabled
      }
      disabled={disabled}
      onCheckedChange={(value) => void save(value)}
    />
  );

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-4">
        <Label
          className={
            disabled ? "font-medium text-muted-foreground" : "font-medium"
          }
          htmlFor={id}
        >
          {individual ? "Controller vibration" : "Vibration (All Controllers)"}
        </Label>
        {disabled && disabledReason ? (
          <Tooltip>
            <TooltipTrigger
              render={
                <span
                  className="inline-flex *:pointer-events-none"
                  tabIndex={0}
                />
              }
              aria-label="Controller vibration unavailable"
            >
              {checkbox}
            </TooltipTrigger>
            <TooltipContent>{disabledReason}</TooltipContent>
          </Tooltip>
        ) : (
          checkbox
        )}
      </div>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      {!config && error && (
        <Button
          variant="outline"
          onClick={() => setAttempt((value) => value + 1)}
        >
          Retry
        </Button>
      )}
    </div>
  );
}
