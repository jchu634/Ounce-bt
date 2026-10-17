import { useEffect, useRef, useState } from "react";
import * as Blockly from "blockly/core";
import * as English from "blockly/msg/en";
import type { MacroDoc } from "@/src/lib/types";
import { cn } from "cn";
import {
  MACRO_TOOLBOX,
  registerMacroBlocks,
} from "@/src/components/editors/blockly/macro-blocks";
import {
  loadMacroWorkspace,
  readMacroWorkspace,
} from "@/src/components/editors/blockly/macro-workspace";

const englishMessages: Record<string, string> = {};
for (const [key, value] of Object.entries(English)) {
  if (typeof value === "string") englishMessages[key] = value;
}
Blockly.setLocale(englishMessages);

const lightTheme = Blockly.Theme.defineTheme("macro-light", {
  name: "macro-light",
  base: Blockly.Themes.Classic,
  componentStyles: {
    workspaceBackgroundColour: "#ffffff",
    toolboxBackgroundColour: "#f5f5f5",
    toolboxForegroundColour: "#171717",
    flyoutBackgroundColour: "#fafafa",
    flyoutForegroundColour: "#171717",
    scrollbarColour: "#a3a3a3",
    insertionMarkerColour: "#e11d48",
    markerColour: "#e11d48",
    cursorColour: "#e11d48",
  },
  fontStyle: { family: "Scoutie Sans Variable, sans-serif" },
});

const darkTheme = Blockly.Theme.defineTheme("macro-dark", {
  name: "macro-dark",
  base: Blockly.Themes.Classic,
  componentStyles: {
    workspaceBackgroundColour: "#171717",
    toolboxBackgroundColour: "#262626",
    toolboxForegroundColour: "#fafafa",
    flyoutBackgroundColour: "#202020",
    flyoutForegroundColour: "#fafafa",
    scrollbarColour: "#737373",
    insertionMarkerColour: "#fb7185",
    markerColour: "#fb7185",
    cursorColour: "#fb7185",
  },
  fontStyle: { family: "Scoutie Sans Variable, sans-serif" },
});

export type MacroBlocklyEditorProps = {
  document: MacroDoc;
  onChange: (document: MacroDoc) => void;
  onDirty: () => void;
  onValidityChange: (valid: boolean) => void;
  className?: string;
};

export function MacroBlocklyEditor({
  document,
  onChange,
  onDirty,
  onValidityChange,
  className,
}: MacroBlocklyEditorProps) {
  const container = useRef<HTMLDivElement | null>(null);
  const callbacks = useRef({ onChange, onDirty, onValidityChange });
  const [issue, setIssue] = useState<string | null>(null);

  useEffect(() => {
    callbacks.current = { onChange, onDirty, onValidityChange };
  }, [onChange, onDirty, onValidityChange]);

  useEffect(() => {
    const element = container.current;
    if (element === null) return;

    registerMacroBlocks();
    const workspace = Blockly.inject(element, {
      toolbox: MACRO_TOOLBOX,
      theme: globalThis.document.documentElement.classList.contains("dark")
        ? darkTheme
        : lightTheme,
      renderer: "zelos",
      trashcan: true,
      sounds: false,
      move: { scrollbars: true, drag: true, wheel: true },
      zoom: {
        controls: true,
        wheel: true,
        pinch: true,
        startScale: 0.9,
        minScale: 0.5,
        maxScale: 1.5,
      },
    });
    loadMacroWorkspace({ workspace, document });
    workspace.clearUndo();

    const publish = () => {
      const result = readMacroWorkspace({
        workspace,
        name: document.name,
      });
      if (result.kind === "valid") {
        setIssue(null);
        callbacks.current.onValidityChange(true);
        callbacks.current.onChange(result.document);
        return;
      }
      const message =
        result.issues[0]?.message ?? "The block workspace is invalid.";
      setIssue(message);
      callbacks.current.onValidityChange(false);
    };
    const changeListener = (event: Blockly.Events.Abstract) => {
      if (event.isUiEvent) return;
      callbacks.current.onDirty();
      publish();
    };
    workspace.addChangeListener(changeListener);

    const resizeObserver = new ResizeObserver(() =>
      Blockly.svgResize(workspace),
    );
    resizeObserver.observe(element);

    const syncTheme = () => {
      workspace.setTheme(
        globalThis.document.documentElement.classList.contains("dark")
          ? darkTheme
          : lightTheme,
      );
    };
    const themeObserver = new MutationObserver(syncTheme);
    themeObserver.observe(globalThis.document.documentElement, {
      attributes: true,
      attributeFilter: ["class"],
    });

    return () => {
      resizeObserver.disconnect();
      themeObserver.disconnect();
      workspace.removeChangeListener(changeListener);
      workspace.dispose();
    };
  }, [document]);

  return (
    <div className="flex flex-col gap-2">
      <div
        ref={container}
        aria-label="Visual macro workspace"
        className={cn(
          "h-[60vh] min-h-128 w-full overflow-hidden rounded-xl border border-border",
          className,
        )}
      />
      {issue !== null && (
        <p role="alert" className="text-sm text-destructive">
          {issue}
        </p>
      )}
    </div>
  );
}
