import { useCallback, useEffect, useState } from "react";
import { Effect } from "effect";
import { useSocket } from "@/src/hooks/use-socket";
import { activatePreset, getControllers, selectController } from "@/src/lib/api";
import { errorMessage } from "@/src/lib/errors";
import type { ControllersFrame } from "@/src/lib/types";

export function useControllers() {
  const { controllers: frame } = useSocket();
  const [restFrame, setRestFrame] = useState<ControllersFrame | null>(null);
  const [pending, setPending] = useState<"selecting" | "applying" | null>(null);
  const [error, setError] = useState<string | null>(null);

  // REST fallback for state between WS frames (e.g. right after connect).
  useEffect(() => {
    Effect.runPromise(getControllers())
      .then((next) => setRestFrame((current) => current ?? next))
      .catch(() => {});
  }, []);

  const data = frame ?? restFrame;
  const controllers = data?.controllers ?? [];
  const active = data?.active ?? null;

  const update = useCallback(
    async (action: { kind: "selecting"; id: string } | { kind: "applying"; preset: string }) => {
      setPending(action.kind);
      setError(null);
      try {
        const result = await Effect.runPromise(
          action.kind === "selecting" ? selectController(action.id) : activatePreset(action.preset),
        );
        setRestFrame(result);
      } catch (cause: unknown) {
        setError(errorMessage(cause));
      } finally {
        setPending(null);
      }
    },
    [],
  );

  const activeInfo = controllers.find((c) => c.guid === active) ?? null;

  return {
    available: data?.available ?? false,
    controllers,
    active,
    activeInfo,
    preset: data?.preset ?? null,
    pending,
    error,
    update,
  };
}
