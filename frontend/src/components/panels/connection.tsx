import { PlugsConnectedIcon, PlugsIcon, SpinnerGapIcon, TrashIcon } from "@phosphor-icons/react";
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
import { type BluetoothStatus } from "@/src/lib/bluetooth";
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
        : `${status.pairing ? "Pairing, " : ""}${status.state}${status.address ? `: ${status.address}` : ""}`;
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
  const { status, selected: address, setSelected, disabled, active, update } = connection;

  return (
    <section aria-label="Connection">
      <div className="flex items-end gap-2">
        <Select
          value={address}
          disabled={disabled || active || !address}
          onValueChange={(value) => setSelected(value ?? "")}
        >
          <SelectTrigger className="w-full min-w-0" aria-label="Controller config">
            <SelectValue placeholder="No saved devices" />
          </SelectTrigger>
          <SelectContent align="start">
            {status?.peers.map((peer) => (
              <SelectItem key={peer} value={peer}>
                {peer}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
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

      {status?.pairing && (
        <p className="mt-2 text-sm text-muted-foreground">
          On the Switch, open Controllers → Change Grip/Order.
        </p>
      )}
    </section>
  );
}
