import { Data, Effect } from "effect";
import type {
  ConfigSnapshot,
  ControllerInfo,
  ControllersFrame,
  PresetInfo,
  ValidationBody,
} from "./types";

export class ApiError extends Data.TaggedError("ApiError")<{
  readonly status: number;
  readonly message: string;
  readonly body: ValidationBody | null;
}> {}

const isValidationBody = (body: unknown): body is ValidationBody =>
  typeof body === "object" &&
  body !== null &&
  !Array.isArray(body) &&
  "error" in body &&
  typeof body.error === "string";

const toApiError = (status: number, body: unknown): ApiError => {
  const parsed = isValidationBody(body) ? body : null;
  const message = parsed?.error ?? `request failed (${status})`;
  return new ApiError({ status, message, body: parsed });
};

const requestJson = <T>(path: string, init?: RequestInit): Effect.Effect<T, ApiError> =>
  Effect.gen(function* () {
    let response: Response;
    try {
      response = yield* Effect.promise(() =>
        fetch(path, {
          ...init,
          headers: {
            ...(init?.body ? { "Content-Type": "application/json" } : {}),
            ...init?.headers,
          },
        }),
      );
    } catch (cause) {
      return yield* new ApiError({
        status: 0,
        message: "could not reach the backend",
        body: { error: String(cause) },
      });
    }

    const text = yield* Effect.promise(() => response.text());
    let body: unknown = null;
    if (text) {
      try {
        body = JSON.parse(text);
      } catch {
        body = null;
      }
    }

    if (!response.ok) {
      return yield* toApiError(response.status, body);
    }
    return body as T;
  });

export const getConfig = () => requestJson<ConfigSnapshot>("/api/config");

export const patchConfig = (changes: ConfigSnapshot) =>
  requestJson<{
    changed: ConfigSnapshot;
    config: ConfigSnapshot;
    colours_reconnect_required: boolean;
  }>("/api/config", {
    method: "PATCH",
    body: JSON.stringify(changes),
  });

export const listMacros = () => requestJson<{ names: string[] }>("/api/macros");

export const getMacro = (name: string) =>
  requestJson<{ name: string; contents: string }>(`/api/macros/${encodeURIComponent(name)}`);

export const putMacro = (name: string, contents: string) =>
  requestJson<{ name: string; saved: boolean }>(`/api/macros/${encodeURIComponent(name)}`, {
    method: "PUT",
    body: JSON.stringify({ contents }),
  });

export const deleteMacro = (name: string) =>
  requestJson<{ name: string; deleted: boolean }>(`/api/macros/${encodeURIComponent(name)}`, {
    method: "DELETE",
  });

export const getControllers = () => requestJson<ControllersFrame>("/api/controllers");

export const selectController = (ident: string | number) =>
  requestJson<ControllersFrame & { applied?: string }>("/api/controllers/active", {
    method: "PUT",
    body: JSON.stringify(typeof ident === "number" ? { index: ident } : { guid: ident }),
  });

export type ControllerSelection = {
  controllers: ControllerInfo[];
  active: string | null;
};

export const listPresets = () =>
  requestJson<{ presets: PresetInfo[]; active: string }>("/api/presets");

export const getPreset = (name: string) =>
  requestJson<{ name: string; contents: string }>(`/api/presets/${encodeURIComponent(name)}`);

export const putPreset = (name: string, contents: string) =>
  requestJson<{ name: string; saved: boolean }>(`/api/presets/${encodeURIComponent(name)}`, {
    method: "PUT",
    body: JSON.stringify({ contents }),
  });

export const deletePreset = (name: string) =>
  requestJson<{ name: string; deleted: boolean }>(`/api/presets/${encodeURIComponent(name)}`, {
    method: "DELETE",
  });

export const activatePreset = (name: string) =>
  requestJson<ControllersFrame & { applied: string }>(
    `/api/presets/${encodeURIComponent(name)}/activate`,
    { method: "POST" },
  );

export const renameMacro = (name: string, newName: string) =>
  requestJson<{ name: string }>(`/api/macros/${encodeURIComponent(name)}`, {
    method: "PATCH",
    body: JSON.stringify({ name: newName }),
  });

export const getDebugStatus = () =>
  requestJson<
    {
      bd_address: string | null;
      bluetooth: { state: string; pairing: boolean };
      acl_connected: boolean;
      hid_control_ready: boolean;
      hid_interrupt_ready: boolean;
      switch_devices: { address: string; name: string }[];
      address_regeneration_available: boolean;
      restart_available: boolean;
    } & Record<string, unknown>
  >("/api/debug");

export type DebugChanges = {
  nolog: boolean;
  bumble_logging: boolean;
  ws_auth_required: boolean;
  macro_rate_hz: number;
  tick_rate_hz: number;
};

export const saveDebugAndRestart = (changes: DebugChanges, regenerateAddress: boolean) =>
  requestJson<{ restarting: boolean }>("/api/debug", {
    method: "POST",
    body: JSON.stringify({ changes, regenerate_address: regenerateAddress }),
  });
