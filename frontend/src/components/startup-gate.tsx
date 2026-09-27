import { useEffect, useState, type ReactNode } from "react";
import { Button } from "@/src/components/ui/button";
import { configureWebSocketAuth, desktopApi } from "@/src/lib/desktop";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/src/components/ui/dialog";

type StartupState =
  | { kind: "loading" }
  | { kind: "ready" }
  | { kind: "missing_firmware"; filename: string };

export function StartupGate({ children }: { children: ReactNode }) {
  const [state, setState] = useState<StartupState>({ kind: "loading" });
  const [closing, setClosing] = useState(false);
  const [closed, setClosed] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let retry: ReturnType<typeof setTimeout> | undefined;
    async function check() {
      try {
        const response = await fetch("/api/startup", { signal: controller.signal });
        if (!response.ok) throw new Error("Startup check failed");
        const body: unknown = await response.json();
        if (typeof body !== "object" || body === null || !("kind" in body)) {
          throw new Error("Invalid startup response");
        }
        if (!("ws_auth_required" in body) || typeof body.ws_auth_required !== "boolean") {
          throw new Error("Invalid startup security settings");
        }
        configureWebSocketAuth(body.ws_auth_required);
        if (body.kind === "ready") {
          setState({ kind: "ready" });
        } else if (
          body.kind === "missing_firmware" &&
          "filename" in body &&
          typeof body.filename === "string"
        ) {
          setState({ kind: "missing_firmware", filename: body.filename });
        } else {
          throw new Error("Invalid startup response");
        }
        setError(null);
      } catch {
        if (controller.signal.aborted) return;
        setError("Waiting for the application backend…");
        retry = setTimeout(() => void check(), 1000);
      }
    }
    void check();
    return () => {
      controller.abort();
      clearTimeout(retry);
    };
  }, []);

  async function closeApplication() {
    setClosing(true);
    setError(null);
    try {
      const api = desktopApi();
      if (api) {
        await api.close_application();
        return;
      }
      const response = await fetch("/api/application/close", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      if (!response.ok) throw new Error("Shutdown failed");
      setClosed(true);
      window.close();
    } catch {
      setError("Could not close the application. Please try again.");
      setClosing(false);
    }
  }

  if (state.kind === "ready") return children;
  if (state.kind === "loading") {
    return (
      <p role="status" className="p-6">
        {error ?? "Checking application files…"}
      </p>
    );
  }
  return (
    <Dialog open onOpenChange={() => {}}>
      <DialogContent showCloseButton={false}>
        <DialogHeader>
          <DialogTitle>Required firmware is missing</DialogTitle>
          <DialogDescription>
            Firmware is not distributed with Ounce-bt for licensing and legal reasons. Place your
            separately obtained {state.filename} file in the application root folder, beside the
            executable, then restart the application.
          </DialogDescription>
        </DialogHeader>
        {error && <p role="alert">{error}</p>}
        {closed && <p role="status">The backend has stopped. You can close this window.</p>}
        <DialogFooter>
          <Button disabled={closing} onClick={() => void closeApplication()}>
            {closed ? "Application closed" : closing ? "Closing…" : "Close application"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
