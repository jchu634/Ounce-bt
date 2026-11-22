import ColourPreviewController from "@/src/assets/controllers/ColourPreviewController";
import { JoyCon, JoyConPair } from "@/src/assets/controllers/JoyCon";
import {
  ControllerSwitchPro,
  SwitchJoycon,
  SwitchJoyconLeft,
  SwitchJoyconRight,
} from "@/src/assets/input-prompts/switch";
import { controllerColourDefaults, type ControllerColours } from "@/src/lib/controller-colours";
import {
  CONTROLLER_VARIANT_NAMES,
  type ControllerVariant,
  type JoyConSide,
} from "@/src/lib/controller-variants";

export function ControllerVariantIcon({ variant }: { variant: ControllerVariant }) {
  switch (variant) {
    case "pro": return <ControllerSwitchPro aria-hidden="true" className="size-5" />;
    case "joycon_l": return <SwitchJoyconLeft aria-hidden="true" className="size-5 -rotate-90" />;
    case "joycon_r": return <SwitchJoyconRight aria-hidden="true" className="size-5 -rotate-90" />;
    case "combined": return <SwitchJoycon aria-hidden="true" className="size-5" />;
  }
}

export function ControllerPreview({
  colours,
  variant = "pro",
  upright = false,
  activeSide,
}: {
  colours?: ControllerColours;
  variant?: ControllerVariant;
  upright?: boolean;
  activeSide?: JoyConSide;
}) {
  const className = "mx-auto size-full max-w-md";
  if (variant === "combined") {
    return (
      <JoyConPair
        left={activeSide === "joycon_l" ? colours : undefined}
        right={activeSide === "joycon_r" ? colours : undefined}
        activeSide={activeSide}
        role="img"
        aria-label={
          activeSide
            ? `${CONTROLLER_VARIANT_NAMES[activeSide]} combined preview`
            : "Joycons preview"
        }
        className={className}
      />
    );
  }
  const palette = colours ?? controllerColourDefaults(variant);
  if (variant !== "pro") {
    return (
      <JoyCon
        side={variant}
        upright={upright}
        colours={palette}
        role="img"
        aria-label={`${CONTROLLER_VARIANT_NAMES[variant]} preview. Main body ${palette.body}, buttons ${palette.buttons}.`}
        className={className}
      />
    );
  }
  return (
    <ColourPreviewController
      colours={palette}
      viewBox="5 12 54 39"
      role="img"
      aria-label={`Pro Controller preview. Main body ${palette.body}, buttons ${palette.buttons}, left grip ${palette.left_grip}, right grip ${palette.right_grip}.`}
      className={className}
    />
  );
}
