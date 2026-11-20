import { useEffect, useRef, useState } from "react";
import { LiveVideoPlayer, Video } from "@videojs/react/live-video";
import {
  PlayIcon,
  SpinnerGapIcon,
  VideoCameraIcon,
  VideoCameraSlashIcon,
  WarningIcon,
} from "@phosphor-icons/react";
import { CapturePreviewSkin } from "./capture-preview-skin";
import { Button } from "@/src/components/ui/button";
import { useCaptureControls, useCaptureInput, useCaptureStream } from "@/src/hooks/use-capture";

export function CapturePreview() {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [aspectRatio, setAspectRatio] = useState(16 / 9);
  const stream = useCaptureStream();
  const { error, permission, requestingPermission, start, starting, stop } = useCaptureControls();
  const { selectedCameraInputId } = useCaptureInput();

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    video.srcObject = stream;
    return () => {
      video.srcObject = null;
    };
  }, [stream]);

  return (
    <LiveVideoPlayer>
      <CapturePreviewSkin aspectRatio={aspectRatio} capturing={stream !== null} onStop={stop}>
        <Video
          ref={videoRef}
          autoPlay
          playsInline
          disablePictureInPicture
          onResize={(event) => {
            const { videoWidth, videoHeight } = event.currentTarget;
            if (videoWidth > 0 && videoHeight > 0) {
              setAspectRatio(videoWidth / videoHeight);
            }
          }}
          className="size-full object-contain"
        />
        {!stream && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 px-4 text-zinc-400 max-sm:pb-8">
            <Button
              type="button"
              variant="outline"
              size="icon-lg"
              className="size-12 border-white/20 bg-white/10 text-white hover:bg-white/20 hover:text-white sm:size-14"
              aria-label="Start capture input"
              title="Start capture input"
              disabled={starting || requestingPermission}
              onClick={() => void start(selectedCameraInputId)}
            >
              {starting || requestingPermission ? (
                <SpinnerGapIcon aria-hidden className="size-5 animate-spin" />
              ) : (
                <PlayIcon aria-hidden className="size-5" weight="fill" />
              )}
            </Button>
            <p role="status" className="flex items-center gap-1.5 text-center text-sm">
              {starting || requestingPermission ? (
                <>
                  <VideoCameraIcon aria-hidden className="size-4 shrink-0" />
                  {starting ? "Starting capture…" : "Waiting for camera access…"}
                </>
              ) : error || permission === "denied" ? (
                <>
                  <WarningIcon aria-hidden className="size-4 shrink-0" />
                  {permission === "denied"
                    ? "Camera access is blocked. Check your browser’s site settings."
                    : error}
                </>
              ) : (
                <>
                  <VideoCameraSlashIcon aria-hidden className="size-4 shrink-0" />
                  Capture card is idle
                </>
              )}
            </p>
          </div>
        )}
      </CapturePreviewSkin>
    </LiveVideoPlayer>
  );
}
