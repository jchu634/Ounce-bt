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

  it.each([
    ["joycon_l", "rotate(-90 32 32)"],
    ["joycon_r", "rotate(-90 32 32)"],
  ] as const)("shows %s with the requested grip and colours", (variant, transform) => {
    const markup = renderToStaticMarkup(
      <ControllerPreview
        variant={variant}
        colours={{ ...DEFAULT_CONTROLLER_COLOURS, body: "#0044AA", buttons: "#B00BCA" }}
      />,
    );
    expect(markup).toContain(`transform="${transform}"`);
    expect(markup).toMatch(/data-region="body"[^>]*fill="#0044AA"/);
    expect(markup).toMatch(/data-region="buttons"[^>]*fill="#B00BCA"/);
    expect(markup).not.toContain("left_grip");
  });

  it("greys out the inactive side in combined Joy-Con preview", () => {
    const leftMarkup = renderToStaticMarkup(
      <ControllerPreview
        variant="combined"
        activeSide="joycon_l"
        colours={{ ...DEFAULT_CONTROLLER_COLOURS, body: "#00B9D6", buttons: "#001E1E" }}
      />,
    );
    expect(leftMarkup).toContain('data-side="joycon_l"');
    expect(leftMarkup).toContain('data-side="joycon_r" data-inactive="true"');
    expect(leftMarkup).toMatch(/data-region="body"[^>]*fill="#00B9D6"/);

    const rightMarkup = renderToStaticMarkup(
      <ControllerPreview
        variant="combined"
        activeSide="joycon_r"
        colours={{ ...DEFAULT_CONTROLLER_COLOURS, body: "#FF3C28", buttons: "#1E0A0A" }}
      />,
    );
    expect(rightMarkup).toContain('data-side="joycon_l" data-inactive="true"');
    expect(rightMarkup).toContain('data-side="joycon_r"');
    expect(rightMarkup).toMatch(/data-region="body"[^>]*fill="#FF3C28"/);
  });
});
