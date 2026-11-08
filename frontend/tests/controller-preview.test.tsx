import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ControllerPreview } from "../src/components/settings/controller-preview";
import { COLOUR_FIELDS, DEFAULT_CONTROLLER_COLOURS } from "../src/lib/controller-colours";

describe("controller preview", () => {
  it("renders every configured colour in its own SVG region", () => {
    const colours = {
      body: "#FF3344",
      buttons: "#2255AA",
      left_grip: "#22CC88",
      right_grip: "#FFCC11",
    };
    const markup = renderToStaticMarkup(<ControllerPreview colours={colours} />);
    for (const { key } of COLOUR_FIELDS) {
      expect(markup).toMatch(new RegExp(`data-region="${key}"[^>]*fill="${colours[key]}"`));
    }
  });

  it("keeps clip paths unique across preview instances", () => {
    const markup = renderToStaticMarkup(
      <>
        <ControllerPreview colours={DEFAULT_CONTROLLER_COLOURS} />
        <ControllerPreview colours={DEFAULT_CONTROLLER_COLOURS} />
      </>,
    );
    const ids = Array.from(markup.matchAll(/\bid="([^"]+)"/g), (match) => match[1]);
    expect(ids.length).toBe(2);
    expect(new Set(ids).size).toBe(ids.length);
    for (const match of markup.matchAll(/url\(#([^)]+)\)/g)) {
      expect(ids).toContain(match[1]);
    }
  });
});
