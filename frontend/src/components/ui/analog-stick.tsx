import { useCallback, useEffect, useRef, type PointerEvent } from "react";
import { cn } from "cn";
import { GenericButtonCircleFill } from "@/src/assets/input-prompts/generic";
import { clampStick, type StickPosition } from "@/src/lib/analog-stick";

export type AnalogStickProps = {
  value: StickPosition;
  onChange: (position: StickPosition | null) => void;
  onStickClick?: () => void;
  "aria-label": string;
  disabled?: boolean;
  className?: string;
};

/** Emits null when released, allowing another input source to resume control. */
export function AnalogStick({
  value,
  onChange,
  onStickClick,
  "aria-label": label,
  disabled = false,
  className,
}: AnalogStickProps) {
  const surface = useRef<HTMLDivElement>(null);
  const pointer = useRef<number | null>(null);
  const start = useRef<{ x: number; y: number; dragged: boolean } | null>(null);

  const release = useCallback(() => {
    const id = pointer.current;
    if (id === null) return;
    pointer.current = null;
    start.current = null;
    if (surface.current?.hasPointerCapture(id)) {
      surface.current.releasePointerCapture(id);
    }
    onChange(null);
  }, [onChange]);

  useEffect(() => {
    if (disabled) release();
  }, [disabled, release]);

  useEffect(() => {
    const onVisibilityChange = () => {
      if (document.hidden) release();
    };
    window.addEventListener("blur", release);
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      window.removeEventListener("blur", release);
      document.removeEventListener("visibilitychange", onVisibilityChange);
      release();
    };
  }, [release]);

  const move = (event: PointerEvent<HTMLDivElement>) => {
    if (disabled || pointer.current !== event.pointerId) return;
    const origin = start.current;
    if (origin === null) return;
    if (
      !origin.dragged &&
      Math.hypot(event.clientX - origin.x, event.clientY - origin.y) < 6
    )
      return;
    origin.dragged = true;
    const bounds = event.currentTarget.getBoundingClientRect();
    // The visible thumb radius is 18% of the pad, leaving 32% of travel.
    const radius = Math.min(bounds.width, bounds.height) * 0.32;
    if (radius <= 0) return;
    onChange(
      clampStick(
        (event.clientX - bounds.left - bounds.width / 2) / radius,
        (bounds.top + bounds.height / 2 - event.clientY) / radius,
      ),
    );
  };

  return (
    <div
      ref={surface}
      role="button"
      tabIndex={disabled ? -1 : 0}
      aria-label={label}
      aria-disabled={disabled}
      className={cn(
        "relative size-36 touch-none rounded-full border-2 border-border bg-muted/30 select-none",
        disabled ? "opacity-50" : "group cursor-grab active:cursor-grabbing",
        className,
      )}
      onPointerDown={(event) => {
        if (disabled || event.button !== 0 || pointer.current !== null) return;
        event.preventDefault();
        pointer.current = event.pointerId;
        start.current = { x: event.clientX, y: event.clientY, dragged: false };
        event.currentTarget.setPointerCapture(event.pointerId);
      }}
      onPointerMove={move}
      onPointerUp={(event) => {
        if (pointer.current !== event.pointerId) return;
        const clicked = start.current?.dragged === false;
        release();
        if (clicked) onStickClick?.();
      }}
      onPointerCancel={(event) => {
        if (pointer.current === event.pointerId) release();
      }}
      onLostPointerCapture={(event) => {
        if (pointer.current === event.pointerId) release();
      }}
      onKeyDown={(event) => {
        if (!disabled && (event.key === " " || event.key === "Enter"))
          event.preventDefault();
      }}
      onKeyUp={(event) => {
        if (disabled || (event.key !== " " && event.key !== "Enter")) return;
        event.preventDefault();
        onStickClick?.();
      }}
      onContextMenu={(event) => event.preventDefault()}
    >
      <GenericButtonCircleFill
        aria-hidden="true"
        className="pointer-events-none absolute size-[48%] -translate-x-1/2 -translate-y-1/2 text-foreground transition-colors group-hover:text-primary"
        style={{
          left: `${50 + value[0] * 32}%`,
          top: `${50 - value[1] * 32}%`,
        }}
      />
    </div>
  );
}
