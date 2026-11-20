import {
  BluetoothIcon,
  PencilSimpleIcon,
  PlugsConnectedIcon,
  PlugsIcon,
  SpinnerGapIcon,
  TrashIcon,
} from "@phosphor-icons/react";
import { useId, useState } from "react";
import type { PresetInfo } from "@/src/lib/types";
import { ControllerColoursDialog } from "@/src/components/settings/controller-colours-dialog";
import { ControllerMappingDialog } from "@/src/components/settings/controller-mapping-dialog";
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
import { Input } from "@/src/components/ui/input";
import { Label } from "@/src/components/ui/label";
import { useControllers } from "@/src/hooks/use-controllers";
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
};

export function ConnectionToggleButton({
  status,
  address,
  disabled,
  busy,
  onReconnect,
  onDisconnect,
}: ConnectionToggleButtonProps) {
  const active = status?.state !== "disconnected";
  const reconnecting = status?.state === "reconnecting";
  const disconnecting = status?.state === "disconnecting";
  const action = disconnecting
    ? "Disconnecting…"
    : active
      ? "Disconnect controller"
      : "Reconnect controller";

  return (
    <Button
      variant={active && status?.address ? "destructive" : "outline"}
      size="icon-sm"
      className="rounded-lg"
      aria-label={action}
      title={action}
      disabled={disabled || (active ? !status?.address || reconnecting || disconnecting : !address)}
      onClick={active ? onDisconnect : onReconnect}
    >
      {busy || reconnecting || disconnecting ? (
        <SpinnerGapIcon className="animate-spin" />
      ) : active && status?.address ? (
        <PlugsIcon weight="fill" />
      ) : (
        <PlugsConnectedIcon weight="fill" />
      )}
    </Button>
  );
}

type SwitchConnectionState = ReturnType<typeof useSwitchConnection>;

function ConnectionStatus({
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
                : status.state === "disconnecting"
                  ? "Disconnecting"
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
        : status.pairing ||
            status.state === "connecting" ||
            status.state === "reconnecting" ||
            status.state === "disconnecting"
          ? "pending"
          : status.state === "connected"
            ? "connected"
            : "disconnected";

  return (
    <p
      className="flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground"
      title={statusDetail}
    >
      <span className="shrink-0">{statusLabel}</span>
      <span
        aria-hidden
        className={cn(
          "size-1.5 shrink-0 rounded-full bg-current",
          statusTone === "connected" && "bg-emerald-500",
          statusTone === "pending" && "bg-amber-500",
          statusTone === "error" && "bg-destructive",
        )}
      />
      {status?.address && !statusError && (
        <span className="min-w-0 truncate font-mono">{status.address}</span>
      )}
    </p>
  );
}

export function ConnectionPanel({ onEditPreset }: { onEditPreset: (preset: PresetInfo) => void }) {
  const connection = useSwitchConnection();
  const controller = useControllers();

  return (
    <section aria-label="Connection" className="min-w-0 space-y-2">
      <h2 className="text-lg font-semibold">Connection</h2>
      <ConnectionCard connection={connection} controller={controller} onEditPreset={onEditPreset} />
    </section>
  );
}

function ConnectionCard({
  connection,
  controller,
  onEditPreset,
}: {
  connection: SwitchConnectionState;
  controller: ReturnType<typeof useControllers>;
  onEditPreset: (preset: PresetInfo) => void;
}) {
  const {
    status,
    statusError,
    selected: address,
    setSelected,
    disabled,
    busy,
    active,
    update,
    rename,
  } = connection;
  const id = useId();
  const controllerName = controller.activeInfo?.name ?? "No controller selected";
  const [deleting, setDeleting] = useState<{ address: string; name: string } | null>(null);
  const [renaming, setRenaming] = useState<{ address: string; name: string } | null>(null);
  const [savingName, setSavingName] = useState(false);
  const [renameError, setRenameError] = useState<string | null>(null);
  const pairing = status?.pairing ?? false;
  const pairingAction = pairing ? "Stop pairing" : "Start pairing";

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
    <article
      aria-labelledby={`${id}-controller`}
      className="grid min-w-0 grid-cols-[auto_minmax(0,1fr)] items-start gap-2 rounded-xl border border-border bg-card p-2.5 text-card-foreground"
    >
      <ControllerColoursDialog />

      <div className="min-w-0 space-y-1.5">
        <div className="flex min-w-0 items-center gap-2">
          <h3
            id={`${id}-controller`}
            className="max-w-3/5 min-w-0 truncate text-sm font-medium"
            title={controllerName}
          >
            {controllerName}
          </h3>
          <ConnectionStatus status={status} statusError={statusError} />
          <div className="ms-auto shrink-0">
            <ControllerMappingDialog controller={controller} onEditPreset={onEditPreset} />
          </div>
        </div>
        <div className="flex min-w-0 flex-wrap items-center gap-1.5">
          <ConnectionToggleButton
            status={status}
            address={address}
            disabled={disabled}
            busy={busy}
            onReconnect={() => void update("POST", { address })}
            onDisconnect={() => void update("POST", { action: "disconnect" })}
          />
          <div className="min-w-24 flex-1">
            <Select
              value={address || null}
              disabled={disabled || active || !address}
              onValueChange={(value) => setSelected(value ?? "")}
            >
              <SelectTrigger
                size="sm"
                className="w-full min-w-0"
                aria-label="Saved Switch profile"
                title={address ? `${deviceName(status, address)} (${address})` : undefined}
              >
                <SelectValue placeholder="No saved profiles" className="min-w-0">
                  {address ? <span className="truncate">{deviceName(status, address)}</span> : null}
                </SelectValue>
              </SelectTrigger>
              <SelectContent align="start">
                {status?.peers.map((peer) => (
                  <SelectItem key={peer} value={peer} title={peer}>
                    <span className="truncate">{deviceName(status, peer)}</span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="Rename Switch profile"
            title="Rename Switch profile"
            disabled={disabled || !address}
            onClick={() => {
              setRenaming({ address, name: deviceName(status, address) });
              setRenameError(null);
            }}
          >
            <PencilSimpleIcon />
          </Button>
          <Button
            variant={pairing ? "secondary" : "default"}
            size="icon-sm"
            className="rounded-lg"
            aria-label={pairingAction}
            title={pairingAction}
            disabled={disabled || (!pairing && active)}
            onClick={() => void update("PUT", { pairing: !pairing })}
          >
            <BluetoothIcon weight={pairing ? "bold" : "regular"} />
          </Button>
          <div className="flex shrink-0 items-center gap-1.5">
            <Dialog
              onOpenChange={(open) => {
                if (open) setDeleting({ address, name: deviceName(status, address) });
              }}
            >
              <DialogTrigger
                render={
                  <Button
                    variant="outline"
                    size="icon-sm"
                    className="rounded-lg text-destructive hover:text-destructive"
                    aria-label="Delete Switch profile"
                    title="Delete Switch profile"
                    disabled={disabled || !address || status?.state === "reconnecting"}
                  />
                }
              >
                <TrashIcon weight="fill" />
              </DialogTrigger>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>Delete Switch profile?</DialogTitle>
                  <DialogDescription>
                    Removing {deleting?.name} forgets its Bluetooth pairing. You will need to pair
                    again to reconnect.
                  </DialogDescription>
                </DialogHeader>
                <DialogFooter>
                  <DialogClose render={<Button variant="outline" />}>Cancel</DialogClose>
                  <DialogClose
                    render={
                      <Button
                        variant="destructive"
                        disabled={
                          disabled || !deleting || !status?.peers.includes(deleting.address)
                        }
                      />
                    }
                    onClick={() => {
                      if (deleting) void update("DELETE", { address: deleting.address });
                    }}
                  >
                    Delete profile
                  </DialogClose>
                </DialogFooter>
              </DialogContent>
            </Dialog>
          </div>
        </div>
        {pairing && (
          <p className="text-xs text-muted-foreground">
            On the Switch, open Controllers → Change Grip/Order.
          </p>
        )}
        {statusError && <p className="text-xs text-destructive">{statusError}</p>}
      </div>

      <Dialog
        open={renaming !== null}
        onOpenChange={(open) => {
          if (!open && !savingName) setRenaming(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Rename Switch profile</DialogTitle>
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
              <Label htmlFor={`${id}-name`}>Profile name</Label>
              <Input
                id={`${id}-name`}
                value={renaming?.name ?? ""}
                autoFocus
                required
                maxLength={64}
                disabled={savingName}
                aria-describedby={renameError ? `${id}-rename-error` : undefined}
                onChange={(event) => {
                  const name = event.target.value;
                  setRenaming((current) => current && { ...current, name });
                }}
              />
              {renameError && (
                <p id={`${id}-rename-error`} role="alert" className="text-sm text-destructive">
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
    </article>
  );
}
