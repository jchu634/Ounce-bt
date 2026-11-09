import * as Blockly from "blockly/core";
import { BUTTON_NAMES, type ButtonName, type MacroAction, type MacroDoc } from "@/src/lib/types";
import { MACRO_VERSION, type MacroPath } from "@/src/lib/macro-document";
import {
  MACRO_BLOCK_TYPES,
  registerMacroBlocks,
} from "@/src/components/editors/blockly/macro-blocks";

export type WorkspaceIssue = {
  blockId: string | null;
  message: string;
};

export type WorkspaceReadResult =
  | {
      kind: "valid";
      document: MacroDoc;
      pathsByBlockId: ReadonlyMap<string, MacroPath>;
    }
  | { kind: "invalid"; issues: WorkspaceIssue[] };

type ReadContext = {
  pathsByBlockId: Map<string, MacroPath>;
  issues: WorkspaceIssue[];
};

function initializeBlock(block: Blockly.Block): void {
  if (block instanceof Blockly.BlockSvg) {
    block.initSvg();
    block.render();
    return;
  }
  block.initModel();
}

function newBlock(workspace: Blockly.Workspace, type: string): Blockly.Block {
  const block = workspace.newBlock(type);
  initializeBlock(block);
  return block;
}

function connectInput(parent: Blockly.Block, inputName: string, child: Blockly.Block): void {
  const parentConnection = parent.getInput(inputName)?.connection ?? null;
  const childConnection = child.previousConnection;
  if (parentConnection === null || childConnection === null) {
    throw new Error(`Cannot connect ${child.type} to ${parent.type}.${inputName}.`);
  }
  parentConnection.connect(childConnection);
}

function connectNext(previous: Blockly.Block, next: Blockly.Block): void {
  if (previous.nextConnection === null || next.previousConnection === null) {
    throw new Error(`Cannot connect ${previous.type} to ${next.type}.`);
  }
  previous.nextConnection.connect(next.previousConnection);
}

function loadDuration(block: Blockly.Block, wait: Extract<MacroAction, { do: "wait" }>): void {
  const unit = wait.unit ?? "ms";
  block.setFieldValue(unit, "UNIT");
  block.setFieldValue(unit === "seconds" ? wait.ms / 1000 : wait.ms, "MS");
}

function createActionBlock(workspace: Blockly.Workspace, action: MacroAction): Blockly.Block {
  switch (action.do) {
    case "press":
    case "release": {
      const block = newBlock(workspace, MACRO_BLOCK_TYPES.button);
      block.setFieldValue(action.do, "OPERATION");
      block.setFieldValue(action.button, "BUTTON");
      return block;
    }
    case "wait": {
      const block = newBlock(workspace, MACRO_BLOCK_TYPES.wait);
      loadDuration(block, action);
      return block;
    }
    case "stick": {
      const block = newBlock(workspace, MACRO_BLOCK_TYPES.stick);
      block.setFieldValue(action.side, "SIDE");
      block.setFieldValue(action.x, "X");
      block.setFieldValue(action.y, "Y");
      return block;
    }
    case "loop": {
      // A single-iteration group preserves the hold block in the existing macro format.
      const [press, wait, release] = action.actions;
      if (
        action.count === 1 &&
        action.actions.length === 3 &&
        press?.do === "press" &&
        wait?.do === "wait" &&
        release?.do === "release" &&
        press.button === release.button
      ) {
        const block = newBlock(workspace, MACRO_BLOCK_TYPES.pressAndHold);
        block.setFieldValue(press.button, "BUTTON");
        loadDuration(block, wait);
        return block;
      }
      const block = newBlock(workspace, MACRO_BLOCK_TYPES.loop);
      block.setFieldValue(action.count, "COUNT");
      const firstChild = createActionChain(workspace, action.actions);
      if (firstChild !== null) connectInput(block, "ACTIONS", firstChild);
      return block;
    }
    default: {
      const exhaustive: never = action;
      return exhaustive;
    }
  }
}

function createActionChain(
  workspace: Blockly.Workspace,
  actions: MacroAction[],
): Blockly.Block | null {
  let first: Blockly.Block | null = null;
  let previous: Blockly.Block | null = null;
  for (const action of actions) {
    const block = createActionBlock(workspace, action);
    if (first === null) first = block;
    if (previous !== null) connectNext(previous, block);
    previous = block;
  }
  return first;
}

export function loadMacroWorkspace({
  workspace,
  document,
}: {
  workspace: Blockly.Workspace;
  document: MacroDoc;
}): void {
  registerMacroBlocks();
  Blockly.Events.disable();
  try {
    workspace.clear();
    const root = newBlock(workspace, MACRO_BLOCK_TYPES.root);
    root.setDeletable(false);
    root.setMovable(false);
    root.setFieldValue(document.repeat ?? 1, "REPEAT");
    const firstAction = createActionChain(workspace, document.actions);
    if (firstAction !== null) connectInput(root, "ACTIONS", firstAction);
    if (root instanceof Blockly.BlockSvg) root.moveBy(32, 32);
  } finally {
    Blockly.Events.enable();
  }
}

function fieldValue(block: Blockly.Block, fieldName: string): unknown {
  const value: unknown = block.getFieldValue(fieldName);
  return value;
}

function numberField(
  block: Blockly.Block,
  fieldName: string,
  label: string,
  context: ReadContext,
  integer: boolean,
): number | null {
  const value = fieldValue(block, fieldName);
  const valid =
    typeof value === "number" &&
    Number.isFinite(value) &&
    value >= 0 &&
    (!integer || Number.isInteger(value));
  if (valid) return value;
  context.issues.push({
    blockId: block.id,
    message: `${label} must be a non-negative ${integer ? "integer" : "number"}.`,
  });
  return null;
}

function signedNumberField(
  block: Blockly.Block,
  fieldName: string,
  label: string,
  context: ReadContext,
): number | null {
  const value = fieldValue(block, fieldName);
  if (typeof value === "number" && Number.isFinite(value)) return value;
  context.issues.push({
    blockId: block.id,
    message: `${label} must be a finite number.`,
  });
  return null;
}

function durationField(
  block: Blockly.Block,
  label: string,
  context: ReadContext,
): Extract<MacroAction, { do: "wait" }> | null {
  const duration = numberField(block, "MS", label, context, false);
  const unit = fieldValue(block, "UNIT");
  if (unit !== "ms" && unit !== "seconds") {
    context.issues.push({ blockId: block.id, message: "Choose ms or seconds." });
    return null;
  }
  if (duration === null) return null;
  const ms = unit === "seconds" ? duration * 1000 : duration;
  if (!Number.isFinite(ms)) {
    context.issues.push({ blockId: block.id, message: `${label} in milliseconds must be finite.` });
    return null;
  }
  return { do: "wait", ms, unit };
}

function isButtonName(value: unknown): value is ButtonName {
  return typeof value === "string" && BUTTON_NAMES.some((buttonName) => buttonName === value);
}

function readAction(
  block: Blockly.Block,
  path: MacroPath,
  depth: number,
  context: ReadContext,
): MacroAction | null {
  context.pathsByBlockId.set(block.id, path);
  switch (block.type) {
    case MACRO_BLOCK_TYPES.button: {
      const operation = fieldValue(block, "OPERATION");
      const button = fieldValue(block, "BUTTON");
      if ((operation !== "press" && operation !== "release") || !isButtonName(button)) {
        context.issues.push({
          blockId: block.id,
          message: "Choose a valid button action.",
        });
        return null;
      }
      return { do: operation, button };
    }
    case MACRO_BLOCK_TYPES.wait: {
      return durationField(block, "Wait duration", context);
    }
    case MACRO_BLOCK_TYPES.pressAndHold: {
      if (depth >= 16) {
        context.issues.push({
          blockId: block.id,
          message: "Loops may be nested at most 16 levels deep.",
        });
        return null;
      }
      const button = fieldValue(block, "BUTTON");
      const wait = durationField(block, "Hold duration", context);
      if (!isButtonName(button)) {
        context.issues.push({ blockId: block.id, message: "Choose a valid button." });
        return null;
      }
      return wait === null
        ? null
        : {
            do: "loop",
            count: 1,
            actions: [{ do: "press", button }, wait, { do: "release", button }],
          };
    }
    case MACRO_BLOCK_TYPES.stick: {
      const side = fieldValue(block, "SIDE");
      const x = signedNumberField(block, "X", "Stick X", context);
      const y = signedNumberField(block, "Y", "Stick Y", context);
      if (side !== "left" && side !== "right") {
        context.issues.push({
          blockId: block.id,
          message: "Choose the left or right stick.",
        });
        return null;
      }
      return x === null || y === null ? null : { do: "stick", side, x, y };
    }
    case MACRO_BLOCK_TYPES.loop: {
      if (depth >= 16) {
        context.issues.push({
          blockId: block.id,
          message: "Loops may be nested at most 16 levels deep.",
        });
        return null;
      }
      const count = numberField(block, "COUNT", "Loop count", context, true);
      const actions = readActionChain(
        block.getInputTargetBlock("ACTIONS"),
        [...path, "actions"],
        depth + 1,
        context,
      );
      return count === null ? null : { do: "loop", count, actions };
    }
    default:
      context.issues.push({
        blockId: block.id,
        message: `Unsupported block type '${block.type}'.`,
      });
      return null;
  }
}

function readActionChain(
  first: Blockly.Block | null,
  path: MacroPath,
  depth: number,
  context: ReadContext,
): MacroAction[] {
  const actions: MacroAction[] = [];
  let block = first;
  let index = 0;
  while (block !== null) {
    const action = readAction(block, [...path, index], depth, context);
    if (action !== null) actions.push(action);
    block = block.getNextBlock();
    index += 1;
  }
  return actions;
}

function applyWarnings(workspace: Blockly.Workspace, issues: WorkspaceIssue[]): void {
  for (const block of workspace.getAllBlocks(false)) block.setWarningText(null);
  for (const issue of issues) {
    if (issue.blockId === null) continue;
    workspace.getBlockById(issue.blockId)?.setWarningText(issue.message);
  }
}

export function readMacroWorkspace({
  workspace,
  name,
}: {
  workspace: Blockly.Workspace;
  name: string | undefined;
}): WorkspaceReadResult {
  const context: ReadContext = {
    pathsByBlockId: new Map(),
    issues: [],
  };
  const topBlocks = workspace.getTopBlocks(false);
  const roots = topBlocks.filter((block) => block.type === MACRO_BLOCK_TYPES.root);
  if (roots.length !== 1) {
    context.issues.push({
      blockId: null,
      message: "The workspace must contain one macro root block.",
    });
  }
  for (const block of topBlocks) {
    if (block.type !== MACRO_BLOCK_TYPES.root) {
      context.issues.push({
        blockId: block.id,
        message: "Connect this block to the macro before saving or running.",
      });
    }
  }

  const root = roots[0];
  if (root === undefined) {
    applyWarnings(workspace, context.issues);
    return { kind: "invalid", issues: context.issues };
  }
  context.pathsByBlockId.set(root.id, []);
  const repeat = numberField(root, "REPEAT", "Macro repeat", context, true);
  const actions = readActionChain(root.getInputTargetBlock("ACTIONS"), ["actions"], 0, context);

  applyWarnings(workspace, context.issues);
  if (repeat === null || context.issues.length > 0) {
    return { kind: "invalid", issues: context.issues };
  }

  const document: MacroDoc = { version: MACRO_VERSION, repeat, actions };
  if (name !== undefined) document.name = name;
  return {
    kind: "valid",
    document,
    pathsByBlockId: context.pathsByBlockId,
  };
}
