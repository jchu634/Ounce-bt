import {
  PencilSimpleIcon,
  PlugsConnectedIcon,
  PlugsIcon,
  SpinnerGapIcon,
  TrashIcon,
} from "@phosphor-icons/react";
import { useState } from "react";
import { Button } from "@/src/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
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
import { Tooltip, TooltipContent, TooltipTrigger } from "@/src/components/ui/tooltip";
import { Input } from "@/src/components/ui/input";
import { Label } from "@/src/components/ui/label";
import { connectionDetail, deviceName, type BluetoothStatus } from "@/src/lib/bluetooth";
import { errorMessage } from "@/src/lib/errors";
import { useSwitchConnection } from "@/src/lib/switch-connection";
import { cn } from "cn";

type ConnectionToggleButtonProps = {
  status: BluetoothStatus | null;
  address: string;
  disabled: boolean;
  busy: boolean;
  onReconnect: () => void;
  onDisconnect: () => void;
  className?: string;
};

export function ConnectionToggleButton({
  status,
  address,
  disabled,
  busy,
  onReconnect,
  onDisconnect,
  className,
}: ConnectionToggleButtonProps) {
  const active = status?.state !== "disconnected";
  const reconnecting = status?.state === "reconnecting";
  const buttonDisabled = active
    ? disabled || !status?.address || reconnecting
    : disabled || !address;

  return (
    <Button
      variant={active ? "destructive" : "tertiary"}
      disabled={buttonDisabled}
      onClick={active ? onDisconnect : onReconnect}
      className={className}
    >
      {busy ? (
        <SpinnerGapIcon className="hidden animate-spin 2xl:block" />
      ) : active ? (
        <PlugsIcon weight="fill" className="hidden 2xl:block" />
      ) : (
        <PlugsConnectedIcon weight="fill" className="hidden 2xl:block" />
      )}
      {busy ? "Connecting…" : active ? "Disconnect Controller" : "Reconnect Controller"}
    </Button>
  );
}

type SwitchConnectionState = ReturnType<typeof useSwitchConnection>;

type SwitchConnectionProps = {
  connection: SwitchConnectionState;
};

export function ConnectionStatus({
  status,
  statusError,
}: Pick<SwitchConnectionState, "status" | "statusError">) {
  const statusLabel = statusError
    ? "Unavailable"
    : !status
      ? "Loading"
      : !status.available
        ? "Unavailable"
        : status.pairing
          ? "Pairing"
          : status.state === "connected"
            ? "Connected"
            : status.state === "connecting"
              ? "Connecting"
              : status.state === "reconnecting"
                ? "Reconnecting"
                : "Disconnected";
  const statusDetail = statusError
    ? statusError
    : !status
      ? "Loading Bluetooth status"
      : !status.available
        ? "Bluetooth is not ready"
        : connectionDetail(status);
  const statusTone =
    statusError || (status && !status.available)
      ? "error"
      : !status
        ? "loading"
        : status.pairing || status.state === "connecting" || status.state === "reconnecting"
          ? "pending"
          : status.state === "connected"
            ? "connected"
            : "disconnected";

  return (
    <Tooltip>
      <TooltipTrigger
        aria-label={`Switch connection: ${statusLabel}`}
        className={cn(
          "inline-flex items-center rounded-full border font-medium",
          statusTone === "connected" &&
            "border-emerald-500/40 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
          statusTone === "pending" &&
            "border-amber-500/40 bg-amber-500/10 text-amber-600 dark:text-amber-400",
          statusTone === "error" && "border-destructive/40 bg-destructive/10 text-destructive",
          statusTone === "disconnected" && "border-border bg-muted text-muted-foreground",
          statusTone === "loading" && "border-border bg-muted text-muted-foreground",
        )}
      >
        <div className="size-1.5 rounded-full bg-current" />
      </TooltipTrigger>
      <TooltipContent>{statusDetail}</TooltipContent>
    </Tooltip>
  );
}

export function SwitchConnection({ connection }: SwitchConnectionProps) {
  const { status, selected: address, setSelected, disabled, active, update, rename } = connection;
  const [renaming, setRenaming] = useState<{ address: string; name: string } | null>(null);
  const [savingName, setSavingName] = useState(false);
  const [renameError, setRenameError] = useState<string | null>(null);

  async function saveName() {
    if (!renaming || savingName || !renaming.name.trim()) return;
    setSavingName(true);
    setRenameError(null);
    try {
      await rename(renaming.address, renaming.name.trim());
      setRenaming(null);
    } catch (cause) {
      setRenameError(errorMessage(cause));
    } finally {
      setSavingName(false);
    }
  }

  return (
    <section aria-label="Connection">
      <div className="flex items-end gap-2">
        <div className="flex min-w-0 flex-1 items-center gap-1">
          <Tooltip>
            <TooltipTrigger
              render={<div className="min-w-0 flex-1" tabIndex={address ? 0 : undefined} />}
            >
              <Select
                value={address}
                disabled={disabled || active || !address}
                onValueChange={(value) => setSelected(value ?? "")}
              >
                <SelectTrigger className="w-full min-w-0" aria-label="Switch device">
                  <SelectValue placeholder="No saved devices">
                    {deviceName(status, address)}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent align="start">
                  {status?.peers.map((peer) => (
                    <SelectItem key={peer} value={peer} title={peer}>
                      {deviceName(status, peer)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </TooltipTrigger>
            <TooltipContent>{address || "No saved devices"}</TooltipContent>
          </Tooltip>
          <Button
            variant="ghost"
            size="icon"
            aria-label="Rename Switch device"
            title="Rename Switch device"
            disabled={disabled || !address}
            onClick={() => {
              setRenaming({ address, name: deviceName(status, address) });
              setRenameError(null);
            }}
          >
            <PencilSimpleIcon />
          </Button>
        </div>
        <Button
          variant="default"
          disabled={disabled || (!status?.pairing && active)}
          onClick={() => void update("PUT", { pairing: !status?.pairing })}
        >
          {status?.pairing ? "Stop pairing" : "Start pairing"}
        </Button>
        <Dialog>
          <DialogTrigger
            render={
              <Button
                variant="destructive"
                size="icon"
                aria-label="Delete controller config"
                disabled={disabled || !address || status?.state === "reconnecting"}
              />
            }
          >
            <TrashIcon weight="fill" />
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Delete controller config?</DialogTitle>
              <DialogDescription>
                This disconnects the {address} config and removes it. You will need to pair again to
                reconnect.
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <DialogClose render={<Button variant="outline" />}>Cancel</DialogClose>
              <DialogClose
                render={<Button variant="destructive" />}
                onClick={() => void update("DELETE", { address })}
              >
                Delete config
              </DialogClose>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      <Dialog
        open={renaming !== null}
        onOpenChange={(open) => {
          if (!open && !savingName) setRenaming(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Rename Switch device</DialogTitle>
            <DialogDescription>{renaming?.address}</DialogDescription>
          </DialogHeader>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void saveName();
            }}
            className="space-y-4"
          >
            <div className="space-y-2">
              <Label htmlFor="switch-device-name">Device name</Label>
              <Input
                id="switch-device-name"
                value={renaming?.name ?? ""}
                autoFocus
                required
                maxLength={64}
                disabled={savingName}
                aria-describedby={renameError ? "rename-device-error" : undefined}
                onChange={(event) => {
                  const name = event.target.value;
                  setRenaming((current) => current && { ...current, name });
                }}
              />
              {renameError && (
                <p id="rename-device-error" role="alert" className="text-sm text-destructive">
                  {renameError}
                </p>
              )}
            </div>
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                disabled={savingName}
                onClick={() => setRenaming(null)}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={savingName || !renaming?.name.trim()}>
                {savingName ? "Saving…" : "Save name"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {status?.pairing && (
        <p className="mt-2 text-sm text-muted-foreground">
          On the Switch, open Controllers → Change Grip/Order.
        </p>
      )}
    </section>
  );
}
