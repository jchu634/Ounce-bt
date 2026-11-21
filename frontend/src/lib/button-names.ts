import { BUTTON_NAMES, type ButtonName } from "@/src/lib/types";

export function parseButtonName(value: unknown): ButtonName | undefined {
  return BUTTON_NAMES.find((button) => button === value);
}
