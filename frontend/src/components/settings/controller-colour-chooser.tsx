import { EyedropperIcon } from "@phosphor-icons/react";
import { useState } from "react";
import { HexColorPicker } from "react-colorful";
import { Button } from "@/src/components/ui/button";
import { Popover, PopoverContent, PopoverTitle, PopoverTrigger } from "@/src/components/ui/popover";
import { Separator } from "@/src/components/ui/separator";
import { Input } from "@/src/components/ui/input";
import { expandHexColour, FIXED_COLOURS } from "@/src/lib/controller-colours";

export function ControllerColourChooser({
  id,
  label,
  colour,
  recent,
  onChange,
}: {
  id: string;
  label: string;
  colour: string;
  recent: string[];
  onChange: (colour: string) => void;
}) {
  const [hex, setHex] = useState<string | null>(null);
  const [invalid, setInvalid] = useState(false);

  function commitHex() {
    try {
      const normalized = expandHexColour((hex ?? colour).trim().replace(/^#?/, "#"));
      onChange(normalized);
      setHex(null);
      setInvalid(false);
    } catch {
      setInvalid(true);
    }
  }

  function picker(pickerId: string) {
    return (
      <div className="space-y-3">
        <HexColorPicker
          color={colour}
          onChange={(value) => {
            onChange(value);
            setHex(null);
            setInvalid(false);
          }}
          aria-label={`${label} colour picker`}
          style={{ width: "100%", height: 120 }}
        />

        <label className="flex items-center gap-2 text-xs" htmlFor={`${pickerId}-hex`}>
          Hex
          <Input
            id={`${pickerId}-hex`}
            aria-label={`${label} hex colour`}
            aria-invalid={invalid}
            aria-describedby={invalid ? `${pickerId}-error` : undefined}
            className="h-8 rounded-md font-mono text-sm"
            value={hex ?? colour}
            maxLength={7}
            spellCheck={false}
            autoComplete="off"
            onChange={(event) => {
              setHex(event.target.value);
              setInvalid(false);
            }}
            onBlur={commitHex}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                commitHex();
              }
              if (event.key === "Escape") {
                event.stopPropagation();
                setHex(null);
                setInvalid(false);
              }
            }}
          />
        </label>
        {invalid && (
          <p id={`${pickerId}-error`} role="alert" className="text-xs text-destructive">
            Enter a hex colour, such as #0355A8.
          </p>
        )}
      </div>
    );
  }

  function palette(customButton: boolean) {
    return (
      <div className="flex items-center gap-1.5" role="group" aria-label={`${label} colours`}>
        {FIXED_COLOURS.map((swatch, index) => swatchButton(swatch, index === 0 ? "Black" : "Grey"))}
        <Separator orientation="vertical" className="mx-0.5" />
        {recent.map((swatch) => swatchButton(swatch, "Recent colour"))}
        {customButton && (
          <Popover>
            <PopoverTrigger
              render={<Button variant="ghost" size="icon-xs" className="size-7 rounded-md" />}
              aria-label={`Custom ${label.toLowerCase()} colour`}
              title="Custom colour"
            >
              <EyedropperIcon aria-hidden="true" />
            </PopoverTrigger>
            <PopoverContent
              align="start"
              className="w-64 max-w-[calc(100vw-2rem)] gap-3 rounded-xl"
            >
              <PopoverTitle className="text-sm">{label}</PopoverTitle>
              {picker(`${id}-wide`)}
            </PopoverContent>
          </Popover>
        )}
      </div>
    );
  }

  function swatchButton(swatch: string, name: string) {
    return (
      <button
        key={swatch}
        type="button"
        className="size-6 shrink-0 rounded-md border border-white/25 ring-1 ring-border outline-none hover:ring-2 focus-visible:ring-2 focus-visible:ring-ring aria-pressed:ring-2 aria-pressed:ring-primary aria-pressed:ring-offset-2 aria-pressed:ring-offset-background"
        style={{ backgroundColor: swatch }}
        aria-label={`${label}: ${name} ${swatch}`}
        aria-pressed={colour === swatch}
        title={swatch}
        onClick={() => {
          onChange(swatch);
          setHex(null);
          setInvalid(false);
        }}
      />
    );
  }

  return (
    <div className="min-w-0 p-2.5">
      <div className="flex items-center gap-2">
        <Popover>
          <PopoverTrigger
            className="size-8 shrink-0 rounded-md border border-white/25 ring-1 ring-border outline-none focus-visible:ring-2 focus-visible:ring-ring @min-[52rem]/appearance:hidden"
            style={{ backgroundColor: colour }}
            aria-label={`Choose ${label.toLowerCase()} colour, currently ${colour}`}
          />
          <PopoverContent align="start" className="w-64 max-w-[calc(100vw-2rem)] gap-3 rounded-xl">
            <PopoverTitle className="text-sm">{label}</PopoverTitle>
            {palette(false)}
            {picker(`${id}-compact`)}
          </PopoverContent>
        </Popover>
        <span
          aria-hidden="true"
          className="hidden size-8 shrink-0 rounded-md border border-white/25 ring-1 ring-border @min-[52rem]/appearance:block"
          style={{ backgroundColor: colour }}
        />
        <div className="min-w-0">
          <h3 className="text-sm font-medium">{label}</h3>
          <p className="font-mono text-xs text-muted-foreground">{colour}</p>
        </div>
      </div>
      <div className="mt-3 hidden @min-[52rem]/appearance:block">{palette(true)}</div>
    </div>
  );
}
