import { useCallback, useRef, useState } from "react";
import { createFileRoute, Link, useLocation, useRouter } from "@tanstack/react-router";
import { Effect } from "effect";
import { ArrowLeftIcon, SpinnerGapIcon } from "@phosphor-icons/react";
import { Button } from "@/src/components/ui/button";
import { Input } from "@/src/components/ui/input";
import { MacroEditor, type MacroEditorHandle } from "@/src/components/editors/macro-editor";
import { MacroPicker } from "@/src/components/panels/macro-picker";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/src/components/ui/dialog";
import { listMacros, putMacro } from "@/src/lib/api";
import { errorMessage } from "@/src/lib/errors";
import { createMacroDocument } from "@/src/lib/macro-document";

const NAME_PATTERN = /^[A-Za-z0-9][A-Za-z0-9 _-]{0,63}$/;

function MacrosPage() {
  const { names } = Route.useLoaderData();
  const router = useRouter();
  const hash = useLocation({ select: (location) => location.hash });
  const selected = hash || null;
  const navigate = Route.useNavigate();
  const setSelected = useCallback(
    (name: string | null) => {
      setEditorSession((session) => session + 1);
      void navigate({ hash: name ?? "", ignoreBlocker: true });
    },
    [navigate],
  );
  const [editorSession, setEditorSession] = useState(0);
  const [renamedSelection, setRenamedSelection] = useState<{
    from: string;
    to: string;
  } | null>(null);
  const [creating, setCreating] = useState(false);
  const [creatingMacro, setCreatingMacro] = useState(false);
  const [newName, setNewName] = useState("");
  const [createError, setCreateError] = useState<string | null>(null);
  const [overwriteName, setOverwriteName] = useState<string | null>(null);
  const macroEditor = useRef<MacroEditorHandle | null>(null);

  const openCreateDialog = useCallback(() => {
    setCreating(true);
    setNewName("");
    setCreateError(null);
    setOverwriteName(null);
  }, []);

  const requestNavigation = useCallback((navigate: () => void) => {
    if (macroEditor.current === null) {
      navigate();
      return;
    }
    macroEditor.current.requestNavigation(navigate);
  }, []);

  const startCreate = useCallback(() => {
    requestNavigation(openCreateDialog);
  }, [openCreateDialog, requestNavigation]);

  const selectMacro = useCallback(
    (name: string) => {
      if (name === selected) return;
      requestNavigation(() => setSelected(name));
    },
    [requestNavigation, selected, setSelected],
  );

  const createMacro = useCallback(
    async (name: string) => {
      setCreatingMacro(true);
      const ok = await Effect.runPromise(putMacro(name, createMacroDocument(name)))
        .then(() => true)
        .catch((error: unknown) => {
          setCreateError(errorMessage(error));
          return false;
        });
      setCreatingMacro(false);
      if (ok) {
        setCreating(false);
        setOverwriteName(null);
        await router.invalidate();
        setSelected(name);
      }
    },
    [router, setSelected],
  );

  const submitCreate = useCallback(async () => {
    const name = newName.trim();
    setCreateError(null);
    if (!NAME_PATTERN.test(name)) {
      setCreateError(
        "Letters, digits, spaces, '_' and '-' only; must start with a letter or digit.",
      );
      return;
    }
    setCreatingMacro(true);
    const existingName = await Effect.runPromise(listMacros())
      .then(
        ({ names }) =>
          names.find((candidate) => candidate.toLocaleLowerCase() === name.toLocaleLowerCase()) ??
          null,
      )
      .catch((error: unknown) => {
        setCreateError(errorMessage(error));
        return undefined;
      });
    setCreatingMacro(false);
    if (existingName === undefined) return;
    if (existingName !== null) {
      setOverwriteName(existingName);
      return;
    }
    await createMacro(name);
  }, [createMacro, newName]);

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-6 px-6 py-8 sm:px-8 lg:px-4">
      <header className="flex flex-wrap items-start justify-between gap-3 text-left">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-foreground">Macro Editor</h1>
        </div>
        <Button render={<Link to="/" />} variant="outline" size="sm">
          <ArrowLeftIcon size={14} /> Back to controller
        </Button>
      </header>

      <div className="grid min-w-0 grid-cols-1 gap-6 lg:grid-cols-[240px_minmax(0,1fr)]">
        <MacroPicker
          names={names}
          selected={selected}
          onSelect={selectMacro}
          onCreate={startCreate}
        />
        <MacroEditor
          key={`${editorSession}:${renamedSelection?.to === selected ? renamedSelection.from : selected}`}
          ref={macroEditor}
          name={selected}
          onRenamed={(name) => {
            if (selected !== null) {
              const from = renamedSelection?.to === selected ? renamedSelection.from : selected;
              setRenamedSelection({ from, to: name });
            }
            void navigate({ hash: name, ignoreBlocker: true });
            void router.invalidate();
          }}
          onDeleted={() => {
            setSelected(null);
            void router.invalidate();
          }}
        />
      </div>

      <Dialog
        open={creating}
        onOpenChange={(open) => {
          if (!open && !creatingMacro) {
            setCreating(false);
            setOverwriteName(null);
          }
        }}
      >
        <DialogContent>
          {overwriteName === null ? (
            <>
              <DialogHeader>
                <DialogTitle>New macro</DialogTitle>
                <DialogDescription>
                  Choose a name. You can add actions after the macro is created.
                </DialogDescription>
              </DialogHeader>
              <Input
                autoFocus
                value={newName}
                onChange={(event) => setNewName(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") void submitCreate();
                }}
                placeholder="Macro name"
                aria-label="New macro name"
                className="rounded-4xl border-border bg-background"
              />
              {createError !== null && (
                <p role="alert" className="text-sm text-destructive">
                  {createError}
                </p>
              )}
              <DialogFooter>
                <DialogClose render={<Button variant="outline" />} disabled={creatingMacro}>
                  Cancel
                </DialogClose>
                <Button
                  onClick={() => void submitCreate()}
                  disabled={creatingMacro || newName.trim().length === 0}
                >
                  {creatingMacro && <SpinnerGapIcon size={14} className="animate-spin" />}
                  Create macro
                </Button>
              </DialogFooter>
            </>
          ) : (
            <>
              <DialogHeader>
                <DialogTitle>Overwrite macro?</DialogTitle>
                <DialogDescription>
                  A macro with this name already exists. Do you want to overwrite it?
                </DialogDescription>
              </DialogHeader>
              {createError !== null && (
                <p role="alert" className="text-sm text-destructive">
                  {createError}
                </p>
              )}
              <DialogFooter>
                <Button
                  variant="outline"
                  onClick={() => {
                    setOverwriteName(null);
                    setCreateError(null);
                  }}
                  disabled={creatingMacro}
                >
                  Cancel
                </Button>
                <Button
                  variant="destructive"
                  onClick={() => void createMacro(overwriteName)}
                  disabled={creatingMacro}
                >
                  {creatingMacro && <SpinnerGapIcon size={14} className="animate-spin" />}
                  Overwrite macro
                </Button>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}

export const Route = createFileRoute("/macros")({
  loader: () => Effect.runPromise(listMacros()),
  component: MacrosPage,
});
