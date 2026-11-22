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
  activeSide?: JoyConSide;
};

const INACTIVE_JOYCON_COLOURS: JoyConColours = {
  body: "#71717A",
  buttons: "#27272A",
};

export function JoyConPair({
  left = controllerColourDefaults("joycon_l"),
  right = controllerColourDefaults("joycon_r"),
  activeSide,
  ...props
}: JoyConPairProps) {
  const leftInactive = activeSide === "joycon_r";
  const rightInactive = activeSide === "joycon_l";
  return (
    <svg viewBox="6 6 52 52" {...props}>
      <g
        transform="translate(-13 0)"
        opacity={leftInactive ? 0.35 : undefined}
        data-side="joycon_l"
        data-inactive={leftInactive || undefined}
      >
        <JoyConParts side="joycon_l" colours={leftInactive ? INACTIVE_JOYCON_COLOURS : left} />
      </g>
      <g
        transform="translate(13 0)"
        opacity={rightInactive ? 0.35 : undefined}
        data-side="joycon_r"
        data-inactive={rightInactive || undefined}
      >
        <JoyConParts side="joycon_r" colours={rightInactive ? INACTIVE_JOYCON_COLOURS : right} />
      </g>
    </svg>
  );
}
