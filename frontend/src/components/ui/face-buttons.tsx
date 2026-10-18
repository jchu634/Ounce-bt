import { useState, type MouseEventHandler, type PointerEvent } from "react";
import { cn } from "cn";
import { Button } from "@/src/components/ui/button";
import {
  SwitchButtons,
  SwitchButtonsUp,
  SwitchButtonsDown,
  SwitchButtonsLeft,
  SwitchButtonsRight,
} from "@/src/assets/input-prompts/switch";

export type FaceButtonName = "A" | "B" | "X" | "Y";

export type FaceButtonsProps = {
  className?: string;
  disabled?: boolean;
  "aria-label"?: string;
  pressedButtons?: ReadonlySet<string>;
  onXClick?: MouseEventHandler<HTMLButtonElement>;
  onBClick?: MouseEventHandler<HTMLButtonElement>;
  onYClick?: MouseEventHandler<HTMLButtonElement>;
  onAClick?: MouseEventHandler<HTMLButtonElement>;
  onButtonPress?: (button: FaceButtonName) => void;
  onButtonRelease?: (button: FaceButtonName) => void;
};

const buttons = [
  { name: "X", handler: "onXClick", icon: SwitchButtonsUp, x: 24, y: 8 },
  { name: "B", handler: "onBClick", icon: SwitchButtonsDown, x: 24, y: 40 },
  { name: "Y", handler: "onYClick", icon: SwitchButtonsLeft, x: 8, y: 24 },
  { name: "A", handler: "onAClick", icon: SwitchButtonsRight, x: 40, y: 24 },
] satisfies {
  name: FaceButtonName;
  handler: `on${FaceButtonName}Click`;
  icon: typeof SwitchButtons;
  x: number;
  y: number;
}[];

export function FaceButtons({
  className,
  disabled = false,
  "aria-label": label = "Face buttons",
  pressedButtons,
  onButtonPress,
  onButtonRelease,
  ...clickHandlers
}: FaceButtonsProps) {
  const [hovered, setHovered] = useState<FaceButtonName | null>(null);
  const selected = !disabled
    ? buttons.find(({ name }) => name === hovered || pressedButtons?.has(name))
    : undefined;
  const Icon = selected?.icon ?? SwitchButtons;

  const releasePointer = (
    event: PointerEvent<HTMLButtonElement>,
    name: FaceButtonName,
  ) => {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    onButtonRelease?.(name);
  };

  return (
    <div
      role="group"
      aria-label={label}
      className={cn(
        "relative inline-block size-32 shrink-0 align-middle text-current",
        disabled && "opacity-50",
        className,
      )}
    >
      <Icon
        className="pointer-events-none absolute inset-0 size-full"
        aria-hidden="true"
      />
      {buttons.map(({ name, handler, x, y }) => (
        <Button
          key={name}
          type="button"
          variant="ghost_no_hover"
          size="icon"
          aria-label={name}
          aria-pressed={pressedButtons?.has(name) ?? false}
          disabled={disabled}
          className="absolute size-1/4 cursor-pointer touch-none rounded-full border-0 bg-transparent p-0 hover:bg-transparent focus-visible:ring-0 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring disabled:cursor-default"
          style={{ left: `${(x / 64) * 100}%`, top: `${(y / 64) * 100}%` }}
          onPointerEnter={(event) => {
            if (event.pointerType !== "touch") setHovered(name);
          }}
          onPointerLeave={() => setHovered(null)}
          onPointerDown={(event) => {
            if (!onButtonPress || event.button !== 0) return;
            event.preventDefault();
            event.currentTarget.setPointerCapture(event.pointerId);
            onButtonPress(name);
          }}
          onPointerUp={(event) => releasePointer(event, name)}
          onPointerCancel={(event) => {
            setHovered(null);
            releasePointer(event, name);
          }}
          onLostPointerCapture={() => onButtonRelease?.(name)}
          onKeyDown={(event) => {
            if (!onButtonPress || (event.key !== " " && event.key !== "Enter"))
              return;
            event.preventDefault();
            if (!event.repeat) onButtonPress(name);
          }}
          onKeyUp={(event) => {
            if (
              !onButtonRelease ||
              (event.key !== " " && event.key !== "Enter")
            )
              return;
            event.preventDefault();
            onButtonRelease(name);
          }}
          onBlur={() => onButtonRelease?.(name)}
          onContextMenu={(event) => event.preventDefault()}
          onClick={clickHandlers[handler]}
        />
      ))}
    </div>
  );
}
