import ColourPreviewController from "@/src/assets/controllers/ColourPreviewController";
import {
  ControllerSwitchPro,
  SwitchJoycon,
  SwitchJoyconLeft,
  SwitchJoyconRight,
} from "@/src/assets/input-prompts/switch";
import { type ControllerColours } from "@/src/lib/controller-colours";
import { type ControllerVariant } from "@/src/lib/controller-variants";

export function ControllerVariantIcon({ variant }: { variant: ControllerVariant }) {
  switch (variant) {
    case "pro": return <ControllerSwitchPro aria-hidden="true" className="size-5" />;
    case "joycon_l": return <SwitchJoyconLeft aria-hidden="true" className="size-5 -rotate-90" />;
    case "joycon_r": return <SwitchJoyconRight aria-hidden="true" className="size-5 -rotate-90" />;
    case "combined": return <SwitchJoycon aria-hidden="true" className="size-5" />;
  }
}

export function ControllerPreview({ colours }: { colours: ControllerColours }) {
  return (
    <ColourPreviewController
      colours={colours}
      viewBox="5 12 54 39"
      role="img"
      aria-label={`Pro Controller preview. Main body ${colours.body}, buttons ${colours.buttons}, left grip ${colours.left_grip}, right grip ${colours.right_grip}.`}
      className="mx-auto size-full max-w-md"
    />
  );
}
