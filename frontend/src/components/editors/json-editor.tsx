import {
  useEffect,
  useImperativeHandle,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import { EditProvider, File as DiffsFile } from "@pierre/diffs/react";
import type { FileContents } from "@pierre/diffs/react";
import type { Editor as DiffsEditor, EditorOptions } from "@pierre/diffs/edit";

type AnyEditor = DiffsEditor<undefined>;
import { cn } from "cn";

// Lazy load edit entry point once per session
type EditModule = typeof import("@pierre/diffs/edit");
let editModulePromise: Promise<EditModule> | null = null;
const loadEditModule = (): Promise<EditModule> => {
  editModulePromise ??= import("@pierre/diffs/edit");
  return editModulePromise;
};

export type JsonMarkerSeverity = "error" | "warning";

/** 1-based line (col optional). */
export type JsonMarker = {
  line: number;
  col?: number;
  severity: JsonMarkerSeverity;
  message: string;
};

export type JsonEditorProps = {
  fileName: string;
  cacheKey: string;
  /** Raw text. Treated as the source of truth while *not* editing. */
  value: string;
  onChange: (text: string) => void;
  editing: boolean;
  markers?: JsonMarker[];
  className?: string;
  ref?: React.Ref<JsonEditorHandle>;
};

export type JsonEditorHandle = {
  /** Replace the attached document's text via the undo-able edit API.
   * Returns false when no edit session is attached (caller should fall
   * back to updating the value prop). */
  replaceDocument: (text: string) => boolean;
  focus: () => void;
};

function useSystemDark(): boolean {
  return useSyncExternalStore(
    (callback) => {
      const query = window.matchMedia("(prefers-color-scheme: dark)");
      query.addEventListener("change", callback);
      return () => query.removeEventListener("change", callback);
    },
    () => window.matchMedia("(prefers-color-scheme: dark)").matches,
    () => false,
  );
}

export function JsonEditor({
  fileName,
  cacheKey,
  value,
  onChange,
  editing,
  markers = [],
  className,
  ref,
}: JsonEditorProps) {
  const [editModule, setEditModule] = useState<EditModule | null>(null);
  const editorRef = useRef<AnyEditor | null>(null);
  const onChangeRef = useRef(onChange);
  const valueRef = useRef(value);

  useLayoutEffect(() => {
    onChangeRef.current = onChange;
    valueRef.current = value;
  }, [onChange, value]);

  useEffect(() => {
    let cancelled = false;
    loadEditModule().then((mod) => {
      if (!cancelled) setEditModule(mod);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const editorOptions = useMemo<EditorOptions<undefined>>(() => {
    return {
      persistState: true,
      onAttach: (editor) => {
        editorRef.current = editor;
        // A re-attached session may restore a cached (edited) document;
        // re-sync the host value so Save operates on the visible text.
        const text = editor.getText();
        if (text !== valueRef.current) onChangeRef.current(text);
      },
      onChange: (file) => {
        onChangeRef.current(file.contents);
      },
    };
  }, []);

  // Push markers into the attached editor (must be attached first).
  useEffect(() => {
    const editor = editorRef.current;
    if (editor === null || markers.length === 0) return;
    const lines = editor.getText().split("\n");
    const docs = markers.map((m) => {
      const lineIdx = Math.min(Math.max(m.line - 1, 0), lines.length - 1);
      const startChar = Math.max((m.col ?? 1) - 1, 0);
      const endChar = Math.max(startChar + 1, lines[lineIdx]?.length ?? 1);
      return {
        start: { line: lineIdx, character: startChar },
        end: { line: lineIdx, character: endChar },
        severity: m.severity,
        message: m.message,
      };
    });
    editor.setMarkers(docs as Parameters<AnyEditor["setMarkers"]>[0]);
  }, [markers, editing]);

  // Clear markers whenever the marker list empties or session detaches.
  useEffect(() => {
    if (markers.length > 0) return;
    editorRef.current?.setMarkers([]);
  }, [markers]);

  const dark = useSystemDark();
  const file = useMemo<FileContents>(
    () => ({
      name: fileName,
      contents: value,
      lang: "json",
      cacheKey,
    }),
    [fileName, value, cacheKey],
  );
  const fileOptions = useMemo(
    () => ({ themeType: dark ? ("dark" as const) : ("light" as const) }),
    [dark],
  );

  useImperativeHandle(
    ref,
    () => ({
      replaceDocument: (text: string) => {
        const editor = editorRef.current;
        if (editor === null) return false;

        const current = editor.getText();
        if (current === text) return true;

        const lines = current.split("\n");
        const lastLine = lines.length - 1;
        const lastChar = lines[lastLine]?.length ?? 0;

        editor.applyEdits(
          [
            {
              range: {
                start: { line: 0, character: 0 },
                end: { line: lastLine, character: lastChar },
              },
              newText: text,
            },
          ],
          false,
        );
        onChangeRef.current(text);
        return true;
      },
      focus: () => editorRef.current?.focus(),
    }),
    [],
  );

  const surface = (
    <DiffsFile
      file={file}
      options={fileOptions}
      edit={editing && editModule !== null}
      editorOptions={editModule !== null ? editorOptions : undefined}
      className="text-left"
    />
  );

  return (
    <div
      className={cn(
        "overflow-auto rounded-xl border border-border bg-background",
        className,
      )}
    >
      {editModule !== null ? (
        <EditProvider
          createEditor={(options: EditorOptions<undefined>) =>
            new editModule.Editor({ persistState: true, ...options })
          }
        >
          {surface}
        </EditProvider>
      ) : (
        surface
      )}
    </div>
  );
}
