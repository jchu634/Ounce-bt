import {
  BluetoothIcon,
  LinkBreakIcon,
  LinkIcon,
  PencilSimpleIcon,
  PlugsConnectedIcon,
  PlugsIcon,
  SpinnerGapIcon,
  TrashIcon,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useId, useRef, useState, type MouseEvent } from "react";
import type { PresetInfo } from "@/src/lib/types";
import { ControllerColoursDialog } from "@/src/components/settings/controller-colours-dialog";
import { CONFIG_CHANGED_EVENT } from "@/src/components/settings/advanced-settings";
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
  SelectGroup,
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
  type CombinedInputMode,
} from "@/src/lib/adapters";
import { connectionDetail, deviceName, type BluetoothStatus } from "@/src/lib/bluetooth";
import {
  CONTROLLER_VARIANTS,
  CONTROLLER_VARIANT_NAMES,
  isBluetoothControllerType,
  type BluetoothControllerType,
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

type AdapterDisplayItem =
  | { kind: "single"; adapter: Adapter }
  | { kind: "pair"; left: Adapter; right: Adapter };

function groupAdapters(adapters: Adapter[]): AdapterDisplayItem[] {
  const byId = new Map(adapters.map((adapter) => [adapter.id, adapter]));
  const seen = new Set<string>();
  const items: AdapterDisplayItem[] = [];
  for (const adapter of adapters) {
    if (seen.has(adapter.id)) continue;
    const partner = adapter.combined_with ? byId.get(adapter.combined_with) : undefined;
    if (partner && partner.combined_with === adapter.id && !seen.has(partner.id)) {
      seen.add(adapter.id);
      seen.add(partner.id);
      const left = adapter.controller_type === "joycon_l" ? adapter : partner;
      const right = left === adapter ? partner : adapter;
      items.push({ kind: "pair", left, right });
    } else {
      seen.add(adapter.id);
      items.push({ kind: "single", adapter });
    }
  }
  return items;
}

export function ConnectionPanel({ onEditPreset }: { onEditPreset: (preset: PresetInfo) => void }) {
  const controller = useControllers();
  const { status, adapterStatuses, lastError, send } = useSocket();
  const selectedAdapters = Object.keys(adapterStatuses);
  const [inventory, setInventory] = useState<AdapterInventory | null>(null);
  const [settingsError, setSettingsError] = useState<{ id: string; message: string } | null>(null);
  const [pending, setPending] = useState<AdapterChange | null>(null);
  const [unpairingPair, setUnpairingPair] = useState<{ left: Adapter; right: Adapter } | null>(null);
  const [busyBluetooth, setBusyBluetooth] = useState<Record<string, boolean>>({});
  const inventoryVersion = useRef(0);
  const selectionAnchor = useRef<string | null>(null);
  const pendingSelection = useRef<string[] | null>(null);

  const reportBluetoothBusy = useCallback((adapterId: string, isBusy: boolean) => {
    setBusyBluetooth((current) => {
      if (!!current[adapterId] === isBusy) return current;
      return { ...current, [adapterId]: isBusy };
    });
  }, []);

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
    const handleConfigChanged = () => {
      clearTimeout(timer);
      void refresh();
    };
    window.addEventListener(CONFIG_CHANGED_EVENT, handleConfigChanged);
    void refresh();
    return () => {
      disposed = true;
      clearTimeout(timer);
      window.removeEventListener(CONFIG_CHANGED_EVENT, handleConfigChanged);
    };
  }, []);

  async function saveSettings(change: AdapterChange) {
    if (inventoryVersion.current % 2 !== 0) return;
    inventoryVersion.current++;
    setPending(change);
    setSettingsError(null);
    const errorTarget =
      change.kind === "pair" || change.kind === "unpair" || change.kind === "pair_mode"
        ? "__pair__"
        : change.adapterId;
    try {
      setInventory(await requestAdapters(change));
    } catch (cause) {
      setSettingsError({ id: errorTarget, message: errorMessage(cause) });
    } finally {
      inventoryVersion.current++;
      setPending(null);
    }
  }

  const displayItems = inventory ? groupAdapters(inventory.adapters) : [];
  const displayedAdapterIds = displayItems.flatMap((item) =>
    item.kind === "pair" ? [item.left.id, item.right.id] : [item.adapter.id],
  );

  function pairMembers(targetId: string): string[] {
    for (const item of displayItems) {
      if (item.kind === "pair" && (item.left.id === targetId || item.right.id === targetId)) {
        return [item.left.id, item.right.id];
      }
    }
    return [targetId];
  }

  function expandWithPairs(ids: string[]): string[] {
    const selectedSet = new Set(ids);
    for (const item of displayItems) {
      if (item.kind === "pair" && (selectedSet.has(item.left.id) || selectedSet.has(item.right.id))) {
        selectedSet.add(item.left.id);
        selectedSet.add(item.right.id);
      }
    }
    return displayedAdapterIds.filter((adapterId) => selectedSet.has(adapterId));
  }

  function selectAdapter(id: string, modifiers: AdapterSelectionModifiers) {
    if (!inventory) return;
    const adapterIds = displayedAdapterIds;
    const current = pendingSelection.current ?? selectedAdapters;
    const additive = modifiers.ctrlKey || modifiers.metaKey;
    const members = pairMembers(id);
    let next = members;
    if (modifiers.shiftKey) {
      const anchorId = selectionAnchor.current ?? current[0];
      const index = adapterIds.indexOf(id);
      const anchor = anchorId ? adapterIds.indexOf(anchorId) : -1;
      const start = anchor < 0 ? index : anchor;
      const range = adapterIds.slice(Math.min(start, index), Math.max(start, index) + 1);
      next = expandWithPairs(additive ? [...current, ...range] : range);
    } else {
      selectionAnchor.current = id;
      if (additive) {
        next = members.some((member) => current.includes(member))
          ? current.filter((adapterId) => !members.includes(adapterId))
          : expandWithPairs([...current, ...members]);
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

  const adaptersById = new Map((inventory?.adapters ?? []).map((adapter) => [adapter.id, adapter]));
  const selectedAdapterList = selectedAdapters
    .map((adapterId) => adaptersById.get(adapterId))
    .filter((adapter): adapter is Adapter => adapter !== undefined);

  let selectedPair: { left: Adapter; right: Adapter } | null = null;
  let canPairSelected = false;
  let pairActionTitle = "Select a Joy-Con L and Joy-Con R adapter to pair";
  if (selectedAdapterList.length === 2) {
    const [first, second] = selectedAdapterList;
    const btBusy = !!busyBluetooth[first.id] || !!busyBluetooth[second.id];
    const macroBusy = first.macro_mode || second.macro_mode;
    if (first.combined_with === second.id && second.combined_with === first.id) {
      const left = first.controller_type === "joycon_l" ? first : second;
      const right = left === first ? second : first;
      selectedPair = { left, right };
      pairActionTitle = btBusy
        ? "Disconnect and stop pairing before unpairing adapters"
        : macroBusy
          ? "Stop running macros before unpairing adapters"
          : "Unpair selected Joy-Con adapters";
    } else if (
      !first.combined_with &&
      !second.combined_with &&
      !first.error &&
      !second.error &&
      first.local_address &&
      second.local_address &&
      ((first.controller_type === "joycon_l" && second.controller_type === "joycon_r") ||
        (first.controller_type === "joycon_r" && second.controller_type === "joycon_l"))
    ) {
      canPairSelected = !btBusy && !macroBusy && pending === null;
      pairActionTitle = btBusy
        ? "Disconnect and stop pairing before pairing adapters"
        : macroBusy
          ? "Stop running macros before pairing adapters"
          : "Pair selected Joy-Con L and Joy-Con R as a combined Joy-Con";
    }
  }
  const canUnpairSelected =
    selectedPair !== null &&
    !busyBluetooth[selectedPair.left.id] &&
    !busyBluetooth[selectedPair.right.id] &&
    !selectedPair.left.macro_mode &&
    !selectedPair.right.macro_mode &&
    pending === null;

  function renderAdapterCard(adapter: Adapter, partner?: Adapter) {
    if (!inventory) return null;
    const combined = !!partner;
    const inputMode: CombinedInputMode = combined
      ? (adapter.combined_input_mode ?? "combined")
      : "combined";
    const combinedShared = combined && inputMode === "combined";
    const isSharedFollower = combinedShared && adapter.controller_type === "joycon_r";
    const source = isSharedFollower && partner ? partner : adapter;
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
          (slot) => slot.id !== source.id && slot.controller_id === entry.id,
        ),
      })),
      active: source.controller_id?.toString() ?? null,
      controllerGuid: pad?.guid ?? null,
      hasGyro: pad?.has_gyro,
      preset: source.preset,
      presetLabel:
        partner && inputMode === "individual"
          ? source.controller_type === "joycon_r"
            ? "Joycon (R)"
            : "Joycon (L)"
          : undefined,
      pending:
        pending?.kind === "assign"
          ? "selecting"
          : pending?.kind === "preset"
            ? "applying"
            : null,
      error:
        settingsError?.id === adapter.id || settingsError?.id === source.id
          ? settingsError.message
          : null,
      macroMode: source.macro_mode,
      allowUnassign: true,
      selectController: (id) =>
        void saveSettings({
          kind: "assign",
          adapterId: source.id,
          controllerId: id === null ? null : Number(id),
        }),
      applyPreset: (preset) =>
        void saveSettings({ kind: "preset", adapterId: source.id, preset }),
      partnerPreset:
        partner && inputMode === "individual"
          ? {
              label:
                partner.controller_type === "joycon_r"
                  ? "Joycon (R)"
                  : "Joycon (L)",
              preset: partner.preset,
              macroMode: partner.macro_mode,
              applyPreset: (preset) =>
                void saveSettings({ kind: "preset", adapterId: partner.id, preset }),
            }
          : undefined,
    };

    const controllerName = isSharedFollower
      ? `↳ Shared with ${pad?.name ?? "Joy-Con L"}`
      : pad?.name;

    return (
      <ConnectionCard
        key={adapter.id}
        adapter={adapter}
        controllerName={controllerName}
        mutedTitle={isSharedFollower}
        combinedShared={combinedShared}
        mapping={mapping}
        onChangeOutput={(output) =>
          void saveSettings({
            kind: "type",
            adapterId: adapter.id,
            output,
          })
        }
        changingOutput={pending !== null}
        onEditPreset={onEditPreset}
        onBluetoothBusyChange={reportBluetoothBusy}
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
  }

  const joyconPairingEnabled = inventory?.joycon_pairing_enabled === true;

  return (
    <section aria-label="Connection" className="min-w-0 space-y-2">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-lg font-semibold">Connection</h2>
        {inventory && inventory.adapters.length > 1 && (joyconPairingEnabled || selectedPair !== null) && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-7 gap-1.5 rounded-lg px-2.5 text-xs"
            title={pairActionTitle}
            disabled={selectedPair ? !canUnpairSelected : !canPairSelected}
            onClick={() => {
              if (selectedPair) {
                setUnpairingPair(selectedPair);
              } else if (selectedAdapterList.length === 2) {
                void saveSettings({
                  kind: "pair",
                  adapterIds: [selectedAdapterList[0].id, selectedAdapterList[1].id],
                });
              }
            }}
          >
            {selectedPair ? <LinkBreakIcon className="size-3.5" /> : <LinkIcon className="size-3.5" />}
            {selectedPair ? "Unpair" : "Pair"}
          </Button>
        )}
      </div>
      {settingsError?.id === "__pair__" && (
        <p role="alert" className="text-xs text-destructive">
          {settingsError.message}
        </p>
      )}
      {displayItems.length ? (
        displayItems.map((item) => {
          if (item.kind === "single") {
            return renderAdapterCard(item.adapter);
          }
          const { left, right } = item;
          const inputMode: CombinedInputMode = left.combined_input_mode ?? "combined";
          const modeDisabled = pending !== null || left.macro_mode || right.macro_mode;
          const unlinkDisabled =
            modeDisabled || !!busyBluetooth[left.id] || !!busyBluetooth[right.id];
          return (
            <div key={`${left.id}:${right.id}`} className="flex flex-col">
              {renderAdapterCard(left, right)}
              <PairConnectorBar
                left={left}
                right={right}
                inputMode={inputMode}
                modeDisabled={modeDisabled}
                unlinkDisabled={unlinkDisabled}
                onChangeMode={(nextMode) => {
                  if (nextMode !== inputMode) {
                    void saveSettings({
                      kind: "pair_mode",
                      adapterId: left.id,
                      inputMode: nextMode,
                    });
                  }
                }}
                onRequestUnpair={() => setUnpairingPair({ left, right })}
              />
              {renderAdapterCard(right, left)}
            </div>
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

      <Dialog
        open={unpairingPair !== null}
        onOpenChange={(open) => {
          if (!open && pending?.kind !== "unpair") setUnpairingPair(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Unpair Joy-Con adapters?</DialogTitle>
            <DialogDescription>
              Separating {unpairingPair?.left.transport} and {unpairingPair?.right.transport} will
              return them to standalone Joy-Con L and Joy-Con R adapters.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <DialogClose render={<Button variant="outline" disabled={pending?.kind === "unpair"} />}>
              Cancel
            </DialogClose>
            <Button
              variant="destructive"
              disabled={!unpairingPair || pending !== null}
              onClick={() => {
                if (!unpairingPair) return;
                const adapterId = unpairingPair.left.id;
                setUnpairingPair(null);
                void saveSettings({ kind: "unpair", adapterId });
              }}
            >
              Unpair
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}

function PairConnectorBar({
  left,
  right,
  inputMode,
  modeDisabled,
  unlinkDisabled,
  onChangeMode,
  onRequestUnpair,
}: {
  left: Adapter;
  right: Adapter;
  inputMode: CombinedInputMode;
  modeDisabled: boolean;
  unlinkDisabled: boolean;
  onChangeMode: (mode: CombinedInputMode) => void;
  onRequestUnpair: () => void;
}) {
  return (
    <div className="relative grid grid-cols-[1fr_auto_1fr] items-center py-1">
      <span
        aria-hidden="true"
        className="pointer-events-none absolute -top-px -bottom-px left-11 w-0.5 bg-primary/65"
      />
      <div />
      <div
        role="group"
        aria-label="Paired Joy-Con input mode"
        className="relative z-10 inline-flex items-center gap-0.5 rounded-full border border-border bg-card p-0.5 text-xs shadow-xs"
      >
        <LinkIcon aria-hidden="true" className="mx-1.5 size-3.5 shrink-0 text-primary" />
        <button
          type="button"
          aria-pressed={inputMode === "combined"}
          disabled={modeDisabled}
          onClick={() => onChangeMode("combined")}
          className={cn(
            "rounded-full px-2.5 py-0.5 font-medium transition-colors disabled:opacity-50",
            inputMode === "combined"
              ? "bg-primary text-primary-foreground"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          Combined
        </button>
        <button
          type="button"
          aria-pressed={inputMode === "individual"}
          disabled={modeDisabled}
          onClick={() => onChangeMode("individual")}
          className={cn(
            "rounded-full px-2.5 py-0.5 font-medium transition-colors disabled:opacity-50",
            inputMode === "individual"
              ? "bg-primary text-primary-foreground"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          Individual
        </button>
      </div>
      <div className="relative z-10 flex justify-end pr-0.5">
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          className="action-hover size-7 rounded-lg text-muted-foreground"
          aria-label={`Unpair ${left.transport} and ${right.transport}`}
          title="Unpair Joy-Con adapters"
          disabled={unlinkDisabled}
          onClick={onRequestUnpair}
        >
          <LinkBreakIcon />
        </Button>
      </div>
    </div>
  );
}

type AdapterSelectionModifiers = Pick<MouseEvent, "shiftKey" | "ctrlKey" | "metaKey">;

function ConnectionCard({
  adapter,
  controllerName = "No controller selected",
  mutedTitle = false,
  combinedShared = false,
  mapping,
  onEditPreset,
  inputTarget,
  onChangeOutput,
  changingOutput,
  onBluetoothBusyChange,
}: {
  adapter?: Adapter;
  controllerName?: string;
  mutedTitle?: boolean;
  combinedShared?: boolean;
  mapping: MappingSettings;
  onEditPreset: (preset: PresetInfo) => void;
  inputTarget?: { selected: boolean; select: (modifiers: AdapterSelectionModifiers) => void };
  onChangeOutput?: (output: { controller_type: BluetoothControllerType }) => void;
  changingOutput?: boolean;
  onBluetoothBusyChange?: (adapterId: string, isBusy: boolean) => void;
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
  const outputOptions = CONTROLLER_VARIANTS.filter(isBluetoothControllerType).map((type) => ({
    value: type,
    label: CONTROLLER_VARIANT_NAMES[type],
    variant: type,
  }));
  const controllerSelection = mapping.active ?? (mapping.allowUnassign ? "unassigned" : null);
  const activeControllerName = mapping.options.find((option) => option.id === mapping.active)?.name;

  useEffect(() => {
    if (!adapter || !onBluetoothBusyChange) return;
    onBluetoothBusyChange(adapter.id, active || pairing);
  }, [adapter, active, pairing, onBluetoothBusyChange]);

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
          combinedShared={combinedShared}
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
          {mutedTitle ? (
            <h3
              id={`${id}-controller`}
              className="min-w-0 flex-1 truncate text-sm font-normal text-muted-foreground"
              title={controllerName}
            >
              {controllerName}
            </h3>
          ) : (
            <div className="min-w-44 flex-1">
              <Select
                value={controllerSelection}
                disabled={
                  !mapping.available ||
                  mapping.options.length === 0 ||
                  mapping.pending !== null ||
                  mapping.macroMode
                }
                onValueChange={(value) => {
                  if (value !== null && value !== controllerSelection) {
                    mapping.selectController(value === "unassigned" ? null : value);
                  }
                }}
              >
                <SelectTrigger
                  id={`${id}-controller`}
                  size="sm"
                  className="w-full min-w-0"
                  aria-label="Select controller"
                  title={activeControllerName ?? controllerName}
                >
                  <SelectValue placeholder="No controller selected" className="min-w-0">
                    <span className="truncate">
                      {activeControllerName ??
                        (mapping.allowUnassign ? "No controller" : "No controller selected")}
                    </span>
                  </SelectValue>
                </SelectTrigger>
                <SelectContent align="start">
                  <SelectGroup>
                    {mapping.allowUnassign && (
                      <SelectItem value="unassigned">No controller</SelectItem>
                    )}
                    {mapping.options.map((entry) => (
                      <SelectItem key={entry.id} value={entry.id} disabled={entry.disabled}>
                        {entry.name}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
            </div>
          )}
          <div className="ms-auto flex shrink-0 items-center gap-1.5">
            <ConnectionStatus status={status} statusError={statusError} />
            <ControllerMappingDialog
              controller={mapping}
              usbAdapter={
                adapter
                  ? { transport: adapter.transport, address: adapter.local_address }
                  : undefined
              }
              onEditPreset={onEditPreset}
              bluetoothOutput={
                adapter && onChangeOutput
                  ? {
                      value: controllerType,
                      options: outputOptions,
                      disabled:
                        combined ||
                        disabled ||
                        active ||
                        pairing ||
                        !!changingOutput ||
                        adapter.macro_mode,
                      error: null,
                      select: (value) => {
                        if (isBluetoothControllerType(value)) {
                          onChangeOutput({ controller_type: value });
                        }
                      },
                    }
                  : undefined
              }
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
