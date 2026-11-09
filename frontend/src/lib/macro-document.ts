import { BUTTON_NAMES, type ButtonName, type MacroAction, type MacroDoc } from "@/src/lib/types";

export type MacroPath = (string | number)[];

export type MacroDocumentParseResult =
  | { kind: "valid"; document: MacroDoc }
  | { kind: "invalid-json"; error: SyntaxError }
  | { kind: "invalid-document"; message: string; path: MacroPath };

export type VisualMacroParseResult =
  | { kind: "valid"; document: MacroDoc }
  | Exclude<MacroDocumentParseResult, { kind: "valid" }>
  | { kind: "unsupported"; message: string; path: MacroPath };

export const MACRO_VERSION = 1;

const ROOT_KEYS = new Set(["version", "name", "repeat", "actions"]);
const ACTION_KEYS = {
  press: new Set(["do", "button"]),
  release: new Set(["do", "button"]),
  wait: new Set(["do", "ms", "unit"]),
  stick: new Set(["do", "side", "x", "y"]),
  loop: new Set(["do", "count", "actions"]),
} satisfies Record<MacroAction["do"], ReadonlySet<string>>;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isButtonName(value: unknown): value is ButtonName {
  return typeof value === "string" && BUTTON_NAMES.some((buttonName) => buttonName === value);
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function invalid(message: string, path: MacroPath): MacroDocumentParseResult {
  return { kind: "invalid-document", message, path };
}

function parseActions(
  value: unknown,
  path: MacroPath,
  depth: number,
): MacroAction[] | MacroDocumentParseResult {
  if (!Array.isArray(value)) return invalid("Actions must be a list.", path);
  if (depth > 16) {
    return invalid("Loops are nested too deeply. The maximum is 16.", path);
  }

  const actions: MacroAction[] = [];
  for (const [index, candidate] of value.entries()) {
    const actionPath = [...path, index];
    if (!isRecord(candidate)) {
      return invalid("Each action must be an object.", actionPath);
    }

    switch (candidate.do) {
      case "press":
      case "release":
        if (!isButtonName(candidate.button)) {
          return invalid(`Unknown button for '${candidate.do}'.`, [...actionPath, "button"]);
        }
        actions.push({ do: candidate.do, button: candidate.button });
        break;
      case "wait":
        if (!isFiniteNumber(candidate.ms) || candidate.ms < 0) {
          return invalid("Wait duration must be a non-negative number.", [...actionPath, "ms"]);
        }
        if (
          candidate.unit !== undefined &&
          candidate.unit !== "ms" &&
          candidate.unit !== "seconds"
        ) {
          return invalid("Wait unit must be 'ms' or 'seconds'.", [...actionPath, "unit"]);
        }
        actions.push(
          candidate.unit === undefined
            ? { do: "wait", ms: candidate.ms }
            : { do: "wait", ms: candidate.ms, unit: candidate.unit },
        );
        break;
      case "stick":
        if (candidate.side !== "left" && candidate.side !== "right") {
          return invalid("Stick side must be 'left' or 'right'.", [...actionPath, "side"]);
        }
        if (!isFiniteNumber(candidate.x)) {
          return invalid("Stick X must be a finite number.", [...actionPath, "x"]);
        }
        if (!isFiniteNumber(candidate.y)) {
          return invalid("Stick Y must be a finite number.", [...actionPath, "y"]);
        }
        actions.push({
          do: "stick",
          side: candidate.side,
          x: candidate.x,
          y: candidate.y,
        });
        break;
      case "loop": {
        if (
          typeof candidate.count !== "number" ||
          !Number.isInteger(candidate.count) ||
          candidate.count < 0
        ) {
          return invalid("Loop count must be a non-negative integer.", [...actionPath, "count"]);
        }
        const nested = parseActions(candidate.actions, [...actionPath, "actions"], depth + 1);
        if (!Array.isArray(nested)) return nested;
        actions.push({ do: "loop", count: candidate.count, actions: nested });
        break;
      }
      default:
        return invalid(
          "Unknown action. Expected press, release, wait, stick, or loop.",
          actionPath,
        );
    }
  }
  return actions;
}

function findUnknownKey(
  value: Record<string, unknown>,
  allowed: ReadonlySet<string>,
  path: MacroPath,
): MacroPath | null {
  const key = Object.keys(value).find((candidate) => !allowed.has(candidate));
  return key === undefined ? null : [...path, key];
}

function findUnsupportedActionKey(actions: unknown[], path: MacroPath): MacroPath | null {
  for (const [index, candidate] of actions.entries()) {
    if (!isRecord(candidate)) continue;
    const actionPath = [...path, index];
    const kind = candidate.do;
    if (
      kind !== "press" &&
      kind !== "release" &&
      kind !== "wait" &&
      kind !== "stick" &&
      kind !== "loop"
    ) {
      continue;
    }
    const unknown = findUnknownKey(candidate, ACTION_KEYS[kind], actionPath);
    if (unknown !== null) return unknown;
    if (kind === "loop" && Array.isArray(candidate.actions)) {
      const nested = findUnsupportedActionKey(candidate.actions, [...actionPath, "actions"]);
      if (nested !== null) return nested;
    }
  }
  return null;
}

export function parseMacroDocument(text: string): MacroDocumentParseResult {
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch (cause) {
    return {
      kind: "invalid-json",
      error: cause instanceof SyntaxError ? cause : new SyntaxError("The macro is not valid JSON."),
    };
  }

  if (!isRecord(value)) {
    return invalid("The macro must be an object.", []);
  }
  if (value.version !== MACRO_VERSION) {
    return invalid(`Macro version must be ${MACRO_VERSION}.`, ["version"]);
  }
  if (value.name !== undefined && typeof value.name !== "string") {
    return invalid("Macro name must be a string.", ["name"]);
  }
  if (
    value.repeat !== undefined &&
    (typeof value.repeat !== "number" || !Number.isInteger(value.repeat) || value.repeat < 0)
  ) {
    return invalid("Repeat must be a non-negative integer.", ["repeat"]);
  }

  const actions = parseActions(value.actions, ["actions"], 0);
  if (!Array.isArray(actions)) return actions;

  const document: MacroDoc = { version: MACRO_VERSION, actions };
  if (typeof value.name === "string") document.name = value.name;
  if (typeof value.repeat === "number") document.repeat = value.repeat;
  return { kind: "valid", document };
}

export function parseVisualMacroDocument(text: string): VisualMacroParseResult {
  const parsed = parseMacroDocument(text);
  if (parsed.kind !== "valid") return parsed;

  const raw: unknown = JSON.parse(text);
  if (!isRecord(raw)) return parsed;
  const rootUnknown = findUnknownKey(raw, ROOT_KEYS, []);
  const unsupported =
    rootUnknown ??
    (Array.isArray(raw.actions) ? findUnsupportedActionKey(raw.actions, ["actions"]) : null);
  if (unsupported === null) return parsed;

  return {
    kind: "unsupported",
    path: unsupported,
    message: `The visual editor cannot preserve '${unsupported.join(".")}'. Remove it in JSON mode before switching.`,
  };
}

export function formatMacroDocument(document: MacroDoc): string {
  return `${JSON.stringify(document, null, 2)}\n`;
}

export function createMacroDocument(name: string): string {
  return formatMacroDocument({ version: MACRO_VERSION, name, repeat: 1, actions: [] });
}
