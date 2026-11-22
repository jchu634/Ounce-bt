export const BUTTON_NAMES = [
  "A",
  "B",
  "X",
  "Y",
  "L",
  "R",
  "ZL",
  "ZR",
  "UP",
  "DOWN",
  "LEFT",
  "RIGHT",
  "PLUS",
  "MINUS",
  "HOME",
  "CAPTURE",
  "STICK_L",
  "STICK_R",
  "SL",
  "SR",
] as const;

export type ButtonName = (typeof BUTTON_NAMES)[number];

export type EventAction =
  | { do: "press" | "release"; button: ButtonName }
  | { do: "stick"; side: "left" | "right"; x: number; y: number };

export type MacroAction =
  | { do: "press" | "release"; button: ButtonName }
  | { do: "wait"; ms: number; unit?: "ms" | "seconds" }
  | { do: "stick"; side: "left" | "right"; x: number; y: number }
  | { do: "loop"; count: number; actions: MacroAction[] };

export type MacroDoc = {
  version: 1;
  name?: string;
  repeat?: number;
  actions: MacroAction[];
};

export type MacroStatus = {
  name: string | null;
  state: "running" | "paused";
};

export type AdapterInputStatus = {
  mode: "manual" | "macro";
  macro: MacroStatus | null;
};

export type StatusFrame = AdapterInputStatus & {
  type: "status";
  adapter_id?: string;
  adapter_statuses?: Record<string, AdapterInputStatus>;
  has_joycons?: boolean;
};

export type ControllerInfo = {
  instance_id: number;
  guid: string;
  name: string;
  gamepad_type?: string;
  has_gyro?: boolean;
  has_accel?: boolean;
  has_rumble?: boolean;
};

export type ControllersFrame = {
  type: "controllers";
  controllers: ControllerInfo[];
  active: string | null;
  available: boolean;
  preset: string | null;
};

export type ErrorFrame = {
  type: "error";
  message: string;
  detail?: string;
  code?: "macro_capability";
};

export type ServerFrame = StatusFrame | ControllersFrame | ErrorFrame;

export type AdapterSelection =
  | { type: "select_adapter"; adapter_id: string }
  | { type: "select_adapters"; adapter_ids: string[] };

export type WsInbound =
  | AdapterSelection
  | {
      type: "state";
      buttons: ButtonName[];
      left: [number, number];
      right: [number, number];
    }
  | { type: "event"; action: EventAction }
  | { type: "macro"; op: "start"; macro: MacroDoc }
  | { type: "macro"; op: "start"; name: string }
  | { type: "macro"; op: "cancel" }
  | { type: "macro"; op: "pause" }
  | { type: "macro"; op: "resume" };

export type ConfigSnapshot = Record<string, unknown>;

export type PresetInfo = {
  filename: string;
  name: string;
  builtin: boolean;
  description: string;
  active: boolean;
};

/** 400 response body from PUT /api/macros|presets/{name}. */
export type ValidationBody = {
  error: string;
  detail?: string;
  /** 1-based syntax error location (invalid JSON). */
  line?: number;
  col?: number;
  /** JSON path of a semantic error (invalid macro/preset). */
  path?: (string | number)[];
};
