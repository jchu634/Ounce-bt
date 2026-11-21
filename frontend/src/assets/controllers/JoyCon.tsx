import type { SVGProps } from "react";
import { joyConLeftPaths, joyConRightPaths } from "@/src/assets/input-prompts/switch/joycon-paths";
import { controllerColourDefaults, type JoyConColours } from "@/src/lib/controller-colours";
import type { JoyConSide } from "@/src/lib/controller-variants";

function JoyConParts({ side, colours }: { side: JoyConSide; colours: JoyConColours }) {
  const paths = side === "joycon_l" ? joyConLeftPaths : joyConRightPaths;
  return (
    <>
      <path data-region="body" fill={colours.body} d={paths.body} />
      <path data-region="buttons" fill={colours.buttons} d={paths.buttons} />
    </>
  );
}

type JoyConProps = SVGProps<SVGSVGElement> & {
  side: JoyConSide;
  colours?: JoyConColours;
  upright?: boolean;
};

export function JoyCon({
  side,
  colours = controllerColourDefaults(side),
  upright = false,
  ...props
}: JoyConProps) {
  return (
    <svg viewBox={upright ? "19 6 26 52" : "6 19 52 26"} {...props}>
      <g
        transform={
          upright ? undefined : "rotate(-90 32 32)"
        }
      >
        <JoyConParts side={side} colours={colours} />
      </g>
    </svg>
  );
}

type JoyConPairProps = SVGProps<SVGSVGElement> & {
  left?: JoyConColours;
  right?: JoyConColours;
};

export function JoyConPair({
  left = controllerColourDefaults("joycon_l"),
  right = controllerColourDefaults("joycon_r"),
  ...props
}: JoyConPairProps) {
  return (
    <svg viewBox="6 6 52 52" {...props}>
      <g transform="translate(-13 0)">
        <JoyConParts side="joycon_l" colours={left} />
      </g>
      <g transform="translate(13 0)">
        <JoyConParts side="joycon_r" colours={right} />
      </g>
    </svg>
  );
}
