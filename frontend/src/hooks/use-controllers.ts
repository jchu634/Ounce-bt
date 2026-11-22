import { useCallback, useEffect, useState } from "react";
import { Effect } from "effect";
import { useSocket } from "@/src/hooks/use-socket";
import { requestAdapters } from "@/src/lib/adapters";
import { activatePreset, getControllers } from "@/src/lib/api";
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
    async (
      action:
        | { kind: "selecting"; id: string | null }
        | { kind: "applying"; preset: string },
    ) => {
      setPending(action.kind);
      setError(null);
      try {
        if (action.kind === "selecting") {
          await requestAdapters({
            kind: "assign",
            adapterId: "primary",
            controllerId: action.id === null ? null : Number(action.id),
          });
          setRestFrame(await Effect.runPromise(getControllers()));
        } else {
          setRestFrame(await Effect.runPromise(activatePreset(action.preset)));
        }
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
