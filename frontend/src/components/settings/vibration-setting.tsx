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

type FeatureSpec = {
  globalKey: "vibration_enabled" | "motion_enabled";
  perControllerKey: "controller_vibration" | "controller_motion";
  globalLabel: string;
  individualLabel: string;
  noun: string;
};

const VIBRATION_FEATURE: FeatureSpec = {
  globalKey: "vibration_enabled",
  perControllerKey: "controller_vibration",
  globalLabel: "Vibration (All Controllers)",
  individualLabel: "Controller vibration",
  noun: "vibration",
};

const MOTION_FEATURE: FeatureSpec = {
  globalKey: "motion_enabled",
  perControllerKey: "controller_motion",
  globalLabel: "Motion / Gyro (All Controllers)",
  individualLabel: "Controller motion (gyro)",
  noun: "motion",
};

function readFlag(config: Record<string, unknown>, spec: FeatureSpec): boolean {
  const value = config[spec.globalKey];
  if (typeof value !== "boolean") {
    throw new Error(`Invalid ${spec.noun} setting received from the server`);
  }
  return value;
}

function ControllerFeatureSetting({
  spec,
  controllerGuid,
  supported = true,
}: {
  spec: FeatureSpec;
  controllerGuid?: string | null;
  supported?: boolean;
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
      .then((loaded) => {
        readFlag(loaded, spec);
        if (!disposed) {
          setConfig(loaded);
        }
      })
      .catch((cause: unknown) => {
        if (!disposed) setError(errorMessage(cause));
      });
    return () => {
      disposed = true;
    };
  }, [attempt, spec]);

  async function save(value: boolean) {
    if (controllerGuid === null) return;
    setSaving(true);
    setError(null);
    try {
      const result = await Effect.runPromise(
        patchConfig(
          controllerGuid
            ? { [spec.perControllerKey]: { [controllerGuid]: value } }
            : { [spec.globalKey]: value },
        ),
      );
      readFlag(result.config, spec);
      setConfig(result.config);
    } catch (cause: unknown) {
      setError(errorMessage(cause));
    } finally {
      setSaving(false);
    }
  }

  const globalEnabled = config?.[spec.globalKey] === true;
  const individual = controllerGuid !== undefined;
  const unsupported = individual && !!controllerGuid && !supported;
  const globalDisabled = individual && config !== null && !globalEnabled;
  const disabledReason = unsupported
    ? `This controller does not report ${spec.noun} sensors.`
    : globalDisabled
      ? `Enable ${spec.globalLabel} in Settings to change this controller’s ${spec.noun}.`
      : controllerGuid === null
        ? `Connect and select a controller to change its ${spec.noun}.`
        : null;
  const preferences = config?.[spec.perControllerKey];
  const preference =
    preferences && typeof preferences === "object"
      ? Object.entries(preferences).find(
          ([key]) => key === controllerGuid?.toLowerCase(),
        )?.[1]
      : undefined;
  const disabled =
    !config || saving || globalDisabled || unsupported || controllerGuid === null;
  const checkbox = (
    <Checkbox
      id={id}
      checked={
        individual
          ? !!controllerGuid && supported && preference !== false
          : globalEnabled
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
          {individual ? spec.individualLabel : spec.globalLabel}
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
              aria-label={`${spec.individualLabel} unavailable`}
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

export function VibrationSetting({
  controllerGuid,
}: {
  controllerGuid?: string | null;
}) {
  return (
    <ControllerFeatureSetting
      spec={VIBRATION_FEATURE}
      controllerGuid={controllerGuid}
    />
  );
}

export function MotionSetting({
  controllerGuid,
  supported = true,
}: {
  controllerGuid?: string | null;
  supported?: boolean;
}) {
  return (
    <ControllerFeatureSetting
      spec={MOTION_FEATURE}
      controllerGuid={controllerGuid}
      supported={supported}
    />
  );
}
