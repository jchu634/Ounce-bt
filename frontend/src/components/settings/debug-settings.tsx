import { useEffect, useState } from "react";
import { Effect } from "effect";
import {
  getConfig,
  getDebugStatus,
  saveDebugAndRestart,
  type DebugChanges,
} from "@/src/lib/api";
import { errorMessage } from "@/src/lib/errors";
import { Button } from "@/src/components/ui/button";
import { Checkbox } from "@/src/components/ui/checkbox";
import { NumberField } from "@base-ui/react/number-field";
import { MinusIcon, PlusIcon } from "@phosphor-icons/react";
import { Separator } from "@/src/components/ui/separator";
import { Label } from "@/src/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/src/components/ui/dialog";

const loadDebugStatus = () => Effect.runPromise(getDebugStatus());
type DebugStatus = Awaited<ReturnType<typeof loadDebugStatus>>;

function RateSetting({
  id,
  label,
  description,
  value,
  disabled,
  onValueChange,
}: {
  id: string;
  label: string;
  description: string;
  value: number;
  disabled: boolean;
  onValueChange: (value: number) => void;
}) {
  return (
    <NumberField.Root
      id={id}
      value={Number.isNaN(value) ? null : value}
      min={1}
      max={1000}
      step={1}
      smallStep={1}
      allowWheelScrub
      disabled={disabled}
      onValueChange={(next) => onValueChange(next ?? Number.NaN)}
      className="flex flex-wrap items-center justify-between gap-3"
    >
      <div className="min-w-0 flex-1 basis-64">
        <Label htmlFor={id} className="inline leading-normal">
          {label}
        </Label>
        <span
          id={`${id}-description`}
          className="text-sm text-muted-foreground"
        >
          <br />
          {description}
        </span>
      </div>
      <NumberField.Group className="flex shrink-0 items-center">
        <NumberField.Input
          aria-describedby={`${id}-description`}
          className="mr-2 h-9 w-28 rounded-lg border border-input bg-input/50 px-3 text-sm tabular-nums outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/30 disabled:opacity-50"
        />
        <NumberField.Decrement
          render={
            <Button
              size="icon"
              className="rounded-l-lg rounded-r-none border-primary-foreground/30"
            />
          }
          aria-label={`Decrease ${label.toLowerCase()}`}
        >
          <MinusIcon />
        </NumberField.Decrement>
        <NumberField.Increment
          render={
            <Button
              size="icon"
              className="rounded-l-none rounded-r-lg border-l-0"
            />
          }
          aria-label={`Increase ${label.toLowerCase()}`}
        >
          <PlusIcon />
        </NumberField.Increment>
      </NumberField.Group>
    </NumberField.Root>
  );
}

export function DebugSettings({
  active,
  onStateChange,
  onHideDebug,
}: {
  active: boolean;
  onHideDebug: () => void;
  onStateChange: (state: { dirty: boolean; saving: boolean }) => void;
}) {
  const [saved, setSaved] = useState<DebugChanges | null>(null);
  const [draft, setDraft] = useState<DebugChanges | null>(null);
  const [status, setStatus] = useState<DebugStatus | null>(null);
  const [regenerate, setRegenerate] = useState(false);
  const [prompt, setPrompt] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dirty = regenerate || JSON.stringify(saved) !== JSON.stringify(draft);

  useEffect(() => {
    onStateChange({ dirty, saving });
  }, [dirty, saving, onStateChange]);

  useEffect(() => {
    let cancelled = false;
    void Effect.runPromise(getConfig())
      .then((config) => {
        if (cancelled) return;
        if (
          typeof config.nolog !== "boolean" ||
          typeof config.bumble_logging !== "boolean" ||
          typeof config.ws_auth_required !== "boolean" ||
          typeof config.macro_rate_hz !== "number" ||
          typeof config.tick_rate_hz !== "number"
        )
          throw new Error("Invalid debug configuration");
        const settings = {
          nolog: config.nolog,
          bumble_logging: config.bumble_logging,
          ws_auth_required: config.ws_auth_required,
          macro_rate_hz: config.macro_rate_hz,
          tick_rate_hz: config.tick_rate_hz,
        };
        setSaved(settings);
        setDraft(settings);
      })
      .catch((cause: unknown) => {
        if (!cancelled) setError(errorMessage(cause));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    async function refresh() {
      try {
        const next = await Effect.runPromise(getDebugStatus());
        if (!cancelled) setStatus(next);
      } catch (cause) {
        if (!cancelled) setError(errorMessage(cause));
      }
    }
    void refresh();
    const timer = setInterval(() => void refresh(), 1000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [active]);

  const validRates =
    draft &&
    [draft.macro_rate_hz, draft.tick_rate_hz].every(
      (rate) => Number.isInteger(rate) && rate >= 1 && rate <= 1000,
    );

  async function restart() {
    if (!draft) return;
    setSaving(true);
    setError(null);
    try {
      await Effect.runPromise(saveDebugAndRestart(draft, regenerate));
    } catch (cause) {
      setError(errorMessage(cause));
      setSaving(false);
      setPrompt(false);
    }
  }
  return (
    <div className="space-y-4">
      <section className="space-y-2 rounded-lg border p-4">
        <h2 className="font-semibold">Current info</h2>
        <p>
          Current BD address:{" "}
          <code>{status?.bd_address ?? "Bluetooth is not ready"}</code>
        </p>
        {status && (
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
            <dt>Bluetooth</dt>
            <dd className="text-muted-foreground">
              {status.bluetooth.state}
              {status.bluetooth.pairing ? ", pairing enabled" : ""}
            </dd>
            <dt>ACL connection</dt>
            <dd className="text-muted-foreground">
              {status.acl_connected ? "Connected" : "Disconnected"}
            </dd>
            <dt>HID control</dt>
            <dd className="text-muted-foreground">
              {status.hid_control_ready ? "Ready" : "Not ready"}
            </dd>
            <dt>HID interrupt</dt>
            <dd className="text-muted-foreground">
              {status.hid_interrupt_ready ? "Ready" : "Not ready"}
            </dd>
          </dl>
        )}
        <div className="space-y-1">
          <h3 className="text-sm font-medium">Saved Switch devices</h3>
          {status ? (
            status.switch_devices.length > 0 ? (
              <dl className="space-y-1 text-sm">
                {status.switch_devices.map((device) => (
                  <div
                    key={device.address}
                    className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1"
                  >
                    <dt>{device.name}</dt>
                    <dd className="font-mono text-muted-foreground">
                      {device.address}
                    </dd>
                  </div>
                ))}
              </dl>
            ) : (
              <p className="text-sm text-muted-foreground">
                No saved Switch devices.
              </p>
            )
          ) : (
            <p className="text-sm text-muted-foreground">
              Loading saved devices...
            </p>
          )}
        </div>
        <details className="rounded-md border p-3">
          <summary className="cursor-pointer text-sm font-medium">
            Connection details, JSON
          </summary>
          <pre className="mt-3 overflow-auto text-xs whitespace-pre-wrap">
            {status
              ? JSON.stringify(status, null, 2)
              : "Loading connection states..."}
          </pre>
        </details>
      </section>
      {error && (
        <p role="alert" className="text-destructive">
          {error}
        </p>
      )}
      {draft && (
        <fieldset disabled={saving} className="space-y-4">
          <section className="space-y-4">
            <div className="flex items-start justify-between gap-4">
              <div className="space-y-1">
                <Label htmlFor="debug-visible">Show debug tab</Label>
                <p
                  id="debug-visible-description"
                  className="text-sm text-muted-foreground"
                >
                  Hide this tab when you have finished debugging.
                </p>
              </div>
              <Checkbox
                id="debug-visible"
                aria-describedby="debug-visible-description"
                checked
                onCheckedChange={(checked) => {
                  if (!checked) onHideDebug();
                }}
              />
            </div>
          </section>
          <Separator />
          <h2 className="font-semibold">Requires a restart</h2>
          <div className="flex items-start justify-between gap-4">
            <div className="space-y-1">
              <Label htmlFor="debug-logging">Enable logging</Label>
              <p
                id="debug-logging-description"
                className="text-sm text-muted-foreground"
              >
                Write application diagnostics to the console and log file.
              </p>
            </div>
            <Checkbox
              id="debug-logging"
              aria-describedby="debug-logging-description"
              checked={!draft.nolog}
              onCheckedChange={(checked) =>
                setDraft({ ...draft, nolog: !checked })
              }
            />
          </div>
          <div
            className={`flex items-start justify-between gap-4 ${draft.nolog ? "opacity-50" : ""}`}
          >
            <div className="space-y-1">
              <Label htmlFor="debug-bumble">Bumble logging</Label>
              <p
                id="debug-bumble-description"
                className="text-sm text-muted-foreground"
              >
                Include Bluetooth stack diagnostics. Requires logging to be
                enabled.
              </p>
            </div>
            <Checkbox
              id="debug-bumble"
              aria-describedby="debug-bumble-description"
              checked={draft.bumble_logging}
              disabled={draft.nolog}
              onCheckedChange={(checked) =>
                setDraft({ ...draft, bumble_logging: checked })
              }
            />
          </div>
          <div className="flex items-start justify-between gap-4">
            <div className="space-y-1">
              <Label htmlFor="debug-auth">
                Require WebSocket authentication
              </Label>
              <p
                id="debug-auth-description"
                className="text-sm text-muted-foreground"
              >
                Require the desktop session token before accepting WebSocket
                control connections.
              </p>
            </div>
            <Checkbox
              id="debug-auth"
              aria-describedby="debug-auth-description"
              checked={draft.ws_auth_required}
              onCheckedChange={(checked) =>
                setDraft({ ...draft, ws_auth_required: checked })
              }
            />
          </div>
          <RateSetting
            id="debug-macro-rate"
            label="Macro rate, Hz"
            description="Set how often macro playback updates controller input."
            value={draft.macro_rate_hz}
            disabled={saving}
            onValueChange={(value) =>
              setDraft({ ...draft, macro_rate_hz: value })
            }
          />
          <RateSetting
            id="debug-tick-rate"
            label="Tick rate, Hz"
            description="Set how often the controller loop processes input and sends reports to the Switch."
            value={draft.tick_rate_hz}
            disabled={saving}
            onValueChange={(value) =>
              setDraft({ ...draft, tick_rate_hz: value })
            }
          />
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="min-w-0 flex-1 basis-64">
              <Label id="debug-address-label" className="inline leading-normal">
                BD address
              </Label>
              <span
                id="debug-address-description"
                className="text-sm text-muted-foreground"
              >
                <br />
                Generate a new Bluetooth identity on save and delete all saved
                Switch devices and pairing keys. You will need to pair any
                connections again.
              </span>
            </div>
            <Button
              variant="outline"
              disabled={!status?.address_regeneration_available}
              aria-describedby="debug-address-description"
              onClick={() => setRegenerate(!regenerate)}
            >
              {regenerate
                ? "Cancel BD address regeneration"
                : "Regenerate BD address"}
            </Button>
          </div>
          {status && !status.address_regeneration_available && (
            <p className="text-sm text-muted-foreground">
              BD address regeneration requires a ready Bluetooth adapter on
              Windows.
            </p>
          )}
          {regenerate && (
            <p className="text-sm text-muted-foreground">
              Saving will delete all saved Switch devices and pairing keys. You
              may need to unplug and reconnect the adapter after restarting.
            </p>
          )}
          <div>
            <Button
              disabled={!dirty || !validRates || !status?.restart_available}
              onClick={() => setPrompt(true)}
            >
              Save debug settings
            </Button>
          </div>
          {status && !status.restart_available && (
            <p>Restart is unavailable in this session.</p>
          )}
        </fieldset>
      )}
      <Dialog
        open={prompt}
        onOpenChange={(next) => {
          if (!saving) setPrompt(next);
        }}
      >
        <DialogContent showCloseButton={false}>
          <DialogHeader>
            <DialogTitle>Restart Ounce-bt?</DialogTitle>
            <DialogDescription>
              Saving these settings will restart the application and disconnect
              active controllers. Running macros will stop.
              {regenerate &&
                " All saved Switch devices and pairing keys will be deleted. Pair with your Switch again after restarting."}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              disabled={saving}
              onClick={() => setPrompt(false)}
            >
              Back
            </Button>
            <Button disabled={saving} onClick={() => void restart()}>
              {saving ? "Restarting…" : "Save and restart"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
