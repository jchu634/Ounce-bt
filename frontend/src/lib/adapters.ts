import {
  isBluetoothControllerType,
  type BluetoothControllerType,
} from "./controller-variants";

export type Adapter = {
  id: string;
  transport: string;
  local_address: string | null;
  controller_id: number | null;
  error: string | null;
  preset: string | null;
  macro_mode: boolean;
  controller_type?: BluetoothControllerType;
  combined_with?: string | null;
};

type Controller = { id: number; name: string; guid: string };

export type AdapterInventory = {
  adapters: Adapter[];
  controllers: Controller[];
  controllers_available: boolean;
};

function isAdapter(value: unknown): value is Adapter {
  return (
    typeof value === "object" &&
    value !== null &&
    "id" in value &&
    typeof value.id === "string" &&
    "transport" in value &&
    typeof value.transport === "string" &&
    "local_address" in value &&
    (value.local_address === null || typeof value.local_address === "string") &&
    "controller_id" in value &&
    (value.controller_id === null ||
      (typeof value.controller_id === "number" && Number.isInteger(value.controller_id))) &&
    "error" in value &&
    (value.error === null || typeof value.error === "string") &&
    "preset" in value &&
    (value.preset === null || typeof value.preset === "string") &&
    "macro_mode" in value &&
    typeof value.macro_mode === "boolean" &&
    (!("controller_type" in value) || isBluetoothControllerType(value.controller_type)) &&
    (!("combined_with" in value) || value.combined_with === null || typeof value.combined_with === "string")
  );
}

function isController(value: unknown): value is Controller {
  return (
    typeof value === "object" &&
    value !== null &&
    "id" in value &&
    typeof value.id === "number" &&
    Number.isInteger(value.id) &&
    "name" in value &&
    typeof value.name === "string" &&
    "guid" in value &&
    typeof value.guid === "string"
  );
}

export type AdapterChange =
  | {
      kind: "assign";
      adapterId: string;
      controllerId: number | null;
    }
  | {
      kind: "preset";
      adapterId: string;
      preset: string;
    }
  | {
      kind: "type";
      adapterId: string;
      output: { controller_type: BluetoothControllerType } | {
        controller_type: "combined";
        companion_id: string;
      };
    };

async function readResponse(response: Response): Promise<unknown> {
  const body: unknown = await response.json();
  if (!response.ok) {
    throw new Error(
      typeof body === "object" && body !== null && "error" in body && typeof body.error === "string"
        ? body.error
        : `Adapter request failed (HTTP ${response.status})`,
    );
  }
  return body;
}

export async function requestAdapters(change?: AdapterChange): Promise<AdapterInventory> {
  let response: Response;
  if (change?.kind === "assign") {
    response = await fetch(`/api/adapters/${encodeURIComponent(change.adapterId)}/controller`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ controller_id: change.controllerId }),
      signal: AbortSignal.timeout(6000),
    });
  } else if (change?.kind === "preset") {
    response = await fetch(
      `/api/adapters/${encodeURIComponent(change.adapterId)}/preset/${encodeURIComponent(change.preset)}`,
      { method: "POST", signal: AbortSignal.timeout(6000) },
    );
  } else if (change?.kind === "type") {
    response = await fetch(`/api/adapters/${encodeURIComponent(change.adapterId)}/type`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(change.output),
      signal: AbortSignal.timeout(6000),
    });
  } else {
    response = await fetch("/api/adapters", {
      cache: "no-store",
      signal: AbortSignal.timeout(5000),
    });
  }
  const body = await readResponse(response);
  if (
    typeof body !== "object" ||
    body === null ||
    !("adapters" in body) ||
    !Array.isArray(body.adapters) ||
    !body.adapters.every(isAdapter) ||
    !("controllers" in body) ||
    !Array.isArray(body.controllers) ||
    !body.controllers.every(isController) ||
    !("controllers_available" in body) ||
    typeof body.controllers_available !== "boolean"
  )
    throw new Error("Invalid adapter inventory");
  return {
    adapters: body.adapters,
    controllers: body.controllers,
    controllers_available: body.controllers_available,
  };
}

export async function requestAdapterColours(
  adapterId: string,
  colours?: Record<string, string>,
  variant?: BluetoothControllerType,
) {
  const body = await readResponse(
    await fetch(
      `/api/adapters/${encodeURIComponent(adapterId)}/colours${variant ? `?controller_type=${variant}` : ""}`,
      colours
        ? {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(colours),
            signal: AbortSignal.timeout(5000),
          }
        : { cache: "no-store", signal: AbortSignal.timeout(5000) },
    ),
  );
  if (
    typeof body !== "object" ||
    body === null ||
    !("controller_colours" in body) ||
    !("colours_reconnect_required" in body) ||
    typeof body.colours_reconnect_required !== "boolean"
  )
    throw new Error("Invalid adapter colours");
  return { colours: body.controller_colours, reconnectRequired: body.colours_reconnect_required };
}
