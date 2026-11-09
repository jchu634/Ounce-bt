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
  "SR_R",
  "SL_R",
  "SR_L",
  "SL_L",
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

export type StatusFrame = {
  type: "status";
  mode: "manual" | "macro";
  macro: MacroStatus | null;
};

export type ControllerInfo = {
  guid: string;
  index: number;
  name: string;
  axes: number;
  buttons: number;
  hats: number;
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
};

export type ServerFrame = StatusFrame | ControllersFrame | ErrorFrame;

export type WsInbound =
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
