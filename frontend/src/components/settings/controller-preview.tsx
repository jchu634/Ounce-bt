import ControllerColourPreview from "@/src/assets/controllers/ControllerColourPreview";
import type { ControllerColours } from "@/src/lib/controller-colours";

export function ControllerPreview({ colours }: { colours: ControllerColours }) {
  return (
    <ControllerColourPreview
      colours={colours}
      viewBox="5 12 54 39"
      role="img"
      aria-label={`Pro Controller preview. Main body ${colours.body}, buttons ${colours.buttons}, left grip ${colours.left_grip}, right grip ${colours.right_grip}.`}
      className="mx-auto h-full max-h-full w-full max-w-md"
    />
  );
}
