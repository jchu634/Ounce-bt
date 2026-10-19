import { useEffect, useRef, useState } from "react";
import { SpinnerGapIcon } from "@phosphor-icons/react";
import { Effect } from "effect";
import { useCaptureControls, useCaptureInput } from "@/src/hooks/use-capture";
import {
  CameraError,
  acquireStream,
  describeError,
  releaseStream,
} from "@/src/lib/webcam";
import { Button } from "@/src/components/ui/button";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/src/components/ui/select";

export function CaptureDeviceSettings({
  disabled,
  draftInputId,
  onDraftInputChange,
}: {
  disabled: boolean;
  draftInputId: string;
  onDraftInputChange: (deviceId: string) => void;
}) {
  return (
    <CaptureDeviceSettingsContent
      key={String(disabled)}
      disabled={disabled}
      draftInputId={draftInputId}
      onDraftInputChange={onDraftInputChange}
    />
  );
}

function CaptureDeviceSettingsContent({
  disabled,
  draftInputId,
  onDraftInputChange,
}: {
  disabled: boolean;
  draftInputId: string;
  onDraftInputChange: (deviceId: string) => void;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [visible, setVisible] = useState(false);
  const [previewStream, setPreviewStream] = useState<MediaStream | null>(null);
  const [previewStarting, setPreviewStarting] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const previewRequestedRef = useRef(false);
  const previewStreamRef = useRef<MediaStream | null>(null);
  const { permission, requestAccess, requestingPermission } =
    useCaptureControls();
  const { cameras } = useCaptureInput();
  const selectedInputLabel = cameras.find(
    (camera) => camera.deviceId === draftInputId,
  )?.label;

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    video.srcObject = visible ? previewStream : null;
    return () => {
      video.srcObject = null;
    };
  }, [previewStream, visible]);

  const releasePreview = () => {
    const current = previewStreamRef.current;
    previewStreamRef.current = null;
    setPreviewStream(null);
    if (current) void Effect.runPromise(releaseStream(current));
  };

  useEffect(
    () => () => {
      previewRequestedRef.current = false;
      const current = previewStreamRef.current;
      previewStreamRef.current = null;
      if (current) void Effect.runPromise(releaseStream(current));
    },
    [],
  );

  const togglePreview = async () => {
    if (visible) {
      previewRequestedRef.current = false;
      setVisible(false);
      releasePreview();
      return;
    }

    previewRequestedRef.current = true;
    setVisible(true);
    setPreviewError(null);
    setPreviewStarting(true);
    try {
      const audioDeviceId = (() => {
        try {
          return localStorage.getItem("ounce-bt.audio-input") ?? "";
        } catch {
          return "";
        }
      })();
      const nextStream = await Effect.runPromise(
        acquireStream(draftInputId, audioDeviceId),
      );
      if (!previewRequestedRef.current) {
        void Effect.runPromise(releaseStream(nextStream));
        return;
      }
      previewStreamRef.current = nextStream;
      setPreviewStream(nextStream);
    } catch (cause: unknown) {
      const captureError = cause instanceof CameraError ? cause : null;
      setPreviewError(
        captureError ? describeError(captureError) : "Unable to access camera.",
      );
    } finally {
      setPreviewStarting(false);
    }
  };

  return (
    <div className="flex flex-col items-start gap-3">
      {permission !== "granted" && permission !== "unsupported" && (
        <Button
          variant="outline"
          disabled={disabled || requestingPermission}
          onClick={() => void requestAccess()}
        >
          {requestingPermission
            ? "Requesting camera access..."
            : "Request camera access"}
        </Button>
      )}
      <div className="flex w-full flex-wrap items-center gap-2">
        <Select
          disabled={disabled}
          value={draftInputId}
          onValueChange={(deviceId) => {
            if (deviceId !== null) {
              onDraftInputChange(deviceId);
              if (visible) {
                previewRequestedRef.current = false;
                setVisible(false);
                releasePreview();
              }
            }
          }}
        >
          <SelectTrigger className="w-1/2 min-w-[min(100%,16rem)]">
            <SelectValue className="min-w-0 truncate" placeholder="Capture Device">
              {selectedInputLabel}
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              <SelectLabel>Capture Device</SelectLabel>
              {cameras.map((camera) => (
                <SelectItem key={camera.deviceId} value={camera.deviceId}>
                  {camera.label}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>

        <Button
          type="button"
          variant="outline"
          disabled={disabled || !draftInputId || previewStarting}
          onClick={() => void togglePreview()}
        >
          {previewStarting && (
            <SpinnerGapIcon className="animate-spin" weight="bold" />
          )}
          {visible ? "Hide preview" : "Show preview"}
        </Button>
      </div>

      <div className="aspect-video w-full max-w-sm overflow-hidden rounded-lg border border-border bg-black">
        {!disabled && visible && previewStream ? (
          <video
            ref={videoRef}
            autoPlay
            playsInline
            muted
            disablePictureInPicture
            className="size-full object-contain"
          />
        ) : (
          <div className="flex size-full items-center justify-center px-6 text-center text-sm text-zinc-400">
            {disabled
              ? "Capture controls are disabled while the controls-only homepage is enabled."
              : visible
                ? (previewError ??
                  (previewStarting
                    ? "Starting preview..."
                    : "Preview unavailable"))
                : "Preview disabled"}
          </div>
        )}
      </div>
    </div>
  );
}
