import { useState } from "react";
import { DownloadSimpleIcon, ShareNetworkIcon } from "@phosphor-icons/react";
import { Button } from "@/src/components/ui/button";
import { toast } from "@/src/components/ui/toast";
import { errorMessage } from "@/src/lib/errors";
import { downloadJson, shareJson } from "@/src/lib/json-transfer";

export function JsonExportButtons({
  name,
  contents,
  disabled,
}: {
  name: string;
  contents: string;
  disabled: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [downloading, setDownloading] = useState(false);

  async function download() {
    setDownloading(true);
    try {
      await downloadJson(name, contents);
    } catch (error) {
      toast.add({
        type: "error",
        title: "Could not download JSON",
        description: errorMessage(error),
      });
    } finally {
      setDownloading(false);
    }
  }

  async function share() {
    setBusy(true);
    try {
      await shareJson(name, contents);
    } catch (error) {
      toast.add({ type: "error", title: "Could not share JSON", description: errorMessage(error) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Button
        size="icon-sm"
        variant="outline"
        disabled={disabled || downloading}
        onClick={() => void download()}
        title="Download JSON"
        aria-label="Download JSON"
      >
        <DownloadSimpleIcon size={14} />
      </Button>
      <Button
        size="icon-sm"
        variant="outline"
        disabled={disabled || busy}
        onClick={() => void share()}
        title="Share JSON"
        aria-label="Share JSON"
      >
        <ShareNetworkIcon size={14} />
      </Button>
    </>
  );
}
