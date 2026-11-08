export type ControllerColours = {
  body: string;
  buttons: string;
  left_grip: string;
  right_grip: string;
};

export const DEFAULT_CONTROLLER_COLOURS: ControllerColours = {
  body: "#000000",
  buttons: "#0F0F0F",
  left_grip: "#828282",
  right_grip: "#828282",
};

export const COLOUR_FIELDS = [
  { key: "body", label: "Main body" },
  { key: "buttons", label: "Buttons" },
  { key: "left_grip", label: "Left grip" },
  { key: "right_grip", label: "Right grip" },
] satisfies { key: keyof ControllerColours; label: string }[];

export const FIXED_COLOURS = ["#000000", "#828282"];
export const INITIAL_RECENT_COLOURS = ["#0355A8", "#AE2121", "#2915EC"];
export const RECENT_COLOURS_STORAGE_KEY = "controller-recent-colours-by-part";
export type ControllerColourHistory = Record<keyof ControllerColours, string[]>;

export function parseControllerColourHistory(value: unknown): ControllerColourHistory {
  const source = typeof value === "object" && value !== null ? value : {};
  return {
    body: recentControllerColours("body" in source ? source.body : null),
    buttons: recentControllerColours("buttons" in source ? source.buttons : null),
    left_grip: recentControllerColours("left_grip" in source ? source.left_grip : null),
    right_grip: recentControllerColours("right_grip" in source ? source.right_grip : null),
  };
}

export function recordSavedControllerColours(
  history: ControllerColourHistory,
  previous: ControllerColours,
  saved: ControllerColours,
): ControllerColourHistory {
  const updated = { ...history };
  for (const { key } of COLOUR_FIELDS) {
    if (expandHexColour(previous[key]) !== expandHexColour(saved[key])) {
      updated[key] = recentControllerColours([saved[key], ...history[key]]);
    }
  }
  return updated;
}

export function recentControllerColours(values: unknown): string[] {
  const recent: string[] = [];
  const candidates = Array.isArray(values) ? values : [];
  for (const value of [...candidates, ...INITIAL_RECENT_COLOURS]) {
    if (typeof value !== "string" || !/^#[0-9a-f]{3}([0-9a-f]{3})?$/i.test(value)) continue;
    const colour = expandHexColour(value);
    if (!FIXED_COLOURS.includes(colour) && !recent.includes(colour)) recent.push(colour);
    if (recent.length === 3) break;
  }
  return recent;
}

export function parseControllerColours(value: unknown): ControllerColours {
  if (
    typeof value !== "object" ||
    value === null ||
    !("body" in value) ||
    !("buttons" in value) ||
    !("left_grip" in value) ||
    !("right_grip" in value)
  )
    throw new Error("Invalid controller colours from the backend.");

  function colour(value: unknown): string {
    if (typeof value !== "string" || !/^#[0-9a-f]{6}$/i.test(value))
      throw new Error("Invalid controller colour from the backend.");
    return value.toUpperCase();
  }
  return {
    body: colour(value.body),
    buttons: colour(value.buttons),
    left_grip: colour(value.left_grip),
    right_grip: colour(value.right_grip),
  };
}

export function sameColours(a: ControllerColours, b: ControllerColours): boolean {
  return COLOUR_FIELDS.every(({ key }) => expandHexColour(a[key]) === expandHexColour(b[key]));
}

export function expandHexColour(colour: string): string {
  if (/^#[0-9a-f]{3}$/i.test(colour))
    return (
      "#" +
      Array.from(colour.slice(1), (digit) => digit + digit)
        .join("")
        .toUpperCase()
    );
  if (/^#[0-9a-f]{6}$/i.test(colour)) return colour.toUpperCase();
  throw new Error("Enter a colour in #RRGGBB format.");
}
