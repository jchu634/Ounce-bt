import { useEffect, useId, useState } from "react";
import { Effect } from "effect";
import { ControllerColourChooser } from "@/src/components/settings/controller-colour-chooser";
import { ControllerPreview } from "@/src/components/settings/controller-preview";
import { Button } from "@/src/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/src/components/ui/dialog";
import { getConfig, patchConfig } from "@/src/lib/api";
import { requestAdapterColours } from "@/src/lib/adapters";
import {
  COLOUR_FIELDS,
  DEFAULT_CONTROLLER_COLOURS,
  expandHexColour,
  parseControllerColourHistory,
  parseControllerColours,
  randomColour,
  RECENT_COLOURS_STORAGE_KEY,
  recordSavedControllerColours,
  sameColours,
  type ControllerColours,
} from "@/src/lib/controller-colours";
import { errorMessage } from "@/src/lib/errors";

export function ControllerColoursDialog({ adapterId }: { adapterId?: string }) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const [discardOpen, setDiscardOpen] = useState(false);
  const [saved, setSaved] = useState<ControllerColours | null>(null);
  const [draft, setDraft] = useState<ControllerColours | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [recent, setRecent] = useState(() => {
    try {
      return parseControllerColourHistory(
        JSON.parse(localStorage.getItem(RECENT_COLOURS_STORAGE_KEY) ?? "null"),
      );
    } catch {
      return parseControllerColourHistory(null);
    }
  });
  const colours = draft ?? saved;
  const dirty = draft !== null && saved !== null && !sameColours(draft, saved);

  useEffect(() => {
    let disposed = false;
    const load = adapterId
      ? requestAdapterColours(adapterId).then((result) => result.colours)
      : Effect.runPromise(getConfig()).then(
          (config) => config.controller_colours,
        );
    void load
      .then((palette) => {
        if (!disposed) setSaved(parseControllerColours(palette));
      })
      .catch((cause: unknown) => {
        if (!disposed) setError(errorMessage(cause));
      });
    return () => {
      disposed = true;
    };
  }, [adapterId, loadAttempt]);

  useEffect(() => {
    try {
      localStorage.setItem(RECENT_COLOURS_STORAGE_KEY, JSON.stringify(recent));
    } catch {
      // Colour selection also works without browser storage.
    }
  }, [recent]);

  function edit(next: ControllerColours | null) {
    setDraft(next);
    setNotice(null);
  }

  function close() {
    setOpen(false);
    setDraft(null);
    setNotice(null);
    if (saved) setError(null);
  }

  async function save() {
    if (!draft || !saved || !dirty || saving) return;
    setSaving(true);
    setNotice(null);
    setError(null);
    try {
      const submitted = { ...draft };
      for (const { key } of COLOUR_FIELDS)
        submitted[key] = expandHexColour(submitted[key]);
      const result = adapterId
        ? await requestAdapterColours(adapterId, submitted)
        : await Effect.runPromise(
            patchConfig({ controller_colours: submitted }),
          ).then((config) => ({
            colours: config.config.controller_colours,
            reconnectRequired: config.colours_reconnect_required,
          }));
      const palette = parseControllerColours(result.colours);
      setRecent((history) =>
        recordSavedControllerColours(history, saved, palette),
      );
      setSaved(palette);
      setDraft(null);
      setNotice(
        result.reconnectRequired
          ? "Colours saved. Reconnect to apply them on the Switch."
          : "Colours saved.",
      );
    } catch (cause: unknown) {
      setError(errorMessage(cause));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen, details) => {
        if (nextOpen) {
          setOpen(true);
        } else if (saving || dirty) {
          details.cancel();
          if (!saving) setDiscardOpen(true);
        } else {
          close();
        }
      }}
    >
      <DialogTrigger
        render={
          <Button
            aria-label="Edit controller colours"
            title="Edit controller colours"
            variant="ghost"
            size="icon"
            className="size-17 self-center rounded-lg p-0.5 sm:size-17"
          />
        }
      >
        <span className="block size-full" aria-hidden="true">
          <ControllerPreview colours={saved ?? DEFAULT_CONTROLLER_COLOURS} />
        </span>
      </DialogTrigger>
      <DialogContent className="app-scrollbar max-h-[calc(100dvh-2rem)] gap-4 overflow-y-auto bg-background sm:max-w-2xl">
        <DialogHeader className="pr-8">
          <DialogTitle>Controller colours</DialogTitle>
          <DialogDescription>
            Choose how your Pro Controller appears on the Switch.
          </DialogDescription>
        </DialogHeader>
        {colours && (
          <div className="grid items-center gap-3 sm:grid-cols-2">
            <div className="h-32 sm:h-40">
              <ControllerPreview colours={colours} />
            </div>
            <fieldset
              disabled={saving}
              inert={saving}
              className="grid grid-cols-2"
            >
              <legend className="sr-only">Controller colours</legend>
              {COLOUR_FIELDS.map(({ key, label }) => (
                <ControllerColourChooser
                  key={key}
                  id={`${id}-${key}`}
                  label={label}
                  colour={colours[key]}
                  recent={recent[key]}
                  onChange={(colour) =>
                    edit({ ...colours, [key]: colour.toUpperCase() })
                  }
                />
              ))}
              <div className="col-span-2 mt-2 flex flex-wrap gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() =>
                    edit({
                      ...colours,
                      left_grip: randomColour(),
                      right_grip: randomColour(),
                    })
                  }
                >
                  Randomise grips
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() =>
                    edit({
                      body: randomColour(),
                      buttons: randomColour(),
                      left_grip: randomColour(),
                      right_grip: randomColour(),
                    })
                  }
                >
                  Randomise all colours
                </Button>
              </div>
            </fieldset>
          </div>
        )}
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        {!colours &&
          (error ? (
            <Button
              variant="outline"
              className="justify-self-start"
              onClick={() => {
                setError(null);
                setLoadAttempt((attempt) => attempt + 1);
              }}
            >
              Retry
            </Button>
          ) : (
            <p role="status">Loading controller coloursâ€¦</p>
          ))}
        {colours && (
          <DialogFooter className="items-center sm:flex-wrap">
            <p role="status" className="me-auto text-xs text-muted-foreground">
              {notice ?? (dirty ? "Unsaved colour changes" : "")}
            </p>
            <Button
              variant="outline"
              disabled={
                saving || sameColours(colours, DEFAULT_CONTROLLER_COLOURS)
              }
              onClick={() => edit(DEFAULT_CONTROLLER_COLOURS)}
            >
              Reset to default
            </Button>
            <Button
              variant="outline"
              disabled={!dirty || saving}
              onClick={() => edit(null)}
            >
              Reset
            </Button>

            <Button disabled={!dirty || saving} onClick={() => void save()}>
              {saving ? "Savingâ€¦" : "Save"}
            </Button>
          </DialogFooter>
        )}
        <Dialog open={discardOpen} onOpenChange={setDiscardOpen}>
          <DialogContent showCloseButton={false}>
            <DialogHeader>
              <DialogTitle>Discard colour changes?</DialogTitle>
              <DialogDescription>
                Your saved controller colours will be kept.
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <DialogClose render={<Button variant="outline" />}>
                Keep editing
              </DialogClose>
              <Button
                variant="destructive"
                onClick={() => {
                  setDiscardOpen(false);
                  close();
                }}
              >
                Discard changes
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </DialogContent>
    </Dialog>
  );
}
