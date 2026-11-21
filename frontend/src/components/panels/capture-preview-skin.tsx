import { useEffect, useState, type CSSProperties, type ReactNode } from "react";
import { Controls } from "@videojs/react";
import { ArrowsInIcon, ArrowsOutIcon, StopIcon } from "@phosphor-icons/react";
import { cn } from "cn";
import { Button } from "@/src/components/videojs/ui/button";
import { Container } from "@/src/components/videojs/ui/container";
import { MuteButton } from "@/src/components/videojs/ui/mute-button";
import { VolumeSlider } from "@/src/components/videojs/ui/volume-slider";

// Minor adaptation of the Video.js minimal skin with playback UI, gestures and hotkeys removed due to the live capture usecase.
export function CapturePreviewSkin({
  children,
  aspectRatio,
  capturing,
  onStop,
}: {
  children: ReactNode;
  aspectRatio: number;
  capturing: boolean;
  onStop: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const style: CSSProperties & { "--capture-aspect-ratio": number } = {
    "--capture-aspect-ratio": aspectRatio,
  };

  useEffect(() => {
    if (!expanded) return;

    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setExpanded(false);
    };

    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [expanded]);

  return (
    <Container
      className="aspect-(--capture-aspect-ratio) h-auto w-full max-w-[calc((100dvh-6rem)*var(--capture-aspect-ratio))] flex-none rounded-xl data-expanded:fixed data-expanded:inset-0 data-expanded:z-50 data-expanded:aspect-auto data-expanded:h-dvh data-expanded:w-dvw data-expanded:max-w-none data-expanded:rounded-none data-expanded:after:hidden"
      style={style}
      data-theme="minimal"
      data-preset="live-video"
      data-expanded={expanded ? "" : undefined}
      aria-label="Capture card preview"
    >
      {children}
      <Controls.Root>
        <Controls.Content
          className={cn(
            "absolute inset-x-0 bottom-0 z-30 flex items-center justify-between gap-3 bg-(image:--media-controls-gradient) px-3 pt-3 pb-2 text-media-controls-foreground transition-opacity duration-media-controls motion-reduce:transition-none",
            capturing &&
              "not-data-visible:pointer-events-none not-data-visible:opacity-0 focus-within:pointer-events-auto focus-within:opacity-100",
          )}
        >
          <Controls.Group aria-label="Playback controls" className="flex items-center gap-2">
            <Button
              type="button"
              onClick={onStop}
              disabled={!capturing}
              aria-label="Stop capture input"
              title="Stop capture input"
              className="disabled:cursor-not-allowed disabled:opacity-50"
            >
              <StopIcon size={20} weight="fill" aria-hidden />
            </Button>
            <MuteButton />
            <VolumeSlider className="w-22 flex-none" />
          </Controls.Group>
          <Controls.Group>
            <Button
              type="button"
              onClick={() => setExpanded((current) => !current)}
              aria-label={expanded ? "Exit expanded preview" : "Maximise preview"}
              aria-pressed={expanded}
              className="capture-action capture-fullscreen"
              title={expanded ? "Exit expanded preview" : "Maximise preview"}
            >
              {expanded ? (
                <ArrowsInIcon size={20} aria-hidden />
              ) : (
                <ArrowsOutIcon size={20} aria-hidden />
              )}
            </Button>
          </Controls.Group>
        </Controls.Content>
      </Controls.Root>
    </Container>
  );
}
