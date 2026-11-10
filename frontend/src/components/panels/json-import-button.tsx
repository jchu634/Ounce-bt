import { useRef, useState } from "react";
import { SpinnerGapIcon, UploadSimpleIcon } from "@phosphor-icons/react";
import { Button } from "@/src/components/ui/button";
import { importJsonFiles, type ImportKind } from "@/src/lib/json-transfer";
import { errorMessage } from "@/src/lib/errors";

export function JsonImportButton({
  kind,
  onImported,
}: {
  kind: ImportKind;
  onImported: () => void | Promise<void>;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [errors, setErrors] = useState<string[]>([]);

  async function importFiles(files: File[]) {
    setBusy(true);
    setMessage(null);
    setErrors([]);
    try {
      const result = await importJsonFiles(kind, files);
      setErrors(result.errors);
      setMessage(
        `Imported ${result.imported.length} ${kind}${result.imported.length === 1 ? "" : "s"}.`,
      );
      if (result.imported.length > 0) await onImported();
    } catch (error) {
      setErrors([errorMessage(error)]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <input
        ref={input}
        type="file"
        accept=".json,application/json"
        multiple
        hidden
        aria-label={`Import ${kind}s`}
        onChange={(event) => {
          const files = Array.from(event.currentTarget.files ?? []);
          event.currentTarget.value = "";
          if (files.length > 0) void importFiles(files);
        }}
      />
      <Button
        size="icon-sm"
        variant="outline"
        disabled={busy}
        onClick={() => input.current?.click()}
        title={`Import ${kind}s`}
        aria-label={busy ? `Importing ${kind}s` : `Import ${kind}s`}
      >
        {busy ? (
          <SpinnerGapIcon size={14} className="animate-spin" />
        ) : (
          <UploadSimpleIcon size={14} />
        )}
      </Button>
      {message !== null && (
        <p role="status" className="order-last basis-full text-xs text-muted-foreground">
          {message}
        </p>
      )}
      {errors.length > 0 && (
        <ul role="alert" className="order-last basis-full text-xs text-destructive">
          {errors.map((error, index) => (
            <li key={index}>{error}</li>
          ))}
        </ul>
      )}
    </>
  );
}
