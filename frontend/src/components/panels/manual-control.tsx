import { useCallback, useEffect, useRef, useState } from "react";
import type { KeyboardEvent, PointerEvent, ReactNode } from "react";
import {
  SwitchButtonHome,
  SwitchButtonHomeOutline,
  SwitchButtonL,
  SwitchButtonLOutline,
  SwitchButtonR,
  SwitchButtonROutline,
  SwitchButtonSync,
  SwitchButtonSyncOutline,
  SwitchButtonZl,
  SwitchButtonZlOutline,
  SwitchButtonZr,
  SwitchButtonZrOutline,
  SwitchStickLDown,
  SwitchStickLLeft,
  SwitchStickLPress,
  SwitchStickLRight,
  SwitchStickLUp,
  SwitchStickRDown,
  SwitchStickRLeft,
  SwitchStickRPress,
  SwitchStickRRight,
  SwitchStickRUp,
} from "@/src/assets/input-prompts/switch";
import { Dpad, type DpadDirection } from "@/src/components/ui/dpad";
import {
  FaceButtons,
  type FaceButtonName,
} from "@/src/components/ui/face-buttons";
import { AnalogStick } from "@/src/components/ui/analog-stick";
import type { StickPosition } from "@/src/lib/analog-stick";
import { useSocket } from "@/src/hooks/use-socket";
import type { ButtonName } from "@/src/lib/types";
import { Button } from "@/src/components/ui/button";
import { Switch } from "@/src/components/ui/switch";
import { cn } from "cn";

type ControlButtonProps = {
  icon: ReactNode;
  pressedIcon?: ReactNode;
  accessibleLabel: string;
  pressed: boolean;
  disabled: boolean;
  className?: string;
  onPress: () => void;
  onRelease: () => void;
};

type ButtonVisual = { button: ButtonName } & Pick<
  ControlButtonProps,
  "accessibleLabel" | "icon" | "pressedIcon"
>;

type StickSide = "left" | "right";
type StickDirection = "up" | "down" | "left" | "right";
type StickInput = `${StickSide}-${StickDirection}`;
type StickMode = "drag" | "buttons";
const STICK_MODES_KEY = "manual-control-stick-modes";

function loadStickMode(): StickMode {
  try {
    const saved: unknown = JSON.parse(
      localStorage.getItem(STICK_MODES_KEY) ?? "null",
    );
    if (saved === "drag" || saved === "buttons") return saved;
    if (typeof saved !== "object" || saved === null) return "drag";
    return ("left" in saved && saved.left === "buttons") ||
      ("right" in saved && saved.right === "buttons")
      ? "buttons"
      : "drag";
  } catch {
    return "drag";
  }
}

const STICK_BUTTONS = {
  left: "STICK_L",
  right: "STICK_R",
} satisfies Record<StickSide, ButtonName>;

const DPAD_BUTTONS = {
  up: "UP",
  down: "DOWN",
  left: "LEFT",
  right: "RIGHT",
} satisfies Record<DpadDirection, ButtonName>;

function stickPosition(
  side: StickSide,
  inputs: ReadonlySet<StickInput>,
): [number, number] {
  const x =
    Number(inputs.has(`${side}-right`)) - Number(inputs.has(`${side}-left`));
  const y =
    Number(inputs.has(`${side}-up`)) - Number(inputs.has(`${side}-down`));
  return [x, y];
}

function ControlButton({
  icon,
  pressedIcon = icon,
  accessibleLabel,
  pressed,
  disabled,
  className,
  onPress,
  onRelease,
}: ControlButtonProps) {
  const handlePointerDown = (event: PointerEvent<HTMLButtonElement>) => {
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    onPress();
  };

  const handlePointerEnd = (event: PointerEvent<HTMLButtonElement>) => {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    onRelease();
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if ((event.key === " " || event.key === "Enter") && !event.repeat) {
      event.preventDefault();
      onPress();
    }
  };

  const handleKeyUp = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === " " || event.key === "Enter") {
      event.preventDefault();
      onRelease();
    }
  };

  return (
    <Button
      variant="ghost_no_hover"
      size="icon-lg"
      aria-label={accessibleLabel}
      aria-pressed={pressed}
      disabled={disabled}
      className={cn(
        "relative size-14 touch-none rounded-xl border-0 bg-transparent p-0 text-foreground transition-[transform,color] hover:bg-transparent hover:text-primary focus-visible:ring-3 focus-visible:ring-ring/30 focus-visible:outline-none active:translate-y-0 disabled:pointer-events-none disabled:opacity-40",
        pressed && "scale-90 text-primary",
        className,
      )}
      onPointerDown={handlePointerDown}
      onPointerUp={handlePointerEnd}
      onPointerCancel={handlePointerEnd}
      onLostPointerCapture={onRelease}
      onKeyDown={handleKeyDown}
      onKeyUp={handleKeyUp}
      onContextMenu={(event) => event.preventDefault()}
    >
      <span className="absolute inset-0" aria-hidden="true">
        {pressed ? pressedIcon : icon}
      </span>
    </Button>
  );
}

const BUTTON_GROUPS = {
  shoulders: [
    {
      button: "ZL",
      accessibleLabel: "ZL",
      icon: <SwitchButtonZlOutline className="size-full" />,
      pressedIcon: <SwitchButtonZl className="size-full" />,
    },
    {
      button: "L",
      accessibleLabel: "L",
      icon: <SwitchButtonLOutline className="size-full" />,
      pressedIcon: <SwitchButtonL className="size-full" />,
    },
    {
      button: "R",
      accessibleLabel: "R",
      icon: <SwitchButtonROutline className="size-full" />,
      pressedIcon: <SwitchButtonR className="size-full" />,
    },
    {
      button: "ZR",
      accessibleLabel: "ZR",
      icon: <SwitchButtonZrOutline className="size-full" />,
      pressedIcon: <SwitchButtonZr className="size-full" />,
    },
  ],
  system: [
    {
      button: "CAPTURE",
      accessibleLabel: "Capture",
      icon: <SwitchButtonSyncOutline className="size-full" />,
      pressedIcon: <SwitchButtonSync className="size-full" />,
    },
    {
      button: "HOME",
      accessibleLabel: "Home",
      icon: <SwitchButtonHomeOutline className="size-full" />,
      pressedIcon: <SwitchButtonHome className="size-full" />,
    },
  ],
} satisfies Record<string, ReadonlyArray<ButtonVisual>>;

export function ManualControl() {
  const { connection, send, status } = useSocket();
  const heldButtons = useRef<Set<ButtonName>>(new Set());
  const heldSticks = useRef<Set<StickInput>>(new Set());
  const analogSticks = useRef<Record<StickSide, StickPosition | null>>({
    left: null,
    right: null,
  });
  const [analogPositions, setAnalogPositions] = useState(analogSticks.current);
  const [stickMode, setStickMode] = useState(loadStickMode);
  const [pressedButtons, setPressedButtons] = useState<Set<ButtonName>>(
    () => new Set(),
  );
  const [pressedSticks, setPressedSticks] = useState<Set<StickInput>>(
    () => new Set(),
  );
  const disabled = connection !== "open" || status?.mode === "macro";

  useEffect(() => {
    try {
      localStorage.setItem(STICK_MODES_KEY, JSON.stringify(stickMode));
    } catch {
      // Controls still work when browser storage is unavailable.
      console.log("Localstorage sticks setting write failed");
    }
  }, [stickMode]);

  const sendState = useCallback(() => {
    send({
      type: "state",
      buttons: [...heldButtons.current],
      left:
        analogSticks.current.left ?? stickPosition("left", heldSticks.current),
      right:
        analogSticks.current.right ??
        stickPosition("right", heldSticks.current),
    });
  }, [send]);

  const releaseAll = useCallback(() => {
    if (
      heldButtons.current.size === 0 &&
      heldSticks.current.size === 0 &&
      analogSticks.current.left === null &&
      analogSticks.current.right === null
    )
      return;
    heldButtons.current = new Set();
    heldSticks.current = new Set();
    analogSticks.current = { left: null, right: null };
    setAnalogPositions(analogSticks.current);
    setPressedButtons(new Set());
    setPressedSticks(new Set());
    sendState();
  }, [sendState]);

  useEffect(() => {
    if (disabled) releaseAll();
  }, [disabled, releaseAll]);

  useEffect(() => {
    window.addEventListener("blur", releaseAll);
    return () => {
      window.removeEventListener("blur", releaseAll);
      releaseAll();
    };
  }, [releaseAll]);

  const press = useCallback(
    (button: ButtonName) => {
      if (disabled || heldButtons.current.has(button)) return;
      const next = new Set(heldButtons.current).add(button);
      heldButtons.current = next;
      setPressedButtons(next);
      sendState();
    },
    [disabled, sendState],
  );

  const release = useCallback(
    (button: ButtonName) => {
      if (!heldButtons.current.has(button)) return;
      const next = new Set(heldButtons.current);
      next.delete(button);
      heldButtons.current = next;
      setPressedButtons(next);
      sendState();
    },
    [sendState],
  );

  const controlProps = (button: ButtonName) => ({
    pressed: pressedButtons.has(button),
    disabled,
    onPress: () => press(button),
    onRelease: () => release(button),
  });

  const changeAnalogStick = useCallback(
    (side: StickSide, position: StickPosition | null) => {
      if (disabled && position !== null) return;
      const previous = analogSticks.current[side];
      if (
        previous === position ||
        (previous !== null &&
          position !== null &&
          previous[0] === position[0] &&
          previous[1] === position[1])
      )
        return;
      analogSticks.current = { ...analogSticks.current, [side]: position };
      setAnalogPositions(analogSticks.current);
      sendState();
    },
    [disabled, sendState],
  );

  const changeLeftStick = useCallback(
    (position: StickPosition | null) => {
      changeAnalogStick("left", position);
    },
    [changeAnalogStick],
  );

  const changeRightStick = useCallback(
    (position: StickPosition | null) => {
      changeAnalogStick("right", position);
    },
    [changeAnalogStick],
  );

  const changeStickMode = (mode: StickMode) => {
    if (stickMode === mode) return;
    heldSticks.current = new Set();
    setPressedSticks(new Set());
    analogSticks.current = { left: null, right: null };
    setAnalogPositions(analogSticks.current);
    const nextButtons = new Set(heldButtons.current);
    nextButtons.delete(STICK_BUTTONS.left);
    nextButtons.delete(STICK_BUTTONS.right);
    heldButtons.current = nextButtons;
    setPressedButtons(nextButtons);
    sendState();
    setStickMode(mode);
  };

  const stickControlProps = (side: StickSide, direction: StickDirection) => {
    const input: StickInput = `${side}-${direction}`;
    return {
      pressed: pressedSticks.has(input),
      disabled,
      onPress: () => {
        if (disabled || heldSticks.current.has(input)) return;
        const next = new Set(heldSticks.current).add(input);
        heldSticks.current = next;
        setPressedSticks(next);
        sendState();
      },
      onRelease: () => {
        if (!heldSticks.current.has(input)) return;
        const next = new Set(heldSticks.current);
        next.delete(input);
        heldSticks.current = next;
        setPressedSticks(next);
        sendState();
      },
    };
  };

  return (
    <section className="w-full">
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg font-semibold">Manual control</h2>
      </div>

      <div className="mx-auto flex max-w-xl flex-col gap-2 rounded-md border border-border bg-card p-3 text-card-foreground shadow-sm">
        <div className="grid grid-cols-4 gap-1" aria-label="Triggers">
          {BUTTON_GROUPS.shoulders.map(({ button, ...visual }) => (
            <ControlButton
              key={button}
              {...controlProps(button)}
              {...visual}
              className="h-12 w-full"
            />
          ))}
        </div>

        <div className="flex w-full items-center justify-between gap-3">
          <Dpad
            className="size-28"
            disabled={disabled}
            onDirectionPress={(direction) => press(DPAD_BUTTONS[direction])}
            onDirectionRelease={(direction) => release(DPAD_BUTTONS[direction])}
          />

          <div className="flex flex-row gap-0">
            {BUTTON_GROUPS.system.map(({ button, ...visual }) => (
              <ControlButton
                key={button}
                {...controlProps(button)}
                {...visual}
                className="size-12"
              />
            ))}
          </div>

          <FaceButtons
            className="size-28"
            disabled={disabled}
            pressedButtons={pressedButtons}
            onButtonPress={(button: FaceButtonName) => press(button)}
            onButtonRelease={(button: FaceButtonName) => release(button)}
          />
        </div>

        <div
          className="grid grid-cols-2 justify-items-center gap-4 border-t border-border pt-4"
          aria-label="Analog sticks"
        >
          {(["left", "right"] satisfies StickSide[]).map((side) => (
            <div key={side} className="flex flex-col items-center gap-3">
              {stickMode === "drag" ? (
                <AnalogStick
                  aria-label={`${side} stick, drag to move or click for ${side === "left" ? "L3" : "R3"}`}
                  value={analogPositions[side] ?? [0, 0]}
                  onChange={
                    side === "left" ? changeLeftStick : changeRightStick
                  }
                  onStickClick={() => {
                    press(STICK_BUTTONS[side]);
                    release(STICK_BUTTONS[side]);
                  }}
                  disabled={disabled}
                />
              ) : (
                <div className="grid size-36 grid-cols-3 grid-rows-3 place-items-center">
                  <ControlButton
                    {...stickControlProps(side, "up")}
                    accessibleLabel={`${side} stick up`}
                    icon={
                      side === "left" ? (
                        <SwitchStickLUp className="size-full" />
                      ) : (
                        <SwitchStickRUp className="size-full" />
                      )
                    }
                    className="col-start-2 row-start-1 size-12"
                  />
                  <ControlButton
                    {...stickControlProps(side, "left")}
                    accessibleLabel={`${side} stick left`}
                    icon={
                      side === "left" ? (
                        <SwitchStickLLeft className="size-full" />
                      ) : (
                        <SwitchStickRLeft className="size-full" />
                      )
                    }
                    className="col-start-1 row-start-2 size-12"
                  />
                  <ControlButton
                    {...controlProps(STICK_BUTTONS[side])}
                    accessibleLabel={`${side} stick click`}
                    icon={
                      side === "left" ? (
                        <SwitchStickLPress className="size-full" />
                      ) : (
                        <SwitchStickRPress className="size-full" />
                      )
                    }
                    className="col-start-2 row-start-2 size-12"
                  />
                  <ControlButton
                    {...stickControlProps(side, "right")}
                    accessibleLabel={`${side} stick right`}
                    icon={
                      side === "left" ? (
                        <SwitchStickLRight className="size-full" />
                      ) : (
                        <SwitchStickRRight className="size-full" />
                      )
                    }
                    className="col-start-3 row-start-2 size-12"
                  />
                  <ControlButton
                    {...stickControlProps(side, "down")}
                    accessibleLabel={`${side} stick down`}
                    icon={
                      side === "left" ? (
                        <SwitchStickLDown className="size-full" />
                      ) : (
                        <SwitchStickRDown className="size-full" />
                      )
                    }
                    className="col-start-2 row-start-3 size-12"
                  />
                </div>
              )}
            </div>
          ))}
        </div>
        <label className="mx-auto flex items-center gap-2 text-xs text-muted-foreground">
          <span>Drag</span>
          <Switch
            size="sm"
            checked={stickMode === "buttons"}
            onCheckedChange={(checked) =>
              changeStickMode(checked ? "buttons" : "drag")
            }
            aria-label="Stick input style"
          />
          <span>Buttons</span>
        </label>
      </div>
    </section>
  );
}
