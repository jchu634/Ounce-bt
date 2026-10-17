"use client";

import "../styles/base.css";
import "../styles/audio/theme.css";
import "../styles/video/captions.css";
import "../styles/video/theme.css";
import { Title as TitlePrimitive } from "@videojs/react";

import { resolveClassName } from "@/src/lib/resolve-class-name";
import { cn } from "cn";

export type TitleProps = Omit<TitlePrimitive.Props, "children">;

export function Title({ className, ...props }: TitleProps = {}) {
  return (
    <TitlePrimitive
      className={(state) =>
        cn(
          "pointer-events-none absolute inset-x-0 top-0 isolate z-20",
          "px-6 pt-2.5 text-media font-medium tracking-[-0.0125em] wrap-anywhere text-media-controls-foreground text-shadow-media",
          "media-md:px-6 media-md:pt-4 media-md:text-media-xl",
          "origin-top duration-media-controls-enter ease-out",
          "not-data-visible:-translate-y-media-hidden-offset not-data-visible:opacity-0 not-data-visible:duration-media-controls",
          "pointer-fine:not-data-visible:blur-media-hidden",
          "flex min-h-[calc(var(--media-control-size)+(--spacing(2)))] items-center",
          "media-max-lg:pe-36",
          "transition-[filter,opacity,scale,translate]",
          "not-data-visible:scale-media-hidden",
          resolveClassName(className, state),
        )
      }
      {...props}
    />
  );
}
