import {
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
  type ComponentType,
  type Ref,
  type SVGProps,
} from "react";
import { Effect } from "effect";
import {
  ArrowCounterClockwiseIcon,
  ArrowLeftIcon,
  CheckIcon,
  FloppyDiskIcon,
  GameControllerIcon,
  MagicWandIcon,
  MinusIcon,
  SpinnerGapIcon,
  SlidersHorizontalIcon,
  CodeIcon,
  WarningIcon,
} from "@phosphor-icons/react";
import {
  SwitchButtonA,
  SwitchButtonB,
  SwitchButtonHome,
  SwitchButtonL,
  SwitchButtonMinus,
  SwitchButtonPlus,
  SwitchButtonR,
  SwitchButtonSync,
  SwitchButtonX,
  SwitchButtonY,
  SwitchButtonZl,
  SwitchButtonZr,
  SwitchDpadDown,
  SwitchDpadLeft,
  SwitchDpadRight,
  SwitchDpadUp,
  SwitchStickLPress,
  SwitchStickL,
  SwitchStickRPress,
  SwitchStickR,
} from "@/src/assets/input-prompts/switch";
import {
  XboxButtonA,
  XboxButtonB,
  XboxButtonMenu,
  XboxButtonView,
  XboxButtonX,
  XboxButtonY,
  XboxGuide,
  XboxLb,
  XboxLs,
  XboxLt,
  XboxRb,
  XboxRs,
  XboxRt,
  XboxStickL,
  XboxStickR,
} from "@/src/assets/input-prompts/xbox";
import {
  Playstation5ButtonCreate,
  Playstation5ButtonOptions,
  PlaystationButtonCircle,
  PlaystationButtonCross,
  PlaystationButtonL3,
  PlaystationButtonR3,
  PlaystationButtonSquare,
  PlaystationButtonTriangle,
  PlaystationDpadDown,
  PlaystationDpadLeft,
  PlaystationDpadRight,
  PlaystationDpadUp,
  PlaystationStickL,
  PlaystationStickR,
  PlaystationTriggerL1,
  PlaystationTriggerL2,
  PlaystationTriggerR1,
  PlaystationTriggerR2,
} from "@/src/assets/input-prompts/playstation";
import {
  ControllerIcon as SteamGuideIcon,
  SteamButtonA,
  SteamButtonB,
  SteamButtonBackIcon,
  SteamButtonStartIcon,
  SteamButtonX,
  SteamButtonY,
  SteamDpadDown,
  SteamDpadLeft,
  SteamDpadRight,
  SteamDpadUp,
  SteamLb,
  SteamLg,
  SteamLt,
  SteamPad,
  SteamPadCenter,
  SteamRb,
  SteamRg,
  SteamRt,
  SteamStick,
  SteamStickLPress,
} from "@/src/assets/input-prompts/steam-controller";
import {
  SteamdeckButtonA,
  SteamdeckButtonB,
  SteamdeckButtonGuide,
  SteamdeckButtonL1,
  SteamdeckButtonL2,
  SteamdeckButtonL4,
  SteamdeckButtonL5,
  SteamdeckButtonOptions,
  SteamdeckButtonQuickaccess,
  SteamdeckButtonR1,
  SteamdeckButtonR2,
  SteamdeckButtonR4,
  SteamdeckButtonR5,
  SteamdeckButtonView,
  SteamdeckButtonX,
  SteamdeckButtonY,
  SteamdeckDpadDown,
  SteamdeckDpadLeft,
  SteamdeckDpadRight,
  SteamdeckDpadUp,
  SteamdeckStickL,
  SteamdeckStickLPress,
  SteamdeckStickR,
  SteamdeckStickRPress,
} from "@/src/assets/input-prompts/steam-deck";
import { parseButtonName } from "@/src/lib/button-names";
import { BUTTON_ICONS } from "@/src/assets/input-prompts/switch/button-icons";
import { GenericStick } from "@/src/assets/input-prompts/generic";
import { errorMessage } from "@/src/lib/errors";
import { Button } from "@/src/components/ui/button";
import { JsonExportButtons } from "@/src/components/editors/json-export-buttons";
import { Input } from "@/src/components/ui/input";
import { Label } from "@/src/components/ui/label";
import { ToggleGroup, ToggleGroupItem } from "@/src/components/ui/toggle-group";
import { ControllerPreview, ControllerVariantIcon } from "@/src/components/settings/controller-preview";
import {
  CONTROLLER_VARIANTS,
  CONTROLLER_VARIANT_NAMES,
  JOYCON_BUTTONS,
  type ControllerVariant,
} from "@/src/lib/controller-variants";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/src/components/ui/select";
import {
  Dialog,
  DialogClose,
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
import { getPreset, putPreset } from "@/src/lib/api";
import { ApiError } from "@/src/lib/api";
import {
  type ButtonName,
  type ValidationBody,
} from "@/src/lib/types";
import { locatePathLine, positionToLineCol } from "@/src/lib/json-locate";
import {
  CONTROLLER_LAYOUTS,
  GAMEPAD_BUTTON_INPUTS,
  GAMEPAD_TRIGGER_INPUTS,
  GENERIC_BUTTON_NAMES,
  GENERIC_CONTROLLER_LAYOUT,
  GENERIC_TRIGGER_NAMES,
  type ControllerLayout,
  type ControllerLayoutDefinition,
  type GamepadButtonInput,
  type GamepadTriggerInput,
} from "@/src/lib/controller-mappings";
import { cn } from "cn";

export type PresetEditorProps = {
  name: string | null;
  builtin: boolean;
  onSaved: (name: string) => void;
  ref?: Ref<PresetEditorHandle>;
};

export type PresetEditorHandle = {
  requestNavigation: (navigate: () => void) => void;
};

type SaveResult = "saved" | "save-as-required" | "failed";

export function PresetEditor({
  name,
  builtin,
  onSaved,
  ref,
}: PresetEditorProps) {
  const [initialName] = useState(name);
  const [value, setValue] = useState("");
  const [savedText, setSavedText] = useState<string | null>(null);
  const [loading, setLoading] = useState(initialName !== null);
  const [saving, setSaving] = useState(false);
  const [saveAsOpen, setSaveAsOpen] = useState(false);
  const [saveAsName, setSaveAsName] = useState("");
  const [savingAs, setSavingAs] = useState(false);
  const [saveAsError, setSaveAsError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [markers, setMarkers] = useState<JsonMarker[]>([]);
  const [advanced, setAdvanced] = useState(false);
  const [navigationPromptOpen, setNavigationPromptOpen] = useState(false);
  const editorHandle = useRef<JsonEditorHandle | null>(null);
  const pendingNavigation = useRef<(() => void) | null>(null);
  const saveAsForNavigation = useRef(false);

  useEffect(() => {
    if (initialName === null) return;
    let cancelled = false;
    Effect.runPromise(getPreset(initialName))
      .then((r) => {
        if (cancelled) return;
        setValue(r.contents);
        setSavedText(r.contents);
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setValue("");
        setError(errorMessage(error));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [initialName]);

  const dirty = savedText !== null && value !== savedText;

  useImperativeHandle(
    ref,
    () => ({
      requestNavigation(navigate) {
        if (saving || savingAs) return;
        if (!dirty) {
          navigate();
          return;
        }
        pendingNavigation.current = navigate;
        setNavigationPromptOpen(true);
      },
    }),
    [dirty, saving, savingAs],
  );

  const cancelNavigation = useCallback(() => {
    pendingNavigation.current = null;
    setNavigationPromptOpen(false);
  }, []);

  const finishNavigation = useCallback(() => {
    const navigate = pendingNavigation.current;
    pendingNavigation.current = null;
    saveAsForNavigation.current = false;
    setNavigationPromptOpen(false);
    navigate?.();
  }, []);

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

  const buildMarkers = useCallback(
    (body: ValidationBody, text: string): JsonMarker[] => {
      if (body.line !== undefined) {
        return [
          {
            line: body.line,
            col: body.col,
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

  const save = useCallback(async (): Promise<SaveResult> => {
    if (name === null) return "failed";
    const local = syntaxPrecheck(value);
    if (local.length > 0) {
      setMarkers(local);
      setError("Invalid JSON — fix the highlighted line before saving.");
      return "failed";
    }
    if (builtin) {
      let suggestedName = name;
      const document: unknown = JSON.parse(value);
      if (
        typeof document === "object" &&
        document !== null &&
        !Array.isArray(document) &&
        "name" in document &&
        typeof document.name === "string"
      ) {
        suggestedName = document.name;
      }
      setSaveAsName(`${suggestedName} copy`);
      setSaveAsError(null);
      setSaveAsOpen(true);
      return "save-as-required";
    }
    setSaving(true);
    const result = await Effect.runPromise(putPreset(name, value)).catch(
      (e): null => {
        if (e instanceof ApiError && e.body !== null) {
          setMarkers(buildMarkers(e.body, value));
          setError(`${e.message}${e.body.detail ? ` — ${e.body.detail}` : ""}`);
        } else {
          setError(String(e));
        }
        return null;
      },
    );
    setSaving(false);
    if (result !== null) {
      setSavedText(value);
      setMarkers([]);
      setError(null);
      onSaved(name);
      return "saved";
    }
    return "failed";
  }, [name, builtin, value, syntaxPrecheck, buildMarkers, onSaved]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (
        !(event.ctrlKey || event.metaKey) ||
        event.altKey ||
        event.key.toLowerCase() !== "s"
      )
        return;
      event.preventDefault();
      if (!event.repeat && dirty && !saving && !loading && !saveAsOpen)
        void save();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [dirty, saving, loading, saveAsOpen, save]);

  const format = useCallback(() => {
    try {
      const pretty = `${JSON.stringify(JSON.parse(value), null, 2)}\n`;
      if (!editorHandle.current?.replaceDocument(pretty)) {
        setValue(pretty);
      }
      setMarkers([]);
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

  const saveAsNewPreset = useCallback(async () => {
    const targetName = saveAsName.trim();
    if (targetName.length === 0) return;
    setSavingAs(true);
    setSaveAsError(null);
    const targetFilename = `preset-${crypto.randomUUID()}`;
    const succeeded = await Promise.resolve()
      .then(() => {
        const document: unknown = JSON.parse(value);
        if (
          typeof document !== "object" ||
          document === null ||
          Array.isArray(document)
        ) {
          throw new Error("Preset JSON must be an object.");
        }
        const contents = `${JSON.stringify({ ...document, name: targetName }, null, 2)}\n`;
        return Effect.runPromise(putPreset(targetFilename, contents));
      })
      .then(() => true)
      .catch((error: unknown) => {
        setSaveAsError(errorMessage(error));
        return false;
      });
    setSavingAs(false);
    if (!succeeded) return;
    setSaveAsOpen(false);
    onSaved(targetFilename);
    if (saveAsForNavigation.current) finishNavigation();
  }, [saveAsName, value, onSaved, finishNavigation]);

  const saveAndNavigate = useCallback(async () => {
    saveAsForNavigation.current = builtin;
    const result = await save();
    switch (result) {
      case "saved":
        finishNavigation();
        return;
      case "save-as-required":
        setNavigationPromptOpen(false);
        return;
      case "failed":
        saveAsForNavigation.current = false;
        return;
    }
  }, [builtin, finishNavigation, save]);

  if (name === null) {
    return (
      <section className="flex w-full flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-border py-16 text-sm text-muted-foreground">
        <p>Select a preset to inspect it.</p>
      </section>
    );
  }

  return (
    <section className="flex w-full flex-col gap-3 text-left">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-lg font-semibold text-foreground">
          {name}.json
        </h2>
        {builtin && (
          <span className="rounded-4xl bg-muted px-2 py-0.5 text-[10px] tracking-wide text-muted-foreground uppercase">
            built-in
          </span>
        )}
        {dirty && (
          <span className="rounded-4xl bg-amber-500/15 px-2 py-0.5 text-xs text-amber-600 dark:text-amber-400">
            unsaved
          </span>
        )}
        {!builtin && savedText !== null && !dirty && (
          <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
            <CheckIcon size={12} /> saved
          </span>
        )}
        <div className="ms-auto flex flex-wrap items-center gap-2">
          <JsonExportButtons name={name} contents={value} disabled={loading || savedText === null} />
          <Button
            size="sm"
            variant={advanced ? "secondary" : "outline"}
            onClick={() => setAdvanced((current) => !current)}
          >
            {advanced ? (
              <SlidersHorizontalIcon size={14} />
            ) : (
              <CodeIcon size={14} />
            )}
            {advanced ? "Visual Editor" : "JSON Editor"}
          </Button>
          {advanced && (
            <Button size="sm" variant="ghost" onClick={format} title="Format">
              <MagicWandIcon size={14} />
            </Button>
          )}
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              if (savedText === null) return;
              // While an edit session is attached the editor's
              // document is authoritative — route through it.
              if (!editorHandle.current?.replaceDocument(savedText)) {
                setValue(savedText);
              }
              setMarkers([]);
              setError(null);
            }}
            disabled={!dirty}
            title="Revert"
          >
            Undo
            <ArrowCounterClockwiseIcon size={14} />
          </Button>
          <Button
            size="sm"
            onClick={() => void save()}
            disabled={saving || !dirty}
          >
            {saving ? (
              <SpinnerGapIcon size={14} className="animate-spin" />
            ) : (
              <FloppyDiskIcon size={14} weight="fill" />
            )}
            Save
          </Button>
        </div>
      </div>

      {error !== null && (
        <div
          role="alert"
          className="flex items-start gap-2 rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm"
        >
          <WarningIcon size={16} className="mt-0.5 shrink-0 text-destructive" />
          <p className="flex-1">{error}</p>
          <Button size="xs" variant="ghost" onClick={() => setError(null)}>
            Dismiss
          </Button>
        </div>
      )}
      {loading ? (
        <div className="flex h-64 items-center justify-center gap-2 rounded-xl border border-border text-sm text-muted-foreground">
          <SpinnerGapIcon size={16} className="animate-spin" /> Loading…
        </div>
      ) : advanced ? (
        <JsonEditor
          ref={editorHandle}
          fileName={`${name}.json`}
          cacheKey={`preset:${name}`}
          value={value}
          onChange={setValue}
          editing
          markers={markers}
          className="max-h-[60vh] min-h-64"
        />
      ) : (
        <PresetMappingEditor
          value={value}
          onChange={setValue}
          disabled={false}
        />
      )}
      <Dialog
        open={saveAsOpen}
        onOpenChange={(open) => {
          setSaveAsOpen(open);
          if (!open && saveAsForNavigation.current) {
            saveAsForNavigation.current = false;
            cancelNavigation();
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Save as new preset</DialogTitle>
            <DialogDescription>
              Built-in presets cannot be overwritten. Name your edited copy to
              save it as a new preset.
            </DialogDescription>
          </DialogHeader>
          <Input
            autoFocus
            value={saveAsName}
            onChange={(event) => setSaveAsName(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") void saveAsNewPreset();
            }}
            placeholder="Preset name"
            aria-label="New preset name"
            className="rounded-4xl border-border bg-background"
          />
          {saveAsError !== null && (
            <p role="alert" className="text-sm text-destructive">
              {saveAsError}
            </p>
          )}
          <DialogFooter>
            <DialogClose
              render={<Button variant="outline" />}
              onClick={() => {
                if (saveAsForNavigation.current) cancelNavigation();
                saveAsForNavigation.current = false;
              }}
            >
              Cancel
            </DialogClose>
            <Button
              onClick={() => void saveAsNewPreset()}
              disabled={savingAs || saveAsName.trim().length === 0}
            >
              {savingAs && (
                <SpinnerGapIcon size={14} className="animate-spin" />
              )}
              Save new preset
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <Dialog
        open={navigationPromptOpen}
        onOpenChange={(open) => {
          if (!open) cancelNavigation();
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Leave without saving?</DialogTitle>
            <DialogDescription>
              You have unsaved changes to this preset. Save them before leaving?
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={cancelNavigation}>
              Go back
            </Button>
            <Button variant="destructive" onClick={finishNavigation}>
              Exit without saving
            </Button>
            <Button onClick={() => void saveAndNavigate()} disabled={saving}>
              {saving && <SpinnerGapIcon size={14} className="animate-spin" />}
              Save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}

type PresetMappingEditorProps = {
  value: string;
  onChange: (value: string) => void;
  disabled: boolean;
};

type ParsedPreset =
  | {
      kind: "valid";
      document: Record<string, unknown>;
      mapping: Record<string, unknown>;
      mappings: Record<string, unknown>;
      buttons: Record<string, ButtonName>;
      triggers: Record<string, ButtonName>;
    }
  | { kind: "invalid"; message: string };

type PhysicalSource =
  | { kind: "button"; input: GamepadButtonInput }
  | { kind: "trigger"; input: GamepadTriggerInput };

const VALID_BUTTON_SET = new Set<string>(GAMEPAD_BUTTON_INPUTS);
const VALID_TRIGGER_SET = new Set<string>(GAMEPAD_TRIGGER_INPUTS);

// W3C Standard Gamepad button index -> semantic SDL3 input.
const WEB_GAMEPAD_SOURCES: readonly (PhysicalSource | null)[] = [
  { kind: "button", input: "south" },
  { kind: "button", input: "east" },
  { kind: "button", input: "west" },
  { kind: "button", input: "north" },
  { kind: "button", input: "left_shoulder" },
  { kind: "button", input: "right_shoulder" },
  { kind: "trigger", input: "left_trigger" },
  { kind: "trigger", input: "right_trigger" },
  { kind: "button", input: "back" },
  { kind: "button", input: "start" },
  { kind: "button", input: "left_stick" },
  { kind: "button", input: "right_stick" },
  { kind: "button", input: "dpad_up" },
  { kind: "button", input: "dpad_down" },
  { kind: "button", input: "dpad_left" },
  { kind: "button", input: "dpad_right" },
  { kind: "button", input: "guide" },
  { kind: "button", input: "touchpad" },
];

const MAPPING_GROUPS: readonly { title: string; controls: readonly ButtonName[] }[] = [
  { title: "Shoulder controls", controls: ["ZL", "ZR", "L", "R"] },
  { title: "Rail buttons", controls: ["SL", "SR"] },
  {
    title: "System controls",
    controls: ["MINUS", "PLUS", "CAPTURE", "HOME"],
  },
  { title: "D-pad", controls: ["UP", "RIGHT", "DOWN", "LEFT"] },
  { title: "Sticks", controls: ["STICK_L", "STICK_R"] },
  { title: "Face buttons", controls: ["A", "B", "X", "Y"] },
];

const BUTTON_LABELS: Record<ButtonName, string> = {
  A: "A",
  B: "B",
  X: "X",
  Y: "Y",
  L: "L bumper",
  R: "R bumper",
  ZL: "ZL trigger",
  ZR: "ZR trigger",
  UP: "D-pad up",
  DOWN: "D-pad down",
  LEFT: "D-pad left",
  RIGHT: "D-pad right",
  PLUS: "Plus",
  MINUS: "Minus",
  HOME: "Home",
  CAPTURE: "Capture",
  STICK_L: "Left stick click",
  STICK_R: "Right stick click",
  SL: "SL",
  SR: "SR",
};

type InputIcon = ComponentType<SVGProps<SVGSVGElement>>;

const MAPPING_TRIGGER_CLASS =
  "w-auto shrink-0 rounded-md border-primary-foreground/30 bg-primary-foreground px-2 text-primary";
const STICK_SIDES = ["left", "right"] as const;
type StickSide = (typeof STICK_SIDES)[number];
const STICK_NAMES: Record<StickSide, string> = { left: "Left stick", right: "Right stick" };
const STICK_ICONS: Record<ControllerLayout, Record<StickSide, InputIcon>> = {
  generic: { left: GenericStick, right: GenericStick },
  switch: { left: SwitchStickL, right: SwitchStickR },
  xbox: { left: XboxStickL, right: XboxStickR },
  playstation: { left: PlaystationStickL, right: PlaystationStickR },
  steam_controller: { left: SteamStick, right: SteamPad },
  steam_deck: { left: SteamdeckStickL, right: SteamdeckStickR },
};

const CONTROLLER_BUTTON_ICONS: Partial<
  Record<ControllerLayout, Partial<Record<GamepadButtonInput, InputIcon>>>
> = {
  switch: {
    east: SwitchButtonA,
    south: SwitchButtonB,
    north: SwitchButtonX,
    west: SwitchButtonY,
    back: SwitchButtonMinus,
    guide: SwitchButtonHome,
    start: SwitchButtonPlus,
    right_stick: SwitchStickRPress,
    left_stick: SwitchStickLPress,
    left_shoulder: SwitchButtonL,
    right_shoulder: SwitchButtonR,
    dpad_up: SwitchDpadUp,
    dpad_down: SwitchDpadDown,
    dpad_left: SwitchDpadLeft,
    dpad_right: SwitchDpadRight,
    misc1: SwitchButtonSync,
  },
  xbox: {
    south: XboxButtonA,
    east: XboxButtonB,
    west: XboxButtonX,
    north: XboxButtonY,
    left_shoulder: XboxLb,
    right_shoulder: XboxRb,
    back: XboxButtonView,
    start: XboxButtonMenu,
    left_stick: XboxLs,
    right_stick: XboxRs,
    guide: XboxGuide,
  },
  playstation: {
    south: PlaystationButtonCross,
    east: PlaystationButtonCircle,
    west: PlaystationButtonSquare,
    north: PlaystationButtonTriangle,
    back: Playstation5ButtonCreate,
    start: Playstation5ButtonOptions,
    left_stick: PlaystationButtonL3,
    right_stick: PlaystationButtonR3,
    left_shoulder: PlaystationTriggerL1,
    right_shoulder: PlaystationTriggerR1,
    dpad_up: PlaystationDpadUp,
    dpad_down: PlaystationDpadDown,
    dpad_left: PlaystationDpadLeft,
    dpad_right: PlaystationDpadRight,
  },
  steam_controller: {
    south: SteamButtonA,
    east: SteamButtonB,
    west: SteamButtonX,
    north: SteamButtonY,
    back: SteamButtonBackIcon,
    guide: SteamGuideIcon,
    start: SteamButtonStartIcon,
    left_stick: SteamStickLPress,
    right_stick: SteamPadCenter,
    left_shoulder: SteamLb,
    right_shoulder: SteamRb,
    dpad_up: SteamDpadUp,
    dpad_down: SteamDpadDown,
    dpad_left: SteamDpadLeft,
    dpad_right: SteamDpadRight,
    left_paddle1: SteamLg,
    right_paddle1: SteamRg,
  },
  steam_deck: {
    south: SteamdeckButtonA,
    east: SteamdeckButtonB,
    west: SteamdeckButtonX,
    north: SteamdeckButtonY,
    back: SteamdeckButtonView,
    guide: SteamdeckButtonGuide,
    start: SteamdeckButtonOptions,
    misc1: SteamdeckButtonQuickaccess,
    left_stick: SteamdeckStickLPress,
    right_stick: SteamdeckStickRPress,
    left_shoulder: SteamdeckButtonL1,
    right_shoulder: SteamdeckButtonR1,
    dpad_up: SteamdeckDpadUp,
    dpad_down: SteamdeckDpadDown,
    dpad_left: SteamdeckDpadLeft,
    dpad_right: SteamdeckDpadRight,
    left_paddle1: SteamdeckButtonL4,
    right_paddle1: SteamdeckButtonR4,
    left_paddle2: SteamdeckButtonL5,
    right_paddle2: SteamdeckButtonR5,
  },
};

const CONTROLLER_TRIGGER_ICONS: Partial<
  Record<ControllerLayout, Partial<Record<GamepadTriggerInput, InputIcon>>>
> = {
  switch: {
    left_trigger: SwitchButtonZl,
    right_trigger: SwitchButtonZr,
  },
  xbox: {
    left_trigger: XboxLt,
    right_trigger: XboxRt,
  },
  playstation: {
    left_trigger: PlaystationTriggerL2,
    right_trigger: PlaystationTriggerR2,
  },
  steam_controller: {
    left_trigger: SteamLt,
    right_trigger: SteamRt,
  },
  steam_deck: {
    left_trigger: SteamdeckButtonL2,
    right_trigger: SteamdeckButtonR2,
  },
};

function physicalInputIcon(
  source: PhysicalSource,
  layout: ControllerLayout,
): InputIcon {
  if (source.kind === "button") {
    return CONTROLLER_BUTTON_ICONS[layout]?.[source.input] ?? GameControllerIcon;
  }
  return CONTROLLER_TRIGGER_ICONS[layout]?.[source.input] ?? GameControllerIcon;
}

const isControllerLayout = (value: unknown): value is ControllerLayout =>
  value === "generic" ||
  value === "switch" ||
  value === "xbox" ||
  value === "playstation" ||
  value === "steam_controller" ||
  value === "steam_deck";

const MAPPING_FIELDS: ReadonlyArray<"buttons" | "triggers"> = [
  "buttons",
  "triggers",
];

function isMappingObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parsePreset(value: string, variant: ControllerVariant): ParsedPreset {
  let parsed: unknown;
  try {
    parsed = JSON.parse(value);
  } catch {
    return {
      kind: "invalid",
      message: "Fix the JSON in Advanced mode before using the mapping editor.",
    };
  }
  if (!isMappingObject(parsed)) {
    return { kind: "invalid", message: "Preset JSON must be an object." };
  }

  const document = parsed;
  if (document.version !== 2) {
    return { kind: "invalid", message: "This editor requires a version 2 preset." };
  }
  const mappings = document.mappings;
  if (!isMappingObject(mappings) || !CONTROLLER_VARIANTS.every((item) => isMappingObject(mappings[item]))) {
    return { kind: "invalid", message: "Version 2 presets require mappings for all four controllers." };
  }
  const mapping = mappings[variant];
  if (!isMappingObject(mapping)) {
    return { kind: "invalid", message: "The selected controller mapping must be an object." };
  }
  const controls: Record<"buttons" | "triggers", Record<string, ButtonName>> = {
    buttons: {},
    triggers: {},
  };
  for (const field of MAPPING_FIELDS) {
    const rawMappings = mapping[field];
    if (rawMappings === undefined) continue;
    if (
      typeof rawMappings !== "object" ||
      rawMappings === null ||
      Array.isArray(rawMappings)
    ) {
      return {
        kind: "invalid",
        message: `The preset "${field}" field must be an object.`,
      };
    }
    const validSet = field === "buttons" ? VALID_BUTTON_SET : VALID_TRIGGER_SET;
    for (const [inputName, target] of Object.entries(rawMappings)) {
      const button = parseButtonName(target);
      if (!validSet.has(inputName) || button === undefined) {
        return {
          kind: "invalid",
          message: `A ${field === "buttons" ? "button" : "trigger"} mapping is not valid. Open Advanced mode to fix it.`,
        };
      }
      controls[field][inputName] = button;
    }
  }
  return { kind: "valid", document, mapping, mappings, ...controls };
}

function sourceFor(
  buttons: Record<string, ButtonName>,
  triggers: Record<string, ButtonName>,
  target: ButtonName,
): PhysicalSource | null {
  const buttonInput = Object.entries(buttons).find(
    ([, button]) => button === target,
  )?.[0];
  if (buttonInput !== undefined && VALID_BUTTON_SET.has(buttonInput)) {
    return { kind: "button", input: buttonInput as GamepadButtonInput };
  }
  const triggerInput = Object.entries(triggers).find(
    ([, button]) => button === target,
  )?.[0];
  if (triggerInput !== undefined && VALID_TRIGGER_SET.has(triggerInput)) {
    return { kind: "trigger", input: triggerInput as GamepadTriggerInput };
  }
  return null;
}

function sourceValue(source: PhysicalSource | null): string {
  return source === null ? "" : `${source.kind}:${source.input}`;
}

function parseSourceValue(value: string): PhysicalSource | null {
  const [kind, input, extra] = value.split(":");
  if (extra !== undefined || !input) return null;
  if (kind === "button" && VALID_BUTTON_SET.has(input)) {
    return { kind, input: input as GamepadButtonInput };
  }
  if (kind === "trigger" && VALID_TRIGGER_SET.has(input)) {
    return { kind, input: input as GamepadTriggerInput };
  }
  return null;
}

function inferControllerLayout(
  document: Record<string, unknown>,
): ControllerLayout {
  if (isControllerLayout(document.controller_layout))
    return document.controller_layout;
  const identity =
    `${document.name ?? ""} ${document.description ?? ""}`.toLowerCase();
  if (
    identity.includes("playstation") ||
    identity.includes("dualshock") ||
    identity.includes("dualsense")
  ) {
    return "playstation";
  }
  if (
    identity.includes("switch") ||
    identity.includes("joy-con") ||
    identity.includes("nintendo")
  ) {
    return "switch";
  }
  if (identity.includes("steam deck") || identity.includes("steamdeck")) {
    return "steam_deck";
  }
  if (identity.includes("steam") || identity.includes("valve")) {
    return "steam_controller";
  }
  return "xbox";
}

function physicalInputLabel(
  source: PhysicalSource,
  controller: ControllerLayoutDefinition,
): string {
  if (source.kind === "button") {
    return (
      controller.buttonNames[source.input] ??
      GENERIC_BUTTON_NAMES[source.input]
    );
  }
  return (
    controller.triggerNames[source.input] ??
    GENERIC_TRIGGER_NAMES[source.input]
  );
}

function controllerLayoutDefinition(
  layout: ControllerLayout,
): ControllerLayoutDefinition {
  return (
    CONTROLLER_LAYOUTS.find((controller) => controller.value === layout) ??
    GENERIC_CONTROLLER_LAYOUT
  );
}

function PresetMappingEditor({
  value,
  onChange,
  disabled,
}: PresetMappingEditorProps) {
  const [variant, setVariant] = useState<ControllerVariant>("pro");
  const parsed = useMemo(() => parsePreset(value, variant), [value, variant]);
  const [listeningTarget, setListeningTarget] =
    useState<ButtonName | null>(null);
  const pressedAtStart = useRef<Set<number>>(new Set());

  const updateMapping = useCallback((changes: Record<string, unknown>) => {
    if (disabled || parsed.kind === "invalid") return;
    const mapping = { ...parsed.mapping, ...changes };
    const nextDocument = { ...parsed.document, mappings: { ...parsed.mappings, [variant]: mapping } };
    onChange(`${JSON.stringify(nextDocument, null, 2)}\n`);
  }, [disabled, parsed, variant, onChange]);

  const assign = useCallback(
    (target: ButtonName, source: PhysicalSource | null) => {
      if (disabled || parsed.kind === "invalid") return;
      const nextButtons = Object.fromEntries(
        Object.entries(parsed.buttons).filter(
          ([inputName, button]) =>
            !(source?.kind === "button" && inputName === source.input) &&
            button !== target,
        ),
      );
      const nextTriggers = Object.fromEntries(
        Object.entries(parsed.triggers).filter(
          ([inputName, button]) =>
            !(source?.kind === "trigger" && inputName === source.input) &&
            button !== target,
        ),
      );
      if (source?.kind === "button") nextButtons[source.input] = target;
      if (source?.kind === "trigger") nextTriggers[source.input] = target;
      updateMapping({ buttons: nextButtons, triggers: nextTriggers });
    },
    [disabled, parsed, updateMapping],
  );

  useEffect(() => {
    if (listeningTarget === null) return;
    let animationFrame = 0;
    const poll = () => {
      const gamepad = Array.from(navigator.getGamepads()).find(
        (item) => item !== null,
      );
      if (gamepad !== undefined) {
        const pressed = new Set<number>();
        gamepad.buttons.forEach((button, index) => {
          if (button.pressed) pressed.add(index);
        });
        const newlyPressed = [...pressed].find(
          (index) => !pressedAtStart.current.has(index),
        );
        if (newlyPressed !== undefined) {
          const mapped = WEB_GAMEPAD_SOURCES[newlyPressed] ?? null;
          if (mapped !== null) {
            assign(listeningTarget, mapped);
            setListeningTarget(null);
            return;
          }
        }
        pressedAtStart.current = pressed;
      }
      animationFrame = requestAnimationFrame(poll);
    };
    animationFrame = requestAnimationFrame(poll);
    return () => cancelAnimationFrame(animationFrame);
  }, [assign, listeningTarget]);

  const startListening = (target: ButtonName) => {
    const gamepad = Array.from(navigator.getGamepads()).find(
      (item) => item !== null,
    );
    pressedAtStart.current = new Set(
      gamepad?.buttons.flatMap((button, index) =>
        button.pressed ? [index] : [],
      ) ?? [],
    );
    setListeningTarget(target);
  };

  if (parsed.kind === "invalid") {
    return (
      <div className="flex min-h-64 items-center justify-center rounded-xl border border-dashed border-border px-6 text-center text-sm text-muted-foreground">
        {parsed.message}
      </div>
    );
  }

  const controllerLayout = inferControllerLayout(parsed.document);
  const controller = controllerLayoutDefinition(controllerLayout);
  const ControllerImage = controller.image;
  const groups = MAPPING_GROUPS.flatMap(({ title, controls }) => {
    const visible = variant === "joycon_l" || variant === "joycon_r"
      ? controls.filter((button) => JOYCON_BUTTONS[variant].includes(button))
      : controls;
    if (visible.length === 0 || (variant === "pro" && title === "Rail buttons")) return [];
    return [{ title, controls: visible }];
  });
  function stickRow(side: StickSide) {
    if (parsed.kind !== "valid") return null;
    const rawSticks = isMappingObject(parsed.mapping.sticks)
      ? parsed.mapping.sticks
      : {};
    const current = rawSticks[side];
    const source: StickSide | undefined =
      current === "left" || current === "right"
        ? current
        : current === undefined
          ? side
          : undefined;
    const OutputIcon = STICK_ICONS.switch[side];
    const SourceIcon = source ? STICK_ICONS[controllerLayout][source] : GenericStick;
    const label = STICK_NAMES[side];

    return (
      <div key={side} className="flex w-fit items-center gap-2 rounded-lg p-1.5">
        <span title={label} className="flex size-8 shrink-0 items-center justify-center text-primary-foreground">
          <OutputIcon className="size-7" aria-hidden="true" />
        </span>
        <ArrowLeftIcon aria-hidden="true" weight="bold" className="size-4 shrink-0 text-primary-foreground" />
        <Select
          value={source ?? ""}
          disabled={disabled || listeningTarget !== null}
          onValueChange={(value) => {
            const next = STICK_SIDES.find((option) => option === value) ?? null;
            updateMapping({ sticks: { ...rawSticks, [side]: next } });
          }}
        >
          <SelectTrigger
            size="sm"
            aria-label={`Physical stick for ${label.toLowerCase()}`}
            title={`${label} maps to ${source ? STICK_NAMES[source].toLowerCase() : "none"}`}
            className={MAPPING_TRIGGER_CLASS}
          >
            <SelectValue>
              {source ? (
                <SourceIcon className="size-5" aria-hidden="true" />
              ) : (
                <MinusIcon className="size-5" aria-hidden="true" />
              )}
            </SelectValue>
          </SelectTrigger>
          <SelectContent align="start" className="w-50">
            <SelectGroup>
              <SelectItem value="">None</SelectItem>
              <SelectLabel>Sticks</SelectLabel>
              {STICK_SIDES.map((option) => {
                const OptionIcon = STICK_ICONS[controllerLayout][option];
                return (
                  <SelectItem key={option} value={option}>
                    <OptionIcon className="size-5" aria-hidden="true" />
                    {STICK_NAMES[option]}
                  </SelectItem>
                );
              })}
            </SelectGroup>
          </SelectContent>
        </Select>
      </div>
    );
  }

  const setControllerLayout = (layout: ControllerLayout) => {
    if (disabled) return;
    onChange(
      `${JSON.stringify({ ...parsed.document, controller_layout: layout }, null, 2)}\n`,
    );
  };

  function selectVariant(value: string | null) {
    const next = CONTROLLER_VARIANTS.find((item) => item === value);
    if (next) {
      setListeningTarget(null);
      setVariant(next);
    }
  }

  const mappingRow = (target: ButtonName) => {
    const source = sourceFor(parsed.buttons, parsed.triggers, target);
    const listening = listeningTarget === target;
    const Icon = BUTTON_ICONS[target];
    const SelectedInputIcon =
      source === null ? null : physicalInputIcon(source, controllerLayout);
    return (
      <div
        key={target}
        className="group flex w-fit items-center gap-2 rounded-lg p-1.5 transition-colors"
      >
        <span
          title={BUTTON_LABELS[target]}
          className="flex size-8 shrink-0 items-center justify-center text-primary-foreground"
        >
          <Icon className="size-7" />
        </span>
        <ArrowLeftIcon
          aria-hidden="true"
          weight="bold"
          className="size-4 shrink-0 text-primary-foreground"
        />
        <Select
          value={sourceValue(source)}
          onValueChange={(nextValue) => {
            if (nextValue !== null) assign(target, parseSourceValue(nextValue));
          }}
          disabled={disabled || listeningTarget !== null}
        >
          <SelectTrigger
            id={`mapping-${target}`}
            size="sm"
            aria-label={`Physical input for ${BUTTON_LABELS[target]}`}
            title={
              source === null
                ? `${BUTTON_LABELS[target]} is not mapped`
                : `${BUTTON_LABELS[target]} maps to ${physicalInputLabel(
                    source,
                    controller,
                  )}`
            }
            className={MAPPING_TRIGGER_CLASS}
          >
            <SelectValue>
              {source === null || SelectedInputIcon === null ? (
                <MinusIcon className="size-5" />
              ) : (
                <SelectedInputIcon className="size-5" />
              )}
            </SelectValue>
          </SelectTrigger>
          <SelectContent align="start" className="w-50">
            <SelectGroup>
              <SelectItem value="">None</SelectItem>
            </SelectGroup>
            <SelectGroup>
              <SelectLabel>Buttons</SelectLabel>
              {GAMEPAD_BUTTON_INPUTS.map((input) => {
                const option: PhysicalSource = { kind: "button", input };
                const OptionIcon = physicalInputIcon(option, controllerLayout);
                return (
                  <SelectItem key={input} value={`button:${input}`}>
                    <OptionIcon className="size-5" />
                    {physicalInputLabel(option, controller)}
                  </SelectItem>
                );
              })}
            </SelectGroup>
            <SelectGroup>
              <SelectLabel>Triggers</SelectLabel>
              {GAMEPAD_TRIGGER_INPUTS.map((input) => {
                const option: PhysicalSource = { kind: "trigger", input };
                const OptionIcon = physicalInputIcon(option, controllerLayout);
                return (
                  <SelectItem key={input} value={`trigger:${input}`}>
                    <OptionIcon className="size-5" />
                    {physicalInputLabel(option, controller)}
                  </SelectItem>
                );
              })}
            </SelectGroup>
          </SelectContent>
        </Select>
        <Button
          size="icon-sm"
          variant={listening ? "default" : "outline"}
          onClick={() =>
            listening ? setListeningTarget(null) : startListening(target)
          }
          disabled={listeningTarget !== null && !listening}
          title={
            listening
              ? "Cancel controller input"
              : `Press a controller button for ${BUTTON_LABELS[target]}`
          }
          aria-label={
            listening
              ? "Cancel controller input"
              : `Listen for ${BUTTON_LABELS[target]}`
          }
          className={cn(
            "rounded-md dark:bg-white",
            !listening && "text-muted-foreground hover:text-foreground",
          )}
        >
          {listening ? (
            <SpinnerGapIcon className="animate-spin" />
          ) : (
            <GameControllerIcon />
          )}
        </Button>
      </div>
    );
  };

  return (
    <div className="@container/mapping overflow-hidden rounded-xl border border-border bg-card">
      <div className="flex flex-wrap items-center gap-3 border-b border-border bg-muted/30 px-4 py-3">
        <div className="flex items-center gap-2">
          <GameControllerIcon size={18} />
          <div>
            <h3 className="text-sm font-semibold">Controller mapping</h3>
          </div>
        </div>
        <ToggleGroup
          value={[variant]}
          onValueChange={(values) => selectVariant(values[0] ?? null)}
          aria-label="Output controller"
          size="sm"
          variant="outline"
          spacing={0}
          className="hidden shrink-0 gap-0 @min-[52rem]/mapping:flex"
        >
          {CONTROLLER_VARIANTS.map((item) => (
            <ToggleGroupItem key={item} value={item} className="aria-pressed:bg-primary/15 aria-pressed:text-primary">
              {CONTROLLER_VARIANT_NAMES[item]}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
        <div className="@min-[52rem]/mapping:hidden">
          <Select value={variant} onValueChange={selectVariant}>
            <SelectTrigger
              size="sm"
              aria-label="Output controller"
              className="rounded-md border-border bg-background"
            >
              <SelectValue>
                <ControllerVariantIcon variant={variant} />
                {CONTROLLER_VARIANT_NAMES[variant]}
              </SelectValue>
            </SelectTrigger>
            <SelectContent align="start" className="w-48">
              <SelectGroup>
                {CONTROLLER_VARIANTS.map((item) => (
                  <SelectItem key={item} value={item}>
                    <ControllerVariantIcon variant={item} />
                    {CONTROLLER_VARIANT_NAMES[item]}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        </div>
        <Label className="ms-auto flex items-center gap-2 text-xs text-muted-foreground">
          Controller layout
          <Select
            value={controllerLayout}
            onValueChange={(value) => {
              if (isControllerLayout(value)) setControllerLayout(value);
            }}
          >
            <SelectTrigger className="h-8 rounded-md border-border bg-background px-2 text-xs text-foreground">
              <SelectValue className="ps-1">{controller.label}</SelectValue>
            </SelectTrigger>
            <SelectContent align="start" alignItemWithTrigger={false} className="w-60 min-w-(--anchor-width)">
              <SelectGroup>
                {CONTROLLER_LAYOUTS.map(({ value, label, image: Icon }) => (
                  <SelectItem key={value} value={value}>
                    {Icon ? <Icon className="size-5" /> : <GameControllerIcon className="size-5" />}
                    {label}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        </Label>
      </div>

      <div className="flex flex-col gap-4 p-3 @sm/mapping:p-4 mapping-preview:flex-row mapping-preview:gap-6">
        <div className="flex min-w-0 flex-wrap items-start gap-3 mapping-preview:shrink-0 mapping-preview:flex-col">
          {groups.map((group) => (
            <section
              key={group.title}
              className="w-fit max-w-full rounded-xl border bg-primary p-2"
            >
              <h4 className="px-2 py-1 text-xs font-semibold text-primary-foreground">
                {group.title}
              </h4>
              <div className="grid grid-cols-[max-content] @md/mapping:grid-cols-[repeat(2,max-content)]">
                {group.title === "Sticks" && group.controls.map((button) =>
                  stickRow(button === "STICK_L" ? "left" : "right"),
                )}
                {group.controls.map(mappingRow)}
              </div>
            </section>
          ))}
        </div>
        <div className="order-first flex min-w-0 flex-wrap items-center gap-3 rounded-lg bg-muted/30 px-3 py-2.5 mapping-preview:sticky mapping-preview:top-4 mapping-preview:order-last mapping-preview:flex-1 mapping-preview:flex-col mapping-preview:flex-nowrap mapping-preview:self-start mapping-preview:gap-0 mapping-preview:bg-transparent mapping-preview:p-4 mapping-preview:text-center">
          {variant !== "pro" ? (
            <div className="h-10 w-16 shrink-0 mapping-preview:h-40 mapping-preview:w-full mapping-preview:max-w-80">
              <ControllerPreview variant={variant} />
            </div>
          ) : ControllerImage === null ? (
            <GameControllerIcon
              weight="light"
              className="size-10 shrink-0 text-muted-foreground mapping-preview:mb-3 mapping-preview:h-56 mapping-preview:w-full mapping-preview:max-w-112"
            />
          ) : (
            <ControllerImage
              role="img"
              aria-label={`${controller.label} controller layout`}
              viewBox="0 12 64 40"
              width={64}
              height={40}
              className="h-auto w-10 shrink-0 opacity-80 brightness-0 mapping-preview:w-full mapping-preview:max-w-112 dark:invert"
            />
          )}
          <div className="min-w-0 flex-1 mapping-preview:flex-none">
            <p className="text-sm font-semibold">
              {variant === "pro" ? controller.label : CONTROLLER_VARIANT_NAMES[variant]}
            </p>
            <p className="mt-1 text-xs text-muted-foreground mapping-preview:max-w-64">
              Use the dropdowns or the controller buttons beside each mapping.
            </p>
          </div>
          {listeningTarget !== null && (
            <div
              role="status"
              className="flex items-center gap-2 rounded-lg bg-primary/10 px-3 py-1.5 text-xs font-medium text-primary mapping-preview:mt-4"
            >
              <SpinnerGapIcon className="shrink-0 animate-spin" />
              Press a button for {BUTTON_LABELS[listeningTarget]}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
