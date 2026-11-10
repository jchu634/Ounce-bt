import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import { useBlocker } from "@tanstack/react-router";
import { Effect } from "effect";
import {
  ArrowCounterClockwiseIcon,
  CheckIcon,
  FloppyDiskIcon,
  MagicWandIcon,
  PauseIcon,
  PlayIcon,
  SpinnerGapIcon,
  StopIcon,
  TrashIcon,
  WarningIcon,
} from "@phosphor-icons/react";
import { Button } from "@/src/components/ui/button";
import { JsonExportButtons } from "@/src/components/editors/json-export-buttons";
import { Input } from "@/src/components/ui/input";
import { Tabs, TabsList, TabsTrigger } from "@/src/components/ui/tabs";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/src/components/ui/dialog";
import {
  JsonEditor,
  type JsonEditorHandle,
  type JsonMarker,
} from "@/src/components/editors/json-editor";
import { MacroBlocklyEditor } from "@/src/components/editors/blockly/macro-blockly-editor";
import { useMacroRunner } from "@/src/hooks/use-macro-runner";
import {
  deleteMacro,
  getMacro,
  listMacros,
  putMacro,
  renameMacro,
} from "@/src/lib/api";
import { ApiError } from "@/src/lib/api";
import type { MacroDoc, ValidationBody } from "@/src/lib/types";
import { locatePathLine, positionToLineCol } from "@/src/lib/json-locate";
import {
  formatMacroDocument,
  parseMacroDocument,
  parseVisualMacroDocument,
} from "@/src/lib/macro-document";

function parseErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return `${error.message}${error.body?.detail ? `: ${error.body.detail}` : ""}`;
  }
  return String(error);
}

export type MacroEditorProps = {
  name: string | null;
  onDeleted: (name: string) => void;
  onRenamed: (name: string) => void;
};

export type MacroEditorHandle = {
  requestNavigation: (navigate: () => void) => void;
};

type SaveResult = "saved" | "failed";
type EditorMode = "blocks" | "json";

export const MacroEditor = forwardRef<MacroEditorHandle, MacroEditorProps>(
  function MacroEditor({ name, onDeleted, onRenamed }, ref) {
    const [value, setValue] = useState("");

    const [initialName] = useState(name);
    const [newName, setNewName] = useState("");
    const [overwriteName, setOverwriteName] = useState<string | null>(null);
    const [renameOpen, setRenameOpen] = useState(false);
    const [renaming, setRenaming] = useState(false);
    const [renameError, setRenameError] = useState<string | null>(null);
    const documentKey = initialName;

    const [savedText, setSavedText] = useState<string | null>(null);
    const [loading, setLoading] = useState(initialName !== null);
    const [saving, setSaving] = useState(false);

    const [deleting, setDeleting] = useState(false);
    const [deletePromptOpen, setDeletePromptOpen] = useState(false);

    const [error, setError] = useState<string | null>(null);
    const [markers, setMarkers] = useState<JsonMarker[]>([]);

    const [editorMode, setEditorMode] = useState<EditorMode>("blocks");
    const [blockDocument, setBlockDocument] = useState<MacroDoc | null>(null);
    const [blockRevision, setBlockRevision] = useState(0);
    const [blockValid, setBlockValid] = useState(true);
    const [blockDirty, setBlockDirty] = useState(false);

    const [selectionPromptOpen, setSelectionPromptOpen] = useState(false);
    const editorHandle = useRef<JsonEditorHandle | null>(null);
    const pendingSelection = useRef<(() => void) | null>(null);
    const { macroActive, isPaused, startInline, pause, resume, cancel } =
      useMacroRunner();

    useEffect(() => {
      if (initialName === null) return;
      let cancelled = false;
      Effect.runPromise(getMacro(initialName))
        .then((r) => {
          if (cancelled) return;
          setValue(r.contents);
          setSavedText(r.contents);
          const visual = parseVisualMacroDocument(r.contents);
          if (visual.kind === "valid") {
            setBlockDocument(visual.document);
            setBlockRevision((revision) => revision + 1);
            setBlockValid(true);
          } else {
            setBlockDocument(null);
            setEditorMode("json");
          }
        })
        .catch((e) => {
          if (cancelled) return;
          setValue("");
          setBlockDocument(null);
          setEditorMode("json");
          setError(parseErrorMessage(e));
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
      return () => {
        cancelled = true;
      };
    }, [initialName]);

    const dirty = savedText !== null && (value !== savedText || blockDirty);
    const shouldBlockNavigation = useCallback(() => dirty, [dirty]);
    const routeBlocker = useBlocker({
      shouldBlockFn: shouldBlockNavigation,
      enableBeforeUnload: shouldBlockNavigation,
      withResolver: true,
    });

    useImperativeHandle(
      ref,
      () => ({
        requestNavigation(navigate) {
          if (!dirty) {
            navigate();
            return;
          }
          pendingSelection.current = navigate;
          setSelectionPromptOpen(true);
        },
      }),
      [dirty],
    );

    const cancelNavigation = useCallback(() => {
      pendingSelection.current = null;
      setSelectionPromptOpen(false);
      if (routeBlocker.status === "blocked") routeBlocker.reset();
    }, [routeBlocker]);

    const finishNavigation = useCallback(() => {
      const select = pendingSelection.current;
      pendingSelection.current = null;
      setSelectionPromptOpen(false);
      if (select !== null) {
        select();
        return;
      }
      if (routeBlocker.status === "blocked") routeBlocker.proceed();
    }, [routeBlocker]);

    const buildMarkers = useCallback(
      (body: ValidationBody, text: string): JsonMarker[] => {
        if (body.line !== undefined && body.col !== undefined) {
          return [
            {
              line: body.line,
              col: body.col,
              severity: "error",
              message: body.detail ?? body.error,
            },
          ];
        }
        if (body.line !== undefined) {
          return [
            {
              line: body.line,
              severity: "error",
              message: body.detail ?? body.error,
            },
          ];
        }
        if (body.path !== undefined) {
          const line = locatePathLine(text, body.path);
          if (line !== null) {
            return [
              {
                line,
                severity: "error",
                message: body.detail ?? body.error,
              },
            ];
          }
        }
        return [];
      },
      [],
    );

    const syntaxPrecheck = useCallback((text: string): JsonMarker[] => {
      try {
        JSON.parse(text);
        return [];
      } catch (e) {
        const msg = e instanceof SyntaxError ? e.message : String(e);
        const pos = /position (\d+)/i.exec(msg)?.[1];
        const lc =
          pos !== undefined ? positionToLineCol(text, Number(pos)) : null;
        return [
          {
            line: lc?.line ?? 1,
            col: lc?.col,
            severity: "error",
            message: `Invalid JSON: ${msg}`,
          },
        ];
      }
    }, []);

    const save = useCallback(async (): Promise<SaveResult> => {
      if (name === null) return "failed";

      // Block Validity Check
      if (editorMode === "blocks" && !blockValid) {
        setError("Fix the block workspace before saving.");
        return "failed";
      }

      // JSON Validity Check
      const local = syntaxPrecheck(value);
      if (local.length > 0) {
        setMarkers(local);
        setError("Fix the highlighted JSON error before saving.");
        return "failed";
      }

      setSaving(true);
      const result = await Effect.runPromise(putMacro(name, value)).catch(
        (e): null => {
          if (e instanceof ApiError && e.body !== null) {
            setMarkers(buildMarkers(e.body, value));
            setError(
              `${e.message}${e.body.detail ? ` — ${e.body.detail}` : ""}`,
            );
          } else {
            setError(parseErrorMessage(e));
          }
          return null;
        },
      );
      setSaving(false);
      if (result !== null) {
        setSavedText(value);
        setBlockDirty(false);
        setMarkers([]);
        setError(null);
        return "saved";
      }
      return "failed";
    }, [name, value, editorMode, blockValid, syntaxPrecheck, buildMarkers]);

    // Ctrl + S Save Hotkey
    useEffect(() => {
      const onKeyDown = (event: KeyboardEvent) => {
        if (
          !(event.ctrlKey || event.metaKey) ||
          event.altKey ||
          event.key.toLowerCase() !== "s"
        )
          return;
        event.preventDefault();
        if (
          !event.repeat &&
          dirty &&
          !saving &&
          !loading &&
          (editorMode !== "blocks" || blockValid)
        ) {
          void save();
        }
      };
      window.addEventListener("keydown", onKeyDown);
      return () => window.removeEventListener("keydown", onKeyDown);
    }, [dirty, saving, loading, editorMode, blockValid, save]);

    const rename = useCallback(
      async (confirmedName?: string) => {
        if (name === null || renaming) return;
        setRenaming(true);
        setRenameError(null);
        try {
          const targetName = confirmedName ?? newName.trim();
          if (!/^[A-Za-z0-9][A-Za-z0-9 _-]{0,63}$/.test(targetName)) {
            setRenameError(
              "Letters, digits, spaces, '_' and '-' only; must start with a letter or digit.",
            );
            return;
          }
          if (confirmedName === undefined) {
            const { names } = await Effect.runPromise(listMacros());
            const existingName = names.find(
              (candidate) =>
                candidate !== name &&
                candidate.toLocaleLowerCase() ===
                  targetName.toLocaleLowerCase(),
            );
            if (existingName !== undefined) {
              setOverwriteName(existingName);
              return;
            }
          }
          const result = await Effect.runPromise(renameMacro(name, targetName));
          setRenameOpen(false);
          onRenamed(result.name);
        } catch (cause: unknown) {
          setRenameError(parseErrorMessage(cause));
        } finally {
          setRenaming(false);
        }
      },
      [name, newName, onRenamed, renaming],
    );

    const run = useCallback(() => {
      if (name === null) return;
      if (editorMode === "blocks" && !blockValid) {
        setError("Fix the block workspace before running.");
        return;
      }
      const result = parseMacroDocument(value);
      switch (result.kind) {
        case "valid":
          startInline({ ...result.document, name });
          setMarkers([]);
          setError(null);
          return;
        case "invalid-json": {
          const local = syntaxPrecheck(value);
          setMarkers(local);
          setError("Fix the highlighted JSON error before running.");
          return;
        }
        case "invalid-document":
          setError(result.message);
          return;
      }
    }, [name, value, editorMode, blockValid, syntaxPrecheck, startInline]);

    const format = useCallback(() => {
      try {
        const pretty = `${JSON.stringify(JSON.parse(value), null, 2)}\n`;
        if (!editorHandle.current?.replaceDocument(pretty)) {
          setValue(pretty);
        }
        setMarkers([]);
        setError(null);
      } catch (e) {
        const msg = e instanceof SyntaxError ? e.message : String(e);
        const pos = /position (\d+)/i.exec(msg)?.[1];
        const lc =
          pos !== undefined ? positionToLineCol(value, Number(pos)) : null;
        setMarkers([
          {
            line: lc?.line ?? 1,
            col: lc?.col,
            severity: "error",
            message: `Cannot format: ${msg}`,
          },
        ]);
      }
    }, [value]);

    const remove = useCallback(async () => {
      if (name === null) return;
      setDeleting(true);
      const ok = await Effect.runPromise(deleteMacro(name))
        .then(() => true)
        .catch((e) => {
          setError(parseErrorMessage(e));
          return false;
        });
      setDeleting(false);
      if (ok) {
        setDeletePromptOpen(false);
        onDeleted(name);
      }
    }, [name, onDeleted]);

    const saveAndNavigate = useCallback(async () => {
      const result = await save();
      if (result === "saved") finishNavigation();
    }, [finishNavigation, save]);

    const showBlocks = useCallback(() => {
      const result = parseVisualMacroDocument(value);
      switch (result.kind) {
        case "valid":
          setBlockDocument(result.document);
          setBlockRevision((revision) => revision + 1);
          setBlockValid(true);
          setBlockDirty(value !== savedText);
          setMarkers([]);
          setError(null);
          setEditorMode("blocks");
          return;
        case "invalid-json": {
          const local = syntaxPrecheck(value);
          setMarkers(local);
          setError("Fix the highlighted JSON error before opening Blocks.");
          return;
        }
        case "invalid-document":
        case "unsupported": {
          const line = locatePathLine(value, result.path);
          setMarkers(
            line === null
              ? []
              : [{ line, severity: "error", message: result.message }],
          );
          setError(result.message);
          return;
        }
      }
    }, [savedText, syntaxPrecheck, value]);

    const discardChanges = useCallback(() => {
      if (savedText === null) return;
      if (
        editorMode === "json" &&
        editorHandle.current?.replaceDocument(savedText)
      ) {
        setBlockDirty(false);
        setMarkers([]);
        setError(null);
        return;
      }
      setValue(savedText);
      const visual = parseVisualMacroDocument(savedText);
      if (visual.kind === "valid") {
        setBlockDocument(visual.document);
        setBlockRevision((revision) => revision + 1);
        setBlockValid(true);
      }
      setBlockDirty(false);
      setMarkers([]);
      setError(null);
    }, [editorMode, savedText]);

    const handleBlockChange = useCallback(
      (document: MacroDoc) => {
        const text = formatMacroDocument(document);
        if (!editorHandle.current?.replaceDocument(text)) setValue(text);
        setBlockDirty(savedText === null || text !== savedText);
        setMarkers([]);
        setError(null);
      },
      [savedText],
    );

    if (name === null) {
      return (
        <section className="flex w-full flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-border py-16 text-sm text-muted-foreground">
          <p>Select a macro to edit, or create a new one.</p>
        </section>
      );
    }

    return (
      <section className="flex w-full flex-col gap-3 text-left">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-lg font-semibold text-foreground">
            {name}.json
          </h2>
          <Button
            size="sm"
            variant="outline"
            disabled={
              loading || saving || deleting || renaming || savedText === null
            }
            onClick={() => {
              setNewName(name);
              setOverwriteName(null);
              setRenameError(null);
              setRenameOpen(true);
            }}
          >
            Rename
          </Button>
          {dirty && (
            <span className="rounded-4xl bg-amber-500/15 px-2 py-0.5 text-xs text-amber-600 dark:text-amber-400">
              unsaved
            </span>
          )}
          {savedText !== null && !dirty && (
            <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
              <CheckIcon size={12} /> saved
            </span>
          )}
          <div className="ms-auto flex flex-wrap items-center gap-2">
            <JsonExportButtons
              name={name}
              contents={value}
              disabled={loading || savedText === null || (editorMode === "blocks" && !blockValid)}
            />
            {editorMode === "json" && (
              <Button
                size="icon-sm"
                variant="ghost"
                onClick={format}
                title="Format JSON"
                aria-label="Format JSON"
              >
                <MagicWandIcon size={14} />
              </Button>
            )}
            <Button
              size="sm"
              variant="outline"
              onClick={discardChanges}
              disabled={!dirty}
              title="Discard changes"
            >
              Undo
              <ArrowCounterClockwiseIcon size={14} />
            </Button>
            <div
              className="flex items-center gap-1"
              role="group"
              aria-label="Macro debugging controls"
            >
              <Button
                size="sm"
                variant="outline"
                onClick={run}
                disabled={editorMode === "blocks" && !blockValid}
              >
                <PlayIcon size={14} weight="fill" /> Run
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={isPaused ? resume : pause}
                disabled={!macroActive}
              >
                {isPaused ? (
                  <PlayIcon size={14} weight="fill" />
                ) : (
                  <PauseIcon size={14} weight="fill" />
                )}
                {isPaused ? "Resume" : "Pause"}
              </Button>
              <Button
                size="sm"
                variant="destructive"
                onClick={cancel}
                disabled={!macroActive}
              >
                <StopIcon size={14} weight="fill" /> Stop
              </Button>
            </div>
            <Button
              size="sm"
              onClick={() => void save()}
              disabled={
                saving || !dirty || (editorMode === "blocks" && !blockValid)
              }
            >
              {saving ? (
                <SpinnerGapIcon size={14} className="animate-spin" />
              ) : (
                <FloppyDiskIcon size={14} weight="fill" />
              )}
              Save
            </Button>
            <Button
              size="icon-sm"
              variant="destructive"
              onClick={() => setDeletePromptOpen(true)}
              disabled={deleting}
              title="Delete macro"
              aria-label="Delete macro"
            >
              {deleting ? (
                <SpinnerGapIcon size={14} className="animate-spin" />
              ) : (
                <TrashIcon size={14} weight="fill" />
              )}
            </Button>
          </div>
        </div>

        {error !== null && (
          <div
            role="alert"
            className="flex items-start gap-2 rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm"
          >
            <WarningIcon
              size={16}
              className="mt-0.5 shrink-0 text-destructive"
            />
            <p className="flex-1">{error}</p>
            <Button size="xs" variant="ghost" onClick={() => setError(null)}>
              Dismiss
            </Button>
          </div>
        )}

        <Tabs
          value={editorMode}
          onValueChange={(value) => {
            if (value === "blocks") {
              if (editorMode === "json") showBlocks();
            } else if (value === "json") {
              setEditorMode("json");
            }
          }}
        >
          <TabsList aria-label="Macro editor mode">
            <TabsTrigger value="blocks">Blocks</TabsTrigger>
            <TabsTrigger
              value="json"
              disabled={editorMode === "blocks" && !blockValid}
            >
              JSON
            </TabsTrigger>
          </TabsList>
        </Tabs>

        {loading ? (
          <div className="flex h-64 items-center justify-center gap-2 rounded-xl border border-border text-sm text-muted-foreground">
            <SpinnerGapIcon size={16} className="animate-spin" /> Loading…
          </div>
        ) : (
          <>
            {blockDocument !== null && (
              <div className={editorMode === "blocks" ? undefined : "hidden"}>
                <MacroBlocklyEditor
                  key={blockRevision}
                  document={blockDocument}
                  onChange={handleBlockChange}
                  onDirty={() => setBlockDirty(true)}
                  onValidityChange={setBlockValid}
                />
              </div>
            )}
            <div className={editorMode === "json" ? undefined : "hidden"}>
              <JsonEditor
                ref={editorHandle}
                fileName={`${name}.json`}
                cacheKey={`macro:${documentKey}`}
                value={value}
                onChange={setValue}
                editing
                markers={markers}
                className="max-h-[60vh]"
              />
            </div>
          </>
        )}

        <Dialog
          open={renameOpen}
          onOpenChange={(open) => {
            if (!renaming) setRenameOpen(open);
          }}
        >
          <DialogContent>
            <DialogHeader>
              <DialogTitle>
                {overwriteName === null ? "Rename macro" : "Overwrite macro?"}
              </DialogTitle>
              <DialogDescription>
                {overwriteName === null
                  ? "Choose a new file name. Unsaved edits will be kept."
                  : `A macro named "${overwriteName}" already exists. Do you want to overwrite it with "${name}"?`}
              </DialogDescription>
            </DialogHeader>
            {overwriteName === null && (
              <Input
                autoFocus
                aria-label="Macro name"
                value={newName}
                maxLength={64}
                disabled={renaming}
                onChange={(event) => setNewName(event.target.value)}
                onKeyDown={(event) => {
                  if (
                    event.key === "Enter" &&
                    newName.trim() &&
                    newName.trim() !== name
                  )
                    void rename();
                }}
                className="rounded-4xl border-border bg-background"
              />
            )}
            {renameError !== null && (
              <p role="alert" className="text-sm text-destructive">
                {renameError}
              </p>
            )}
            <DialogFooter>
              <Button
                variant="outline"
                disabled={renaming}
                onClick={() => {
                  if (overwriteName === null) setRenameOpen(false);
                  else {
                    setOverwriteName(null);
                    setRenameError(null);
                  }
                }}
              >
                Cancel
              </Button>
              <Button
                variant={overwriteName === null ? "default" : "destructive"}
                disabled={
                  renaming || !newName.trim() || newName.trim() === name
                }
                onClick={() => void rename(overwriteName ?? undefined)}
              >
                {renaming && (
                  <SpinnerGapIcon size={14} className="animate-spin" />
                )}
                {overwriteName === null ? "Rename" : "Overwrite macro"}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

        <Dialog
          open={deletePromptOpen}
          onOpenChange={(open) => {
            if (!open && !deleting) setDeletePromptOpen(false);
          }}
        >
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Delete macro?</DialogTitle>
              <DialogDescription>
                Delete "{name}"? This cannot be undone.
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button
                variant="outline"
                onClick={() => setDeletePromptOpen(false)}
                disabled={deleting}
              >
                Cancel
              </Button>
              <Button
                variant="destructive"
                onClick={() => void remove()}
                disabled={deleting}
              >
                {deleting && (
                  <SpinnerGapIcon size={14} className="animate-spin" />
                )}
                Delete
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

        <Dialog
          open={selectionPromptOpen || routeBlocker.status === "blocked"}
          onOpenChange={(open) => {
            if (!open) cancelNavigation();
          }}
        >
          <DialogContent showCloseButton={false}>
            <DialogHeader>
              <DialogTitle>Leave without saving?</DialogTitle>
              <DialogDescription>
                This macro has unsaved changes. Save them before leaving?
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button variant="outline" onClick={cancelNavigation}>
                Stay here
              </Button>
              <Button variant="destructive" onClick={finishNavigation}>
                Leave without saving
              </Button>
              <Button onClick={() => void saveAndNavigate()} disabled={saving}>
                {saving && (
                  <SpinnerGapIcon size={14} className="animate-spin" />
                )}
                Save and leave
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </section>
    );
  },
);
