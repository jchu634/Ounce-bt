import { useEffect, useState } from "react";
import { Effect } from "effect";
import { Checkbox } from "@/src/components/ui/checkbox";
import { Label } from "@/src/components/ui/label";
import { Button } from "@/src/components/ui/button";
import { getConfig, patchConfig } from "@/src/lib/api";
import { errorMessage } from "@/src/lib/errors";

function readVibration(config: Record<string, unknown>): boolean {
  if (typeof config.vibration_enabled !== "boolean") {
    throw new Error("Invalid vibration setting received from the server");
  }
  return config.vibration_enabled;
}

export function VibrationSetting() {
  const [enabled, setEnabled] = useState(true);
  const [ready, setReady] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let disposed = false;
    setError(null);
    void Effect.runPromise(getConfig())
      .then((config) => {
        const value = readVibration(config);
        if (!disposed) {
          setEnabled(value);
          setReady(true);
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
    setSaving(true);
    setError(null);
    try {
      const result = await Effect.runPromise(
        patchConfig({ vibration_enabled: value }),
      );
      setEnabled(readVibration(result.config));
    } catch (cause: unknown) {
      setError(errorMessage(cause));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex w-full max-w-180 items-center justify-between gap-4">
        <div className="flex flex-col gap-1">
          <Label htmlFor="controller-vibration">Vibration</Label>
        </div>
        <Checkbox
          id="controller-vibration"
          aria-describedby="controller-vibration-description"
          checked={enabled}
          disabled={!ready || saving}
          onCheckedChange={(value) => {
            void save(value);
          }}
        />
      </div>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      {!ready && error && (
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
