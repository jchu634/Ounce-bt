import type { ComponentType, SVGProps } from "react";
import PlayStation5Controller from "@/src/assets/controllers/PlayStation5Controller";
import SwitchProController from "@/src/assets/controllers/SwitchProController";
import XboxSeriesController from "@/src/assets/controllers/XboxSeriesController";
import { ControllerSteam } from "@/src/assets/input-prompts/steam-controller";
import { ControllerSteamdeck } from "@/src/assets/input-prompts/steam-deck";

export const GAMEPAD_BUTTON_INPUTS = [
  "south",
  "east",
  "west",
  "north",
  "left_shoulder",
  "right_shoulder",
  "back",
  "start",
  "left_stick",
  "right_stick",
  "guide",
  "misc1",
  "touchpad",
  "dpad_up",
  "dpad_down",
  "dpad_left",
  "dpad_right",
  "left_paddle1",
  "right_paddle1",
  "left_paddle2",
  "right_paddle2",
] as const;

export const GAMEPAD_TRIGGER_INPUTS = [
  "left_trigger",
  "right_trigger",
] as const;

export type GamepadButtonInput = (typeof GAMEPAD_BUTTON_INPUTS)[number];
export type GamepadTriggerInput = (typeof GAMEPAD_TRIGGER_INPUTS)[number];

export type ControllerLayout =
  | "generic"
  | "switch"
  | "xbox"
  | "playstation"
  | "steam_controller"
  | "steam_deck";
export type ControllerLayoutDefinition = {
  value: ControllerLayout;
  label: string;
  image: ComponentType<SVGProps<SVGSVGElement>> | null;
  buttonNames: Partial<Record<GamepadButtonInput, string>>;
  triggerNames: Partial<Record<GamepadTriggerInput, string>>;
};

export const GENERIC_BUTTON_NAMES: Record<GamepadButtonInput, string> = {
  south: "South face",
  east: "East face",
  west: "West face",
  north: "North face",
  left_shoulder: "Left bumper",
  right_shoulder: "Right bumper",
  back: "Back / Select",
  start: "Start",
  left_stick: "Left stick click",
  right_stick: "Right stick click",
  guide: "Guide / Home",
  misc1: "Share / Capture",
  touchpad: "Touchpad",
  dpad_up: "D-pad up",
  dpad_down: "D-pad down",
  dpad_left: "D-pad left",
  dpad_right: "D-pad right",
  left_paddle1: "Left paddle 1",
  right_paddle1: "Right paddle 1",
  left_paddle2: "Left paddle 2",
  right_paddle2: "Right paddle 2",
};

export const GENERIC_TRIGGER_NAMES: Record<GamepadTriggerInput, string> = {
  left_trigger: "Left trigger",
  right_trigger: "Right trigger",
};

export const GENERIC_CONTROLLER_LAYOUT: ControllerLayoutDefinition = {
  value: "generic",
  label: "Generic controller",
  image: null,
  buttonNames: GENERIC_BUTTON_NAMES,
  triggerNames: GENERIC_TRIGGER_NAMES,
};

export const CONTROLLER_LAYOUTS: readonly ControllerLayoutDefinition[] = [
  GENERIC_CONTROLLER_LAYOUT,
  {
    value: "switch",
    label: "Switch",
    image: SwitchProController,
    buttonNames: {
      south: "B",
      east: "A",
      west: "Y",
      north: "X",
      back: "Minus",
      guide: "Home",
      start: "Plus",
      left_stick: "Left stick click",
      right_stick: "Right stick click",
      left_shoulder: "L",
      right_shoulder: "R",
      dpad_up: "D-pad up",
      dpad_down: "D-pad down",
      dpad_left: "D-pad left",
      dpad_right: "D-pad right",
      misc1: "Capture",
      left_paddle1: "GL",
      right_paddle1: "GR",
    },
    triggerNames: {
      left_trigger: "ZL",
      right_trigger: "ZR",
    },
  },
  {
    value: "xbox",
    label: "Xbox",
    image: XboxSeriesController,
    buttonNames: {
      south: "A",
      east: "B",
      west: "X",
      north: "Y",
      left_shoulder: "Left bumper",
      right_shoulder: "Right bumper",
      back: "View",
      start: "Menu",
      left_stick: "Left stick click",
      right_stick: "Right stick click",
      guide: "Xbox",
      misc1: "Share",
      dpad_up: "D-pad up",
      dpad_down: "D-pad down",
      dpad_left: "D-pad left",
      dpad_right: "D-pad right",
    },
    triggerNames: {
      left_trigger: "Left trigger",
      right_trigger: "Right trigger",
    },
  },
  {
    value: "playstation",
    label: "PlayStation",
    image: PlayStation5Controller,
    buttonNames: {
      south: "Cross",
      east: "Circle",
      west: "Square",
      north: "Triangle",
      back: "Create",
      guide: "PS",
      start: "Options",
      left_stick: "L3",
      right_stick: "R3",
      left_shoulder: "L1",
      right_shoulder: "R1",
      dpad_up: "D-pad up",
      dpad_down: "D-pad down",
      dpad_left: "D-pad left",
      dpad_right: "D-pad right",
      touchpad: "Touchpad",
      misc1: "Mute",
    },
    triggerNames: {
      left_trigger: "L2",
      right_trigger: "R2",
    },
  },
  {
    value: "steam_controller",
    label: "Steam Controller",
    image: ControllerSteam,
    buttonNames: {
      south: "A",
      east: "B",
      west: "X",
      north: "Y",
      left_shoulder: "LB",
      right_shoulder: "RB",
      back: "Back",
      start: "Start",
      left_stick: "Left stick click",
      right_stick: "Right pad click",
      guide: "Steam",
      dpad_up: "Left pad up",
      dpad_down: "Left pad down",
      dpad_left: "Left pad left",
      dpad_right: "Left pad right",
      left_paddle1: "Left grip",
      right_paddle1: "Right grip",
    },
    triggerNames: {
      left_trigger: "LT",
      right_trigger: "RT",
    },
  },
  {
    value: "steam_deck",
    label: "Steam Deck",
    image: ControllerSteamdeck,
    buttonNames: {
      south: "A",
      east: "B",
      west: "X",
      north: "Y",
      left_shoulder: "L1",
      right_shoulder: "R1",
      back: "View",
      start: "Menu",
      left_stick: "L3",
      right_stick: "R3",
      guide: "Steam",
      misc1: "Quick Access",
      dpad_up: "D-pad up",
      dpad_down: "D-pad down",
      dpad_left: "D-pad left",
      dpad_right: "D-pad right",
      left_paddle1: "L4",
      right_paddle1: "R4",
      left_paddle2: "L5",
      right_paddle2: "R5",
    },
    triggerNames: {
      left_trigger: "L2",
      right_trigger: "R2",
    },
  },
];
