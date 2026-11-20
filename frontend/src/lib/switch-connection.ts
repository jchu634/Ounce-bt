import { useEffect, useRef, useState } from "react";
import { toast } from "@/src/components/ui/toast";
import {
  BluetoothDisconnectingError,
  requestStatus,
  type BluetoothStatus,
} from "@/src/lib/bluetooth";

export function useSwitchConnection() {
  const [status, setStatus] = useState<BluetoothStatus | null>(null);
  const [selected, setSelected] = useState("");
  const [busy, setBusy] = useState(false);
  const [statusError, setStatusError] = useState<string | null>(null);
  const lastFailureId = useRef<number | null>(null);

  function acceptStatus(next: BluetoothStatus) {
    if (lastFailureId.current !== null && next.failure_id > lastFailureId.current && next.failure) {
      toast.add({
        type: "warning",
        priority: "high",
        title: "Controller disconnected",
        description: `${next.failure} Try connecting again. If the issue persists, restart the app.`,
        timeout: 5000,
      });
    }
    lastFailureId.current = Math.max(lastFailureId.current ?? next.failure_id, next.failure_id);
    setStatus(next);
  }

  useEffect(() => {
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    async function refresh() {
      try {
        const next = await requestStatus();
        if (!disposed) {
          acceptStatus(next);
          setStatusError(null);
        }
      } catch (cause) {
        if (!disposed)
          setStatusError(
            cause instanceof Error ? cause.message : "Could not load Bluetooth status",
          );
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

  async function update(
    method: "PUT" | "POST" | "DELETE",
    body: { pairing: boolean } | { address: string } | { action: "disconnect" },
  ) {
    setBusy(true);
    try {
      acceptStatus(
        await requestStatus({
          method,
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        }),
      );
    } catch (cause) {
      const disconnecting = cause instanceof BluetoothDisconnectingError;
      toast.add({
        type: disconnecting ? "warning" : "error",
        priority: "high",
        title: disconnecting ? "Please wait before reconnecting" : "Connection error",
        description: disconnecting
          ? cause.message
          : `${cause instanceof Error ? cause.message : "Bluetooth operation failed"} Try connecting again. If the issue persists, restart the app.`,
        timeout: 5000,
      });
    } finally {
      setBusy(false);
    }
  }

  const address =
    status?.address && status.peers.includes(status.address)
      ? status.address
      : status?.peers.includes(selected)
        ? selected
        : (status?.peers[0] ?? "");
  const disabled = busy || statusError !== null || !status?.available;
  const active = status?.state !== "disconnected";

  async function rename(address: string, name: string): Promise<void> {
    acceptStatus(
      await requestStatus({
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ address, name }),
      }),
    );
  }

  return {
    status,
    selected: address,
    setSelected,
    busy,
    statusError,
    disabled,
    active,
    update,
    rename,
  };
}
