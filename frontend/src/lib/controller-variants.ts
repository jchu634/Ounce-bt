export type ControllerVariant = "pro" | "joycon_l" | "joycon_r" | "combined";
export type BluetoothControllerType = Exclude<ControllerVariant, "combined">;
export type JoyConSide = Exclude<BluetoothControllerType, "pro">;
export const CONTROLLER_VARIANTS = [
  "pro",
  "joycon_l",
  "joycon_r",
  "combined",
] satisfies ControllerVariant[];

export const CONTROLLER_VARIANT_NAMES: Record<ControllerVariant, string> = {
  pro: "Pro Controller",
  joycon_l: "Joy-Con L",
  joycon_r: "Joy-Con R",
  combined: "Joycons",
};

export function isBluetoothControllerType(value: unknown): value is BluetoothControllerType {
  return value === "pro" || value === "joycon_l" || value === "joycon_r";
}
export const JOYCON_BUTTONS: Record<JoyConSide, readonly ButtonName[]> = {
  joycon_l: ["UP", "RIGHT", "DOWN", "LEFT", "MINUS", "CAPTURE", "STICK_L", "L", "ZL", "SL", "SR"],
  joycon_r: ["A", "B", "X", "Y", "PLUS", "HOME", "STICK_R", "R", "ZR", "SL", "SR"],
};
import type { ButtonName } from "./types";
