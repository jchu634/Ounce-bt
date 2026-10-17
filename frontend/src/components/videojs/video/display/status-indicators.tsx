import type { ComponentProps } from "react";

import { SeekIndicator } from "@/src/components/videojs/ui/seek-indicator";
import { StatusAnnouncer } from "@/src/components/videojs/ui/status-announcer";
import {
  PlaybackStatusIndicator,
  StatusIndicator,
} from "@/src/components/videojs/ui/status-indicator";
import { VolumeIndicator } from "@/src/components/videojs/ui/volume-indicator";
import { cn } from "cn";

export type VideoStatusIndicatorsProps = Omit<
  ComponentProps<"div">,
  "children"
>;

export function VideoStatusIndicators({
  className,
  ...props
}: VideoStatusIndicatorsProps = {}) {
  return (
    <>
      <StatusAnnouncer />
      <div
        className={cn(
          "pointer-events-none absolute inset-0 z-20 grid grid-cols-3 items-center justify-items-center",
          "text-media-controls-foreground",
          className,
        )}
        {...props}
      >
        <VolumeIndicator />
        <StatusIndicator />
        <SeekIndicator />
        <PlaybackStatusIndicator />
      </div>
    </>
  );
}
