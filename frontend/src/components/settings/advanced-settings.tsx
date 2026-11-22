import { useEffect, useId, useState } from "react";
import { Effect } from "effect";
import { WarningIcon } from "@phosphor-icons/react";
import { Button } from "@/src/components/ui/button";
import { Checkbox } from "@/src/components/ui/checkbox";
import { Label } from "@/src/components/ui/label";
import { getConfig, patchConfig } from "@/src/lib/api";
import { errorMessage } from "@/src/lib/errors";

export const CONFIG_CHANGED_EVENT = "ounce-bt:config-changed";

export function AdvancedSettings() {
  const pairingId = useId();
  const [joyconPairingEnabled, setJoyconPairingEnabled] = useState<boolean | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let disposed = false;
    setError(null);
    void Effect.runPromise(getConfig())
      .then((loaded) => {
        if (!disposed) {
          setJoyconPairingEnabled(loaded.joycon_pairing_enabled === true);
        }
      })
      .catch((cause: unknown) => {
        if (!disposed) setError(errorMessage(cause));
      });
    return () => {
      disposed = true;
    };
  }, [attempt]);

  async function saveJoyconPairing(enabled: boolean) {
    setSaving(true);
    setError(null);
    try {
      const result = await Effect.runPromise(
        patchConfig({ joycon_pairing_enabled: enabled }),
      );
      setJoyconPairingEnabled(result.config.joycon_pairing_enabled === true);
      window.dispatchEvent(new Event(CONFIG_CHANGED_EVENT));
    } catch (cause: unknown) {
      setError(errorMessage(cause));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div
        role="note"
        className="flex max-w-180 items-start gap-2.5 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3.5 py-2.5 text-sm text-foreground"
      >
        <WarningIcon
          size={18}
          weight="fill"
          className="mt-0.5 shrink-0 text-amber-500"
          aria-hidden="true"
        />
        <div className="space-y-0.5">
          <p className="font-medium">Experimental features</p>
          <p className="text-muted-foreground">
            Features in this settings tab are not quite stable yet and may behave
            unexpectedly.
          </p>
        </div>
      </div>

      <div className="flex w-full max-w-180 items-center justify-between gap-4">
        <div className="flex flex-col gap-1">
          <Label htmlFor={pairingId}>Joy-Con pairing</Label>
          <p
            id={`${pairingId}-description`}
            className="text-sm text-muted-foreground"
          >
            Pair a Joy-Con L and Joy-Con R adapter together so they act as a single
            combined Joy-Con.
          </p>
        </div>
        <Checkbox
          id={pairingId}
          aria-describedby={`${pairingId}-description`}
          checked={joyconPairingEnabled === true}
          disabled={joyconPairingEnabled === null || saving}
          onCheckedChange={(checked) => void saveJoyconPairing(checked)}
        />
      </div>

      {error && (
        <div className="flex max-w-180 items-center justify-between gap-2">
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
          {joyconPairingEnabled === null && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => setAttempt((value) => value + 1)}
            >
              Retry
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
