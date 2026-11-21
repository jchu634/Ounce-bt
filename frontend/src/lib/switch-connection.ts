import { useEffect, useRef, useState } from "react";
import { toast } from "@/src/components/ui/toast";
import {
  BluetoothDisconnectingError,
  BluetoothPageTimeoutError,
  requestStatus,
  type BluetoothStatus,
} from "@/src/lib/bluetooth";

export function useSwitchConnection(sessionId?: string) {
  const [status, setStatus] = useState<BluetoothStatus | null>(null);
  const [selected, setSelected] = useState("");
  const [busy, setBusy] = useState(false);
  const [statusError, setStatusError] = useState<string | null>(null);
  const lastFailureId = useRef<number | null>(null);
  const lastGripReminderId = useRef<number | null>(null);

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
    const gripReminderId = next.grip_reminder_id ?? 0;
    if (lastGripReminderId.current !== null && gripReminderId > lastGripReminderId.current) {
      toast.add({
        type: "info",
        title: "Register your Joy-Con grip",
        description: "Press SL and SR in Change Grip/Order, or run the Press SL and SR macro.",
        timeout: 8000,
      });
    }
    lastGripReminderId.current = Math.max(lastGripReminderId.current ?? 0, gripReminderId);
    setStatus(next);
  }

  useEffect(() => {
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    async function refresh() {
      try {
        const next = await requestStatus(undefined, sessionId);
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
  }, [sessionId]);

  async function update(
    method: "PUT" | "POST" | "DELETE",
    body: { pairing: boolean } | { address: string } | { action: "disconnect" },
  ) {
    setBusy(true);
    try {
      acceptStatus(
        await requestStatus(
          {
            method,
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          },
          sessionId,
        ),
      );
    } catch (cause) {
      const disconnecting = cause instanceof BluetoothDisconnectingError;
      const pageTimeout = cause instanceof BluetoothPageTimeoutError;
      toast.add({
        type: disconnecting ? "warning" : "error",
        priority: "high",
        title: disconnecting
          ? "Please wait before reconnecting"
          : pageTimeout
            ? "Switch did not respond"
            : "Connection error",
        description:
          disconnecting || pageTimeout
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
      await requestStatus(
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ address, name }),
        },
        sessionId,
      ),
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
