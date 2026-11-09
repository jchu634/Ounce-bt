import * as Blockly from "blockly/core";
import { BUTTON_NAMES } from "@/src/lib/types";

export const MACRO_BLOCK_TYPES = {
  root: "macro_root",
  button: "macro_button",
  pressAndHold: "macro_press_and_hold",
  wait: "macro_wait",
  stick: "macro_stick",
  loop: "macro_loop",
} as const;

const ACTION_CONNECTION = "MacroAction";

const durationUnitField = {
  type: "field_dropdown",
  name: "UNIT",
  options: [
    ["ms", "ms"],
    ["seconds", "seconds"],
  ],
};

const blockDefinitions = [
  {
    type: MACRO_BLOCK_TYPES.root,
    message0: "run macro %1 times (0 forever)",
    args0: [
      {
        type: "field_number",
        name: "REPEAT",
        value: 1,
        min: 0,
        precision: 1,
      },
    ],
    message1: "actions %1",
    args1: [
      {
        type: "input_statement",
        name: "ACTIONS",
        check: ACTION_CONNECTION,
      },
    ],
    colour: 345,
    tooltip: "The macro entry point and how many times to run the whole macro.",
  },
  {
    type: MACRO_BLOCK_TYPES.button,
    message0: "%1 button %2",
    args0: [
      {
        type: "field_dropdown",
        name: "OPERATION",
        options: [
          ["press", "press"],
          ["release", "release"],
        ],
      },
      {
        type: "field_dropdown",
        name: "BUTTON",
        options: BUTTON_NAMES.map((button) => [button, button]),
      },
    ],
    previousStatement: ACTION_CONNECTION,
    nextStatement: ACTION_CONNECTION,
    colour: 210,
    tooltip:
      "Press keeps a button held until a release action. Use separate actions for button combos.",
  },
  {
    type: MACRO_BLOCK_TYPES.pressAndHold,
    message0: "press and hold %1 for %2 %3",
    args0: [
      {
        type: "field_dropdown",
        name: "BUTTON",
        options: BUTTON_NAMES.map((button) => [button, button]),
      },
      { type: "field_number", name: "MS", value: 50, min: 0 },
      durationUnitField,
    ],
    previousStatement: ACTION_CONNECTION,
    nextStatement: ACTION_CONNECTION,
    colour: 210,
    tooltip: "Press a button, hold it for the duration, then release it.",
  },
  {
    type: MACRO_BLOCK_TYPES.wait,
    message0: "wait %1 %2",
    args0: [
      {
        type: "field_number",
        name: "MS",
        value: 50,
        min: 0,
      },
      durationUnitField,
    ],
    previousStatement: ACTION_CONNECTION,
    nextStatement: ACTION_CONNECTION,
    colour: 45,
    tooltip: "Wait before the next action.",
  },
  {
    type: MACRO_BLOCK_TYPES.stick,
    message0: "move %1 stick to x %2 y %3",
    args0: [
      {
        type: "field_dropdown",
        name: "SIDE",
        options: [
          ["left", "left"],
          ["right", "right"],
        ],
      },
      { type: "field_number", name: "X", value: 0 },
      { type: "field_number", name: "Y", value: 0 },
    ],
    previousStatement: ACTION_CONNECTION,
    nextStatement: ACTION_CONNECTION,
    colour: 120,
    tooltip: "Set one analog stick position. Values normally range from -1 to 1.",
  },
  {
    type: MACRO_BLOCK_TYPES.loop,
    message0: "repeat %1 times",
    args0: [
      {
        type: "field_number",
        name: "COUNT",
        value: 1,
        min: 0,
        precision: 1,
      },
    ],
    message1: "do %1",
    args1: [
      {
        type: "input_statement",
        name: "ACTIONS",
        check: ACTION_CONNECTION,
      },
    ],
    previousStatement: ACTION_CONNECTION,
    nextStatement: ACTION_CONNECTION,
    colour: 285,
    tooltip: "Repeat the enclosed actions.",
  },
];

export const MACRO_TOOLBOX: Blockly.utils.toolbox.ToolboxDefinition = {
  kind: "flyoutToolbox",
  contents: [
    { kind: "block", type: MACRO_BLOCK_TYPES.pressAndHold },
    { kind: "block", type: MACRO_BLOCK_TYPES.button },
    { kind: "block", type: MACRO_BLOCK_TYPES.wait },
    { kind: "block", type: MACRO_BLOCK_TYPES.stick },
    { kind: "block", type: MACRO_BLOCK_TYPES.loop },
  ],
};

export function registerMacroBlocks(): void {
  if (MACRO_BLOCK_TYPES.root in Blockly.Blocks) return;
  Blockly.common.defineBlocksWithJsonArray(blockDefinitions);
}
