import { useEffect, useLayoutEffect, useRef, useState } from "react";
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
} from "@/src/components/ui/dialog";
import { getConfig, patchConfig } from "@/src/lib/api";
import { errorMessage } from "@/src/lib/errors";
import {
  COLOUR_FIELDS,
  DEFAULT_CONTROLLER_COLOURS,
  expandHexColour,
  parseControllerColourHistory,
  recordSavedControllerColours,
  RECENT_COLOURS_STORAGE_KEY,
  parseControllerColours,
  sameColours,
  type ControllerColours,
} from "@/src/lib/controller-colours";

export function AppearanceSettings({
  onStateChange,
}: {
  onStateChange: (state: { dirty: boolean; saving: boolean }) => void;
}) {
  const [recent, setRecent] = useState(() => {
    try {
      return parseControllerColourHistory(
        JSON.parse(localStorage.getItem(RECENT_COLOURS_STORAGE_KEY) ?? "null"),
      );
    } catch {
      return parseControllerColourHistory(null);
    }
  });
  useEffect(() => {
    try {
      localStorage.setItem(RECENT_COLOURS_STORAGE_KEY, JSON.stringify(recent));
    } catch {
      // The chooser still works when browser storage is unavailable.
    }
  }, [recent]);

  const [colours, setColours] = useState<ControllerColours | null>(null);
  const [saved, setSaved] = useState<ControllerColours | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedMessage, setSavedMessage] = useState(false);
  const [reconnectNotice, setReconnectNotice] = useState(false);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const layoutRef = useRef<HTMLDivElement>(null);
  const fieldsRef = useRef<HTMLFieldSetElement>(null);
  const [previewHeight, setPreviewHeight] = useState(0);
  const ready = colours !== null;

  useLayoutEffect(() => {
    const layout = layoutRef.current;
    const fields = fieldsRef.current;
    if (!layout || !fields) return;
    function measure() {
      if (!layout || !fields) return;
      const stacked = layout.clientWidth < 832;
      const available = layout.clientHeight - (stacked ? fields.offsetHeight + 16 : 0);
      setPreviewHeight(available >= 96 ? Math.floor(available) : 0);
    }
    const observer = new ResizeObserver(measure);
    observer.observe(layout);
    observer.observe(fields);
    measure();
    return () => observer.disconnect();
  }, [ready]);

  const dirty = colours !== null && saved !== null && !sameColours(colours, saved);

  useEffect(() => {
    onStateChange({ dirty, saving });
  }, [dirty, saving, onStateChange]);

  useEffect(() => {
    let disposed = false;
    setError(null);
    void Effect.runPromise(getConfig())
      .then((config) => {
        const palette = parseControllerColours(config.controller_colours);
        if (!disposed) {
          setColours(palette);
          setSaved(palette);
        }
      })
      .catch((cause: unknown) => {
        if (!disposed) setError(errorMessage(cause));
      });
    return () => {
      disposed = true;
    };
  }, [loadAttempt]);

  function changeColour(key: keyof ControllerColours, colour: string) {
    if (saving) return;
    setColours((current) => current && { ...current, [key]: colour.toUpperCase() });
    setSavedMessage(false);
  }

  async function save() {
    if (!colours || saving) return;
    setSaving(true);
    setError(null);
    setSavedMessage(false);
    try {
      const submitted = { ...colours };
      for (const { key } of COLOUR_FIELDS) submitted[key] = expandHexColour(submitted[key]);
      const result = await Effect.runPromise(patchConfig({ controller_colours: submitted }));
      const palette = parseControllerColours(result.config.controller_colours);
      if (saved) setRecent((history) => recordSavedControllerColours(history, saved, palette));
      setColours(palette);
      setSaved(palette);
      setSavedMessage(true);
      setReconnectNotice(result.colours_reconnect_required);
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="@container/appearance h-full min-h-0">
      <section
        className="flex h-full min-h-0 flex-col gap-3"
        aria-labelledby="controller-colours-heading"
      >
        <div className="sticky -top-2 z-10 flex shrink-0 flex-wrap items-start justify-between gap-3 border-b border-border bg-background py-3">
          <div className="space-y-1">
            <h2 id="controller-colours-heading" className="text-lg font-semibold">
              Controller colours
            </h2>
            <p className="text-sm text-muted-foreground">
              Choose how your Pro Controller appears on the Switch.
            </p>
          </div>
          <div className="ml-auto flex shrink-0 flex-col items-end gap-1">
            <div className="flex gap-2">
              <Button
                variant="outline"
                disabled={!colours || saving || sameColours(colours, DEFAULT_CONTROLLER_COLOURS)}
                onClick={() => {
                  setColours({ ...DEFAULT_CONTROLLER_COLOURS });
                  setSavedMessage(false);
                }}
              >
                Reset
              </Button>
              <Button disabled={!dirty || saving} onClick={() => void save()}>
                {saving ? "Saving…" : "Save"}
              </Button>
            </div>
            <p role="status" className="min-h-4 text-xs text-muted-foreground">
              {savedMessage ? "Colours saved." : dirty ? "Unsaved colour changes" : ""}
            </p>
          </div>
        </div>
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        {!colours ? (
          error ? (
            <Button variant="outline" onClick={() => setLoadAttempt((attempt) => attempt + 1)}>
              Retry
            </Button>
          ) : (
            <p role="status">Loading controller colours…</p>
          )
        ) : (
          <div
            ref={layoutRef}
            className={`grid min-h-0 min-w-0 flex-1 items-start gap-4 ${previewHeight > 0 ? "@max-[52rem]/appearance:grid-rows-[minmax(0,1fr)_auto] @min-[52rem]/appearance:grid-cols-[15rem_minmax(0,1fr)]" : "content-start"}`}
          >
            <fieldset
              ref={fieldsRef}
              disabled={saving}
              inert={saving}
              className="grid min-w-0 grid-cols-2 gap-3 disabled:opacity-60 @min-[52rem]/appearance:grid-cols-1"
            >
              <legend className="sr-only">Controller colours</legend>
              {COLOUR_FIELDS.map(({ key, label }) => (
                <ControllerColourChooser
                  key={key}
                  id={`colour-${key}`}
                  label={label}
                  colour={colours[key]}
                  recent={recent[key]}
                  onChange={(colour) => changeColour(key, colour)}
                />
              ))}
            </fieldset>
            <figure
              hidden={previewHeight === 0}
              className="min-h-0 min-w-0 self-stretch @max-[52rem]/appearance:row-start-1"
              style={{ height: previewHeight }}
            >
              <ControllerPreview colours={colours} />
            </figure>
          </div>
        )}
      </section>
      <Dialog open={reconnectNotice} onOpenChange={setReconnectNotice}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Colours saved for the next connection</DialogTitle>
            <DialogDescription>
              Your controller is already connected. It will stay connected with its current colours.
              The new colours will appear the next time you connect it to the Switch.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <DialogClose render={<Button />}>Got it</DialogClose>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
