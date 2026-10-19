import { useEffect, useRef, useState } from "react";
import { LiveVideoPlayer, Video } from "@videojs/react/live-video";
import { VideoCameraIcon, VideoCameraSlashIcon, WarningIcon } from "@phosphor-icons/react";
import { CapturePreviewSkin } from "./capture-preview-skin";
import { useCaptureControls, useCaptureStream } from "@/src/hooks/use-capture";

export function CapturePreview() {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [aspectRatio, setAspectRatio] = useState(16 / 9);
  const stream = useCaptureStream();
  const { error, permission, starting } = useCaptureControls();
  const permissionGranted = permission === "granted" || permission === "unsupported";

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
      <CapturePreviewSkin aspectRatio={aspectRatio}>
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
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-zinc-400">
            {error ? (
              <>
                <WarningIcon size={36} weight="duotone" />
                <p className="px-6 text-center text-sm">{error}</p>
              </>
            ) : permission === "denied" ? (
              <>
                <VideoCameraSlashIcon size={36} weight="duotone" />
                <p className="px-6 text-center text-sm">
                  Camera access is blocked. Enable it in your browser's site settings to use the
                  capture preview.
                </p>
              </>
            ) : !permissionGranted ? (
              <>
                <VideoCameraIcon size={36} weight="duotone" />
                <p className="text-sm">Camera access required to usae capture preview</p>
              </>
            ) : (
              <>
                <VideoCameraSlashIcon size={36} weight="duotone" />
                <p className="text-sm">
                  {starting ? "Starting capture..." : "Capture card is idle"}
                </p>
              </>
            )}
          </div>
        )}
      </CapturePreviewSkin>
    </LiveVideoPlayer>
  );
}
