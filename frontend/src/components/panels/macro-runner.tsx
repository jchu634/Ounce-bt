import { useState } from "react";
import { Link } from "@tanstack/react-router";
import {
  FilePlusIcon,
  MagnifyingGlassIcon,
  PauseIcon,
  PencilSimpleIcon,
  PlayIcon,
  StopIcon,
  WarningIcon,
} from "@phosphor-icons/react";
import { Button } from "@/src/components/ui/button";
import { useMacroRunner } from "@/src/hooks/use-macro-runner";
import { useSocket } from "@/src/hooks/use-socket";
import { Input } from "@/src/components/ui/input";
import { Label } from "@/src/components/ui/label";
import { cn } from "cn";

export function MacroRunPanel({
  names,
  listError,
  onRetry,
  selected,
  onSelect,
  onCreate,
  fillHeight = false,
}: {
  names: string[];
  listError: string | null;
  onRetry: () => void;
  selected: string | null;
  onSelect: (name: string) => void;
  onCreate?: () => void;
  fillHeight?: boolean;
}) {
  const [search, setSearch] = useState("");
  const { macro, macroActive, isPaused, startByName, pause, resume, cancel } = useMacroRunner();
  const { lastError, clearError } = useSocket();

  const wsError = lastError !== null && lastError.message !== "" ? lastError : null;
  const normalizedSearch = search.trim().toLocaleLowerCase();
  const filteredNames =
    normalizedSearch === ""
      ? names
      : names.filter((name) => name.toLocaleLowerCase().includes(normalizedSearch));

  return (
    <section
      className={cn(
        "flex w-full min-w-0 flex-col gap-3 text-left",
        fillHeight && "h-full min-h-0 gap-2",
      )}
    >
      <div className="flex shrink-0 items-start justify-between gap-2">
        <h2 className="text-lg font-semibold text-foreground">Macros</h2>

        <Button
          render={<Link to="/macros" />}
          nativeButton={false}
          variant="outline"
          size="sm"
          className={fillHeight ? "h-7" : undefined}
        >
          <PencilSimpleIcon size={14} /> Edit macros
        </Button>
      </div>

      {wsError !== null && (
        <div
          role="alert"
          className="flex items-start gap-2 rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-foreground"
        >
          <WarningIcon size={16} className="mt-0.5 shrink-0 text-destructive" />
          <p className="flex-1">
            {wsError.message}
            {wsError.detail ? ` — ${wsError.detail}` : ""}
          </p>
          <Button size="xs" variant="ghost" onClick={clearError}>
            Dismiss
          </Button>
        </div>
      )}

      <div
        className={cn(
          "flex min-h-28 flex-col rounded-md border border-border bg-muted/30 p-2",
          fillHeight && "flex-1",
        )}
      >
        <div className="mb-2 flex shrink-0 items-center gap-2">
          <Label className="relative min-w-0 flex-1">
            <span className="sr-only">Search macros</span>
            <MagnifyingGlassIcon
              size={14}
              className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-muted-foreground"
            />
            <Input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search macros"
              className="h-8 w-full rounded-md border border-input bg-background pr-3 pl-8 text-sm outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"
            />
          </Label>
          {isPaused ? (
            <Button size="sm" variant="outline" onClick={resume}>
              <PlayIcon size={14} weight="fill" /> Resume
            </Button>
          ) : (
            <Button size="sm" variant="outline" onClick={pause} disabled={!macroActive}>
              <PauseIcon size={14} weight="fill" /> Pause
            </Button>
          )}
          <Button size="sm" variant="destructive" onClick={cancel} disabled={!macroActive}>
            <StopIcon size={14} weight="fill" /> Stop
          </Button>
        </div>
        {listError !== null ? (
          <div className="flex flex-1 flex-col items-center gap-2 rounded-md py-6 text-sm">
            <WarningIcon size={20} className="text-destructive" />
            <p>{listError}</p>
            <Button size="xs" variant="outline" onClick={onRetry}>
              Retry
            </Button>
          </div>
        ) : names.length === 0 ? (
          <div className="flex flex-1 flex-col items-center gap-2 rounded-md border border-dashed border-border py-6 text-sm text-muted-foreground">
            <p>No macros yet.</p>
            {onCreate !== undefined && (
              <Button size="xs" variant="outline" onClick={onCreate}>
                <FilePlusIcon size={14} /> New macro
              </Button>
            )}
          </div>
        ) : filteredNames.length === 0 ? (
          <div className="flex flex-1 items-center justify-center rounded-md py-6 text-sm text-muted-foreground">
            No macros match "{search.trim()}".
          </div>
        ) : (
          <ul
            className={cn(
              "app-scrollbar flex flex-col gap-2 overflow-y-auto overscroll-contain",
              fillHeight ? "min-h-0 flex-1 basis-0" : "max-h-42",
            )}
          >
            {filteredNames.map((name) => {
              const isActive = macroActive && macro?.name === name;
              return (
                <li
                  key={name}
                  className={cn(
                    "relative flex shrink-0 items-center gap-2 rounded-md border border-border px-3 py-2 text-sm focus-within:bg-muted/60 hover:bg-muted/60",
                    selected === name ? "bg-muted/60" : isActive ? "bg-primary/5" : "bg-background",
                  )}
                >
                  <Button
                    variant="ghost"
                    className="relative z-0 h-auto min-w-0 flex-1 cursor-pointer justify-start rounded-none border-0 bg-transparent px-1 py-0 text-left font-mono font-normal after:absolute after:inset-0 after:rounded-md hover:bg-transparent focus-visible:after:ring-2 focus-visible:after:ring-ring active:translate-y-0"
                    aria-pressed={selected === name}
                    onClick={() => onSelect(name)}
                    title={name}
                  >
                    <span className="block truncate">{name}</span>
                  </Button>
                  <Button
                    render={<Link to="/macros" hash={name} />}
                    nativeButton={false}
                    size="xs"
                    variant="outline"
                    className="relative z-10"
                    aria-label={`Edit ${name}`}
                  >
                    <PencilSimpleIcon size={12} /> Edit
                  </Button>
                  {isActive && isPaused && (
                    <span className="text-xs text-muted-foreground">paused</span>
                  )}
                  <Button
                    size="xs"
                    className="relative z-10"
                    variant={isActive ? "secondary" : "default"}
                    disabled={macroActive && !isActive && !isPaused}
                    onClick={() => startByName(name)}
                    title={isActive ? "Restart" : "Run"}
                  >
                    <PlayIcon size={12} weight="fill" />
                    {isActive ? "Restart" : "Run"}
                  </Button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </section>
  );
}
