import {
  BUTTON_NAMES,
  MACRO_BUTTON_NAMES,
  type ButtonName,
  type MacroButtonName,
} from "@/src/lib/types";

export function parseButtonName(value: unknown): ButtonName | undefined {
  return BUTTON_NAMES.find((button) => button === value);
}

export function parseMacroButtonName(value: unknown): MacroButtonName | undefined {
  return MACRO_BUTTON_NAMES.find((button) => button === value);
}
