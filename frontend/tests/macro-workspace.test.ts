import { afterEach, describe, expect, it } from "vitest";
import * as Blockly from "blockly/core";
import { formatMacroDocument, parseVisualMacroDocument } from "@/src/lib/macro-document";
import type { MacroAction, MacroDoc } from "@/src/lib/types";
import {
  MACRO_BLOCK_TYPES,
  registerMacroBlocks,
} from "@/src/components/editors/blockly/macro-blocks";
import {
  loadMacroWorkspace,
  readMacroWorkspace,
} from "@/src/components/editors/blockly/macro-workspace";

const workspaces: Blockly.Workspace[] = [];

function createWorkspace(): Blockly.Workspace {
  registerMacroBlocks();
  const workspace = new Blockly.Workspace();
  workspaces.push(workspace);
  return workspace;
}

afterEach(() => {
  for (const workspace of workspaces.splice(0)) workspace.dispose();
});

describe("macro workspace conversion", () => {
  it.each([
    { unit: "ms", duration: 125.5, ms: 125.5 },
    { unit: "seconds", duration: 1.5, ms: 1500 },
    { unit: "seconds", duration: 0.05, ms: 50 },
    { unit: "seconds", duration: 0, ms: 0 },
  ])("stores $duration $unit as $ms ms for waits and holds", ({ unit, duration, ms }) => {
    const workspace = createWorkspace();
    loadMacroWorkspace({
      workspace,
      document: {
        version: 1,
        actions: [
          { do: "wait", ms: 50 },
          {
            do: "loop",
            count: 1,
            actions: [
              { do: "press", button: "A" },
              { do: "wait", ms: 50 },
              { do: "release", button: "A" },
            ],
          },
        ],
      },
    });
    for (const type of [MACRO_BLOCK_TYPES.wait, MACRO_BLOCK_TYPES.pressAndHold]) {
      const block = workspace.getBlocksByType(type, false)[0];
      if (!block) throw new Error("Missing duration block");
      expect(block.getFieldValue("UNIT")).toBe("ms");
      block.setFieldValue(duration, "MS");
      block.setFieldValue(unit, "UNIT");
    }

    const result = readMacroWorkspace({ workspace, name: undefined });
    expect(result).toMatchObject({
      kind: "valid",
      document: {
        actions: [
          { do: "wait", ms, unit },
          {
            do: "loop",
            count: 1,
            actions: [
              { do: "press", button: "A" },
              { do: "wait", ms, unit },
              { do: "release", button: "A" },
            ],
          },
        ],
      },
    });
    if (result.kind !== "valid") throw new Error("Expected valid durations");
    const parsed = parseVisualMacroDocument(formatMacroDocument(result.document));
    if (parsed.kind !== "valid") throw new Error("Expected saved unit metadata to parse");
    loadMacroWorkspace({ workspace, document: parsed.document });
    expect(readMacroWorkspace({ workspace, name: undefined })).toMatchObject({
      kind: "valid",
      document: result.document,
    });
    for (const type of [MACRO_BLOCK_TYPES.wait, MACRO_BLOCK_TYPES.pressAndHold]) {
      const block = workspace.getBlocksByType(type, false)[0];
      expect(block?.getFieldValue("UNIT")).toBe(unit);
      expect(block?.getFieldValue("MS")).toBe(duration);
    }
  });

  it("rejects a seconds duration that overflows milliseconds", () => {
    const workspace = createWorkspace();
    loadMacroWorkspace({ workspace, document: { version: 1, actions: [{ do: "wait", ms: 50 }] } });
    const block = workspace.getBlocksByType(MACRO_BLOCK_TYPES.wait, false)[0];
    if (!block) throw new Error("Missing wait block");
    block.setFieldValue(Number.MAX_VALUE, "MS");
    block.setFieldValue("seconds", "UNIT");

    expect(readMacroWorkspace({ workspace, name: undefined })).toMatchObject({
      kind: "invalid",
      issues: [{ message: "Wait duration in milliseconds must be finite." }],
    });
  });

  it("saves and reloads press and hold with its button and duration", () => {
    const workspace = createWorkspace();
    loadMacroWorkspace({ workspace, document: { version: 1, actions: [] } });
    const root = workspace.getTopBlocks(false)[0];
    const hold = workspace.newBlock(MACRO_BLOCK_TYPES.pressAndHold);
    hold.initModel();
    hold.setFieldValue("B", "BUTTON");
    hold.setFieldValue(125.5, "MS");
    const connection = root?.getInput("ACTIONS")?.connection;
    if (!connection || !hold.previousConnection) throw new Error("Missing action connection");
    connection.connect(hold.previousConnection);

    const result = readMacroWorkspace({ workspace, name: "hold-b" });
    expect(result).toMatchObject({
      kind: "valid",
      document: {
        version: 1,
        name: "hold-b",
        actions: [
          {
            do: "loop",
            count: 1,
            actions: [
              { do: "press", button: "B" },
              { do: "wait", ms: 125.5 },
              { do: "release", button: "B" },
            ],
          },
        ],
      },
    });
    if (result.kind !== "valid") throw new Error("Expected a valid hold block");

    loadMacroWorkspace({ workspace, document: result.document });
    const restored = workspace.getBlocksByType(MACRO_BLOCK_TYPES.pressAndHold, false);
    expect(restored).toHaveLength(1);
    expect(restored[0]?.getFieldValue("BUTTON")).toBe("B");
    expect(restored[0]?.getFieldValue("MS")).toBe(125.5);
    expect(readMacroWorkspace({ workspace, name: "hold-b" })).toMatchObject({
      kind: "valid",
      document: result.document,
    });
  });

  it("keeps individual combo actions separate from nested hold blocks", () => {
    const workspace = createWorkspace();
    const document: MacroDoc = {
      version: 1,
      repeat: 1,
      actions: [
        { do: "press", button: "A" },
        { do: "wait", ms: 50 },
        { do: "release", button: "A" },
        { do: "press", button: "ZL" },
        {
          do: "loop",
          count: 2,
          actions: [
            {
              do: "loop",
              count: 1,
              actions: [
                { do: "press", button: "B" },
                { do: "wait", ms: 100 },
                { do: "release", button: "B" },
              ],
            },
            { do: "wait", ms: 50 },
          ],
        },
        { do: "release", button: "ZL" },
      ],
    };
    loadMacroWorkspace({ workspace, document });

    expect(workspace.getBlocksByType(MACRO_BLOCK_TYPES.button, false)).toHaveLength(4);
    expect(workspace.getBlocksByType(MACRO_BLOCK_TYPES.pressAndHold, false)).toHaveLength(1);
    const result = readMacroWorkspace({ workspace, name: undefined });
    expect(result).toMatchObject({ kind: "valid", document });
    if (result.kind !== "valid") throw new Error("Expected a valid combo");
    const hold = workspace.getBlocksByType(MACRO_BLOCK_TYPES.pressAndHold, false)[0];
    expect(result.pathsByBlockId.get(hold?.id ?? "")).toEqual(["actions", 4, "actions", 0]);
  });

  it("does not collapse groups that release a different button or repeat", () => {
    const workspace = createWorkspace();
    const actions: MacroAction[] = [
      { do: "press", button: "A" },
      { do: "wait", ms: 50 },
      { do: "release", button: "B" },
    ];
    const document: MacroDoc = {
      version: 1,
      repeat: 1,
      actions: [
        { do: "loop", count: 1, actions },
        { do: "loop", count: 2, actions: [...actions.slice(0, 2), { do: "release", button: "A" }] },
      ],
    };
    loadMacroWorkspace({ workspace, document });

    expect(workspace.getBlocksByType(MACRO_BLOCK_TYPES.pressAndHold, false)).toHaveLength(0);
    expect(readMacroWorkspace({ workspace, name: undefined })).toMatchObject({
      kind: "valid",
      document,
    });
  });

  it("round trips the complete macro document", () => {
    const document: MacroDoc = {
      version: 1,
      name: "combo",
      repeat: 0,
      actions: [
        { do: "press", button: "A" },
        { do: "wait", ms: 25.5 },
        { do: "stick", side: "left", x: -1, y: 0.75 },
        {
          do: "loop",
          count: 2,
          actions: [{ do: "release", button: "A" }],
        },
      ],
    };
    const workspace = createWorkspace();

    loadMacroWorkspace({ workspace, document });
    const result = readMacroWorkspace({ workspace, name: document.name });

    expect(result).toMatchObject({ kind: "valid", document });
  });

  it("rejects a detached action block", () => {
    const workspace = createWorkspace();
    loadMacroWorkspace({ workspace, document: { version: 1, actions: [] } });
    const orphan = workspace.newBlock(MACRO_BLOCK_TYPES.wait);
    orphan.initModel();

    const result = readMacroWorkspace({ workspace, name: undefined });

    expect(result).toMatchObject({
      kind: "invalid",
      issues: [
        {
          blockId: orphan.id,
          message: "Connect this block to the macro before saving or running.",
        },
      ],
    });
  });

  it("rejects more than 16 nested loops", () => {
    let actions: MacroAction[] = [{ do: "wait", ms: 1 }];
    for (let count = 0; count < 17; count += 1) {
      actions = [{ do: "loop", count: 1, actions }];
    }
    const workspace = createWorkspace();
    loadMacroWorkspace({ workspace, document: { version: 1, actions } });

    const result = readMacroWorkspace({ workspace, name: undefined });

    expect(result.kind).toBe("invalid");
    if (result.kind === "invalid") {
      expect(result.issues[0]?.message).toContain("16 levels");
    }
  });

  it("counts hold groups toward the playback nesting limit", () => {
    let actions: MacroAction[] = [
      {
        do: "loop",
        count: 1,
        actions: [
          { do: "press", button: "A" },
          { do: "wait", ms: 50 },
          { do: "release", button: "A" },
        ],
      },
    ];
    for (let count = 0; count < 16; count += 1) {
      actions = [{ do: "loop", count: 2, actions }];
    }
    const workspace = createWorkspace();
    loadMacroWorkspace({ workspace, document: { version: 1, actions } });

    expect(readMacroWorkspace({ workspace, name: undefined })).toMatchObject({
      kind: "invalid",
      issues: [{ message: "Loops may be nested at most 16 levels deep." }],
    });
  });
});
