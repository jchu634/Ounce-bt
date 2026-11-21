import type { ComponentType, SVGProps } from "react";
import PlayStation5Controller from "@/src/assets/controllers/PlayStation5Controller";
import SwitchProController from "@/src/assets/controllers/SwitchProController";
import XboxSeriesController from "@/src/assets/controllers/XboxSeriesController";

export type ControllerLayout = "generic" | "switch" | "xbox" | "playstation";
export type ControllerLayoutDefinition = {
  value: ControllerLayout;
  label: string;
  image: ComponentType<SVGProps<SVGSVGElement>> | null;
  buttonNames: readonly string[];
  axisNames: readonly string[];
};

export const GENERIC_CONTROLLER_LAYOUT: ControllerLayoutDefinition = {
  value: "generic",
  label: "Generic controller",
  image: null,
  buttonNames: [],
  axisNames: [],
};

export const CONTROLLER_LAYOUTS: readonly ControllerLayoutDefinition[] = [
  GENERIC_CONTROLLER_LAYOUT,
  {
    value: "switch",
    label: "Switch",
    image: SwitchProController,
    buttonNames: [
      "A",
      "B",
      "X",
      "Y",
      "Minus",
      "Home",
      "Plus",
      "Right stick click",
      "Left stick click",
      "L",
      "R",
      "D-pad up",
      "D-pad down",
      "D-pad left",
      "D-pad right",
      "Capture",
    ],
    axisNames: [
      "Left stick X",
      "Left stick Y",
      "Right stick X",
      "Right stick Y",
      "ZL",
      "ZR",
    ],
  },
  {
    value: "xbox",
    label: "Xbox",
    image: XboxSeriesController,
    buttonNames: [
      "A",
      "B",
      "X",
      "Y",
      "Left bumper",
      "Right bumper",
      "View",
      "Menu",
      "Left stick click",
      "Right stick click",
      "Xbox",
    ],
    axisNames: [
      "Left stick X",
      "Left stick Y",
      "Left trigger",
      "Right stick X",
      "Right stick Y",
      "Right trigger",
    ],
  },
  {
    value: "playstation",
    label: "PlayStation",
    image: PlayStation5Controller,
    buttonNames: [
      "Cross",
      "Circle",
      "Square",
      "Triangle",
      "Create",
      "PS",
      "Options",
      "L3",
      "R3",
      "L1",
      "R1",
      "D-pad up",
      "D-pad down",
      "D-pad left",
      "D-pad right",
      "Touch pad",
    ],
    axisNames: [
      "Left stick X",
      "Left stick Y",
      "Right stick X",
      "Right stick Y",
      "L2",
      "R2",
    ],
  },
];
