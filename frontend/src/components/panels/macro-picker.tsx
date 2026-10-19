import { FilePlusIcon } from "@phosphor-icons/react";
import { Button } from "@/src/components/ui/button";

export type MacroPickerProps = {
  names: string[];
  selected: string | null;
  onSelect: (name: string) => void;
  onCreate: () => void;
};

export function MacroPicker({ names, selected, onSelect, onCreate }: MacroPickerProps) {
  return (
    <section className="flex min-w-0 flex-col gap-3 text-left">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-lg font-semibold text-foreground">Macros</h2>
        <Button size="sm" variant="outline" className="ms-auto" onClick={onCreate}>
          <FilePlusIcon size={14} /> New macro
        </Button>
      </div>

      <div className="app-scrollbar max-h-[calc(100svh-11rem)] overflow-y-auto overscroll-contain rounded-2xl border border-border bg-muted/30 p-2">
        {names.length === 0 ? (
          <div className="flex min-h-28 items-center justify-center rounded-xl border border-dashed border-border px-4 text-sm text-muted-foreground">
            No macros yet. Create one to get started.
          </div>
        ) : (
          <ul className="flex flex-col gap-2">
            {names.map((name) => (
              <li key={name}>
                <Button
                  variant={selected === name ? "secondary" : "outline"}
                  className="h-auto w-full justify-start rounded-xl px-3 py-2 font-mono font-normal"
                  onClick={() => onSelect(name)}
                  title={name}
                >
                  <span className="truncate">{name}</span>
                </Button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
