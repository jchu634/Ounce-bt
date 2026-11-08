import { describe, expect, it } from "vitest";
import {
  DEFAULT_CONTROLLER_COLOURS,
  expandHexColour,
  parseControllerColours,
  sameColours,
  recentControllerColours,
  parseControllerColourHistory,
  recordSavedControllerColours,
} from "../src/lib/controller-colours";

describe("controller colours", () => {
  it("records saved changes only in the matching part's history", () => {
    const history = parseControllerColourHistory({
      body: ["#112233", "#445566", "#778899"],
      left_grip: ["#ABCDEF", "#123456", "#654321"],
    });
    const updated = recordSavedControllerColours(history, DEFAULT_CONTROLLER_COLOURS, {
      ...DEFAULT_CONTROLLER_COLOURS,
      body: "#445566",
      right_grip: "#AABBCC",
    });
    expect(updated.body).toEqual(["#445566", "#112233", "#778899"]);
    expect(updated.right_grip).toEqual(["#AABBCC", "#0355A8", "#AE2121"]);
    expect(updated.left_grip).toEqual(history.left_grip);
    expect(updated.buttons).toEqual(history.buttons);
    expect(history.body).toEqual(["#112233", "#445566", "#778899"]);
  });

  it("restores each part's history independently and tolerates invalid storage", () => {
    const history = parseControllerColourHistory({ body: ["#abc"], buttons: false });
    expect(history.body).toEqual(["#AABBCC", "#0355A8", "#AE2121"]);
    expect(history.buttons).toEqual(["#0355A8", "#AE2121", "#2915EC"]);
    expect(parseControllerColourHistory(null)).toEqual(parseControllerColourHistory([]));
  });
  it("keeps three recent distinct custom colours without displacing black or grey", () => {
    expect(
      recentControllerColours([
        "#abc",
        "#000000",
        "#828282",
        "#AABBCC",
        "#123456",
        "#654321",
        "#ffffff",
      ]),
    ).toEqual(["#AABBCC", "#123456", "#654321"]);
    expect(recentControllerColours(["#654321", "#AABBCC", "#123456"])).toEqual([
      "#654321",
      "#AABBCC",
      "#123456",
    ]);
  });

  it("fills incomplete or corrupt history with premade colours", () => {
    expect(recentControllerColours(null)).toEqual(["#0355A8", "#AE2121", "#2915EC"]);
    expect(recentControllerColours([false, "red", "#123456"])).toEqual([
      "#123456",
      "#0355A8",
      "#AE2121",
    ]);
  });
  it("parses backend colours and normalizes picker hex input", () => {
    const colours = parseControllerColours({ ...DEFAULT_CONTROLLER_COLOURS, left_grip: "#aabbcc" });
    expect(colours.left_grip).toBe("#AABBCC");
    expect(expandHexColour("#abc")).toBe("#AABBCC");
    expect(expandHexColour("#ff0000")).toBe("#FF0000");
    expect(sameColours(colours, DEFAULT_CONTROLLER_COLOURS)).toBe(false);
    expect(sameColours({ ...colours, left_grip: "#abc" }, colours)).toBe(true);
  });

  it.each([
    null,
    [],
    {},
    { ...DEFAULT_CONTROLLER_COLOURS, body: "red" },
    { ...DEFAULT_CONTROLLER_COLOURS, left_grip: 123 },
  ])("rejects malformed backend palettes %j", (value) => {
    expect(() => parseControllerColours(value)).toThrow();
  });
});
