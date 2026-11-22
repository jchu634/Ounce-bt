import {
  BluetoothIcon,
  PencilSimpleIcon,
  PlugsConnectedIcon,
  PlugsIcon,
  SpinnerGapIcon,
  TrashIcon,
} from "@phosphor-icons/react";
import { useEffect, useId, useRef, useState, type MouseEvent } from "react";
import type { PresetInfo } from "@/src/lib/types";
import { ControllerColoursDialog } from "@/src/components/settings/controller-colours-dialog";
import {
  ControllerMappingDialog,
  type MappingSettings,
} from "@/src/components/settings/controller-mapping-dialog";
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
import { Tooltip, TooltipContent, TooltipTrigger } from "@/src/components/ui/tooltip";
import { useControllers } from "@/src/hooks/use-controllers";
import { useSocket } from "@/src/hooks/use-socket";
import {
  requestAdapters,
  type Adapter,
  type AdapterChange,
  type AdapterInventory,
} from "@/src/lib/adapters";
import { connectionDetail, deviceName, type BluetoothStatus } from "@/src/lib/bluetooth";
import {
  CONTROLLER_VARIANTS,
  CONTROLLER_VARIANT_NAMES,
  isBluetoothControllerType,
  type ControllerVariant,
} from "@/src/lib/controller-variants";
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
      variant={status?.state === "disconnected" ? "destructive" : "outline"}
      size="icon-sm"
      className={cn(
        "rounded-lg",
        status?.state === "connected" &&
          "border-transparent bg-green-700 text-white hover:bg-green-800 hover:text-white dark:bg-green-700 dark:hover:bg-green-800",
      )}
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
    <p className="flex shrink-0 items-center gap-1 text-sm text-muted-foreground">
      <span>{statusLabel}</span>
      <Tooltip>
        <TooltipTrigger
          render={<span tabIndex={0} />}
          aria-label="Bluetooth connection details"
          className="pointer-events-auto grid size-4 place-items-center rounded-full focus-visible:outline-2 focus-visible:outline-ring"
        >
          <span
            aria-hidden
            className={cn(
              "size-1.5 rounded-full bg-current",
              statusTone === "connected" && "bg-emerald-500",
              statusTone === "pending" && "bg-amber-500",
              statusTone === "error" && "bg-destructive",
            )}
          />
        </TooltipTrigger>
        <TooltipContent>
          {statusDetail}
          {status?.state === "disconnecting" && !statusError && status.address && (
            <span className="font-mono">{status.address}</span>
          )}
        </TooltipContent>
      </Tooltip>
    </p>
  );
}

export function ConnectionPanel({ onEditPreset }: { onEditPreset: (preset: PresetInfo) => void }) {
  const controller = useControllers();
  const { status, adapterStatuses, lastError, send } = useSocket();
  const selectedAdapters = Object.keys(adapterStatuses);
  const [inventory, setInventory] = useState<AdapterInventory | null>(null);
  const [settingsError, setSettingsError] = useState<{ id: string; message: string } | null>(null);
  const [pending, setPending] = useState<AdapterChange | null>(null);
  const inventoryVersion = useRef(0);
  const selectionAnchor = useRef<string | null>(null);
  const pendingSelection = useRef<string[] | null>(null);

  useEffect(() => {
    const pending = pendingSelection.current;
    if (
      pending &&
      pending.length === Object.keys(adapterStatuses).length &&
      pending.every((id) => Object.hasOwn(adapterStatuses, id))
    ) {
      pendingSelection.current = null;
    }
  }, [adapterStatuses]);

  useEffect(() => {
    if (lastError?.message === "Unknown adapter") pendingSelection.current = null;
  }, [lastError]);

  useEffect(() => {
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    async function refresh() {
      const version = inventoryVersion.current;
      try {
        const next = await requestAdapters();
        if (!disposed && version === inventoryVersion.current && version % 2 === 0) {
          setInventory(next);
        }
      } catch {
        // The legacy connection card still works when inventory is unavailable.
      } finally {
        if (!disposed) timer = setTimeout(() => void refresh(), 1000);
      }
    }
    void refresh();
    return () => {
      disposed = true;
      clearTimeout(timer);
    };
  }, []);

  async function saveSettings(change: AdapterChange) {
    if (inventoryVersion.current % 2 !== 0) return;
    inventoryVersion.current++;
    setPending(change);
    setSettingsError(null);
    try {
      setInventory(await requestAdapters(change));
    } catch (cause) {
      setSettingsError({ id: change.adapterId, message: errorMessage(cause) });
    } finally {
      inventoryVersion.current++;
      setPending(null);
    }
  }

  function selectAdapter(id: string, modifiers: AdapterSelectionModifiers) {
    if (!inventory) return;
    const adapterIds = inventory.adapters.map((adapter) => adapter.id);
    const current = pendingSelection.current ?? selectedAdapters;
    const additive = modifiers.ctrlKey || modifiers.metaKey;
    let next = [id];
    if (modifiers.shiftKey) {
      const anchorId = selectionAnchor.current ?? current[0];
      const index = adapterIds.indexOf(id);
      const anchor = anchorId ? adapterIds.indexOf(anchorId) : -1;
      const start = anchor < 0 ? index : anchor;
      const range = adapterIds.slice(Math.min(start, index), Math.max(start, index) + 1);
      next = additive
        ? adapterIds.filter(
            (adapterId) => current.includes(adapterId) || range.includes(adapterId),
          )
        : range;
    } else {
      selectionAnchor.current = id;
      if (additive) {
        next = current.includes(id)
          ? current.filter((adapterId) => adapterId !== id)
          : adapterIds.filter((adapterId) => current.includes(adapterId) || adapterId === id);
        if (next.length === 0) return;
      }
    }
    const [first, ...rest] = next;
    if (first === undefined) return;
    const sent = send(
      rest.length === 0
        ? { type: "select_adapter", adapter_id: first }
        : { type: "select_adapters", adapter_ids: next },
    );
    if (sent) pendingSelection.current = next;
  }

  const legacyMapping: MappingSettings = {
    available: controller.available,
    options: controller.controllers.map((pad) => ({
      id: pad.instance_id.toString(),
      name: pad.name,
    })),
    active: controller.activeInfo?.instance_id.toString() ?? null,
    controllerGuid: controller.activeInfo?.guid ?? null,
    hasGyro: controller.activeInfo?.has_gyro,
    preset: controller.preset,
    error: controller.error,
    pending: controller.pending,
    macroMode: status?.mode === "macro",
    allowUnassign: true,
    selectController: (id) => void controller.update({ kind: "selecting", id }),
    applyPreset: (preset) => void controller.update({ kind: "applying", preset }),
  };

  return (
    <section aria-label="Connection" className="min-w-0 space-y-2">
      <h2 className="text-lg font-semibold">Connection</h2>
      {inventory?.adapters.length ? (
        inventory.adapters.map((adapter) => {
          const follower = adapter.controller_type === "joycon_r" && !!adapter.combined_with;
          const source = follower
            ? inventory.adapters.find((item) => item.id === adapter.combined_with) ?? adapter
            : adapter;
          const pad = inventory.controllers.find((entry) => entry.id === source.controller_id);
          const multiple = inventory.adapters.length > 1;
          const mapping: MappingSettings = {
            available: inventory.controllers_available,
            options: inventory.controllers.map((entry) => ({
              id: entry.id.toString(),
              name: inventory.controllers.some(
                (other) => other.id !== entry.id && other.name === entry.name,
              )
                ? `${entry.name} (${entry.id})`
                : entry.name,
              disabled: inventory.adapters.some(
                (slot) => slot.id !== adapter.id && slot.controller_id === entry.id,
              ),
            })),
            active: adapter.controller_id?.toString() ?? null,
            controllerGuid: pad?.guid ?? null,
            hasGyro: pad?.has_gyro,
            preset: adapter.preset,
            pending: pending?.kind === "assign" ? "selecting" : pending?.kind === "preset" ? "applying" : null,
            error: settingsError?.id === adapter.id ? settingsError.message : null,
            macroMode: adapter.macro_mode,
            allowUnassign: true,
            selectController: (id) =>
              void saveSettings({
                kind: "assign",
                adapterId: adapter.id,
                controllerId: id === null ? null : Number(id),
              }),
            applyPreset: (preset) =>
              void saveSettings({ kind: "preset", adapterId: adapter.id, preset }),
          };
          return (
            <ConnectionCard
              key={adapter.id}
              adapter={adapter}
              controllerName={pad?.name}
              mapping={mapping}
              outputAdapters={inventory.adapters.filter((item) =>
                item.id === adapter.combined_with || (
                  item.id !== adapter.id && !item.error && item.local_address && !item.combined_with
                ))}
              onChangeOutput={(output) => void saveSettings({
                kind: "type",
                adapterId: adapter.id,
                output,
              })}
              changingOutput={pending !== null}
              onEditPreset={onEditPreset}
              inputTarget={
                multiple
                  ? {
                      selected: selectedAdapters.includes(adapter.id),
                      select: (modifiers) => selectAdapter(adapter.id, modifiers),
                    }
                  : undefined
              }
            />
          );
        })
      ) : (
        <ConnectionCard
          key="primary"
          controllerName={controller.activeInfo?.name}
          mapping={legacyMapping}
          onEditPreset={onEditPreset}
        />
      )}
    </section>
  );
}

type AdapterSelectionModifiers = Pick<MouseEvent, "shiftKey" | "ctrlKey" | "metaKey">;

function ConnectionCard({
  adapter,
  controllerName = "No controller selected",
  mapping,
  onEditPreset,
  inputTarget,
  outputAdapters = [],
  onChangeOutput,
  changingOutput,
}: {
  adapter?: Adapter;
  controllerName?: string;
  mapping: MappingSettings;
  onEditPreset: (preset: PresetInfo) => void;
  inputTarget?: { selected: boolean; select: (modifiers: AdapterSelectionModifiers) => void };
  outputAdapters?: Adapter[];
  onChangeOutput?: (output: Extract<AdapterChange, { kind: "type" }>["output"]) => void;
  changingOutput?: boolean;
}) {
  const connection = useSwitchConnection(adapter?.id === "primary" ? undefined : adapter?.id);
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
  const [deleting, setDeleting] = useState<{ address: string; name: string } | null>(null);
  const [renaming, setRenaming] = useState<{ address: string; name: string } | null>(null);
  const [savingName, setSavingName] = useState(false);
  const [renameError, setRenameError] = useState<string | null>(null);
  const pairing = status?.pairing ?? false;
  const pairingAction = pairing ? "Stop pairing" : "Start pairing";
  const controllerType = adapter?.controller_type ?? "pro";
  const combined = !!adapter?.combined_with;
  const follower = combined && controllerType === "joycon_r";
  const outputValue = combined
    ? follower ? "combined-right" : `combined:${adapter?.combined_with}`
    : controllerType;
  const outputOptions = [
    ...CONTROLLER_VARIANTS.filter(isBluetoothControllerType).map((type) => ({
      value: type,
      label: CONTROLLER_VARIANT_NAMES[type],
      variant: type,
    })),
    ...(follower
      ? [{ value: "combined-right", label: "Joycons (right)", variant: controllerType, disabled: true }]
      : outputAdapters.map((item): { value: string; label: string; variant: ControllerVariant } => ({
          value: `combined:${item.id}`,
          label: `Joycons with ${item.transport}`,
          variant: "combined",
        }))),
  ];

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
      className={cn(
        "relative isolate grid min-w-0 grid-cols-[auto_minmax(0,1fr)] items-start gap-2 rounded-xl border border-border bg-card p-2.5 text-card-foreground",
        inputTarget?.selected && "border-primary ring-1 ring-primary",
      )}
    >
      {inputTarget && (
        <button
          type="button"
          aria-label={`Send manual and macro input through ${adapter?.transport}`}
          aria-pressed={inputTarget.selected}
          title="Shift to select a range. Ctrl+Shift to add a range. Ctrl to toggle."
          onClick={inputTarget.select}
          onKeyDown={(event) => {
            if (
              (event.key === "Enter" || event.key === " ") &&
              (event.shiftKey || event.ctrlKey || event.metaKey)
            ) {
              event.preventDefault();
              if (!event.repeat) inputTarget.select(event);
            }
          }}
          className="absolute inset-0 z-0 cursor-pointer rounded-xl outline-offset-2 focus-visible:outline-2 focus-visible:outline-ring"
        />
      )}
      <div className="relative z-10 self-center">
        <ControllerColoursDialog
          key={controllerType}
          adapterId={adapter?.id}
          variant={adapter?.controller_type}
          upright={combined}
        />
        {!!status?.player_number && (
          <p className="pointer-events-none text-center text-xs text-muted-foreground">
            Player {status.player_number}
          </p>
        )}
      </div>
      <div
        className={cn(
          "relative z-10 min-w-0 space-y-1.5",
          inputTarget && "pointer-events-none [&_button]:pointer-events-auto",
        )}
      >
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
            <ControllerMappingDialog
              controller={follower ? undefined : mapping}
              usbAdapter={
                adapter
                  ? { transport: adapter.transport, address: adapter.local_address }
                  : undefined
              }
              onEditPreset={onEditPreset}
              bluetoothOutput={adapter && onChangeOutput ? {
                value: outputValue,
                options: outputOptions,
                disabled: disabled || active || pairing || !!changingOutput || adapter.macro_mode,
                error: follower ? mapping.error : null,
                select: (value) => {
                  if (isBluetoothControllerType(value)) {
                    onChangeOutput({ controller_type: value });
                  } else if (value.startsWith("combined:")) {
                    onChangeOutput({ controller_type: "combined", companion_id: value.slice(9) });
                  }
                },
              } : undefined}
            />
          </div>
        </div>
        <div className="flex min-w-0 flex-wrap items-center gap-1.5">
          <div className="flex shrink-0 items-center gap-1.5">
            <ConnectionToggleButton
              status={status}
              address={address}
              disabled={disabled}
              busy={busy}
              onReconnect={() => void update("POST", { address })}
              onDisconnect={() => void update("POST", { action: "disconnect" })}
            />
            <Button
              variant="outline"
              size="icon-sm"
              className="action-hover rounded-lg"
              aria-label={pairingAction}
              aria-pressed={pairing}
              title={pairingAction}
              disabled={disabled || (!pairing && active)}
              onClick={() => void update("PUT", { pairing: !pairing })}
            >
              <BluetoothIcon weight={pairing ? "bold" : "regular"} />
            </Button>
          </div>
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
            className="action-hover"
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
                    className="switch-delete rounded-lg text-destructive dark:text-red-400"
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
        {combined && pairing && (
          <p className="text-xs text-muted-foreground">
            Pair both Joy-Cons to the same Switch to register them together.
          </p>
        )}
        {statusError && <p className="text-xs text-destructive">{statusError}</p>}
        {adapter?.error && <p className="text-xs text-destructive">{adapter.error}</p>}
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
