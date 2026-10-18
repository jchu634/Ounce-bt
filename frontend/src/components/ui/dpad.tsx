import { useState, type MouseEventHandler, type PointerEvent } from "react";
import { cn } from "cn";
import { Button } from "@/src/components/ui/button";
import {
  XboxDpadNone,
  XboxDpadUpOutline,
  XboxDpadDownOutline,
  XboxDpadLeftOutline,
  XboxDpadRightOutline,
} from "@/src/assets/input-prompts/xbox";

export type DpadDirection = "up" | "down" | "left" | "right";

export type DpadProps = {
  className?: string;
  disabled?: boolean;
  "aria-label"?: string;
  onUpClick?: MouseEventHandler<HTMLButtonElement>;
  onDownClick?: MouseEventHandler<HTMLButtonElement>;
  onLeftClick?: MouseEventHandler<HTMLButtonElement>;
  onRightClick?: MouseEventHandler<HTMLButtonElement>;
  onDirectionPress?: (direction: DpadDirection) => void;
  onDirectionRelease?: (direction: DpadDirection) => void;
};

// prettier-ignore
const directions = [
  { name: "up",   handler: "onUpClick",   icon: XboxDpadUpOutline,    x: 23, y: 8, width: 18, height: 15, },
  { name: "down", handler: "onDownClick", icon: XboxDpadDownOutline,  x: 23, y: 41, width: 18, height: 15, },
  { name: "left", handler: "onLeftClick", icon: XboxDpadLeftOutline,  x: 8, y: 23, width: 15, height: 18, },
  { name: "right", handler: "onRightClick", icon: XboxDpadRightOutline, x: 41, y: 23, width: 15, height: 18, },
] satisfies {
  name: DpadDirection;
  handler: `on${Capitalize<DpadDirection>}Click`;
  icon: typeof XboxDpadNone;
  x: number;
  y: number;
  width: number;
  height: number;
}[];

export function Dpad({
  className,
  disabled = false,
  "aria-label": label = "Directional pad",
  onDirectionPress,
  onDirectionRelease,
  ...handlers
}: DpadProps) {
  const [hovered, setHovered] = useState<DpadDirection | null>(null);
  const releasePointer = (
    event: PointerEvent<HTMLButtonElement>,
    direction: DpadDirection,
  ) => {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    onDirectionRelease?.(direction);
  };
  const Icon = disabled
    ? XboxDpadNone
    : (directions.find(({ name }) => name === hovered)?.icon ?? XboxDpadNone);

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
      {directions.map(({ name, handler, x, y, width, height }) => (
        <Button
          key={name}
          type="button"
          variant="ghost_no_hover"
          size="icon"
          aria-label={`D-pad ${name}`}
          disabled={disabled}
          className="absolute cursor-pointer touch-none rounded-sm border-0 bg-transparent p-0 hover:bg-transparent focus-visible:ring-0 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring disabled:cursor-default"
          style={{
            left: `${(x / 64) * 100}%`,
            top: `${(y / 64) * 100}%`,
            width: `${(width / 64) * 100}%`,
            height: `${(height / 64) * 100}%`,
          }}
          onPointerEnter={(event) => {
            if (event.pointerType !== "touch") setHovered(name);
          }}
          onPointerLeave={() => setHovered(null)}
          onPointerDown={(event) => {
            if (!onDirectionPress || event.button !== 0) return;
            event.preventDefault();
            event.currentTarget.setPointerCapture(event.pointerId);
            onDirectionPress(name);
          }}
          onPointerUp={(event) => releasePointer(event, name)}
          onPointerCancel={(event) => {
            setHovered(null);
            releasePointer(event, name);
          }}
          onLostPointerCapture={() => onDirectionRelease?.(name)}
          onKeyDown={(event) => {
            if (
              !onDirectionPress ||
              (event.key !== " " && event.key !== "Enter")
            ) {
              return;
            }
            event.preventDefault();
            if (!event.repeat) onDirectionPress(name);
          }}
          onKeyUp={(event) => {
            if (
              !onDirectionRelease ||
              (event.key !== " " && event.key !== "Enter")
            )
              return;
            event.preventDefault();
            onDirectionRelease(name);
          }}
          onBlur={() => onDirectionRelease?.(name)}
          onContextMenu={(event) => event.preventDefault()}
          onClick={handlers[handler]}
        />
      ))}
    </div>
  );
}
