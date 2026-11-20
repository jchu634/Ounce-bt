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
import { desktopApi } from "@/src/lib/desktop";

let monitorQueue = Promise.resolve();

function attachPreview(video: HTMLVideoElement, stream: MediaStream | null) {
  const api = desktopApi();
  const audioTrack = api?.start_capture_audio && stream?.getAudioTracks()[0];
  if (!stream || !audioTrack || !api?.start_capture_audio ||
      !api.set_capture_volume || !api.stop_capture_audio) {
    video.srcObject = stream;
    return () => { video.srcObject = null; };
  }

  const { start_capture_audio, set_capture_volume, stop_capture_audio } = api;
  let disposed = false;
  let session: number | null = null;
  const syncVolume = () => {
    if (session !== null) {
      const volume = video.muted || video.paused ? 0 : video.volume;
      void set_capture_volume(session, volume).catch(() => {});
    }
  };
  const events = ["volumechange", "play", "pause"];
  for (const event of events) video.addEventListener(event, syncVolume);
  // Windows desktop plays through SDL. Keep the WebView silent until its
  // native monitor opens, and use the original stream if the device fails.
  video.srcObject = new MediaStream(stream.getVideoTracks());
  monitorQueue = monitorQueue.then(async () => {
    if (disposed) return;
    try {
      session = await start_capture_audio(audioTrack.label);
    } catch {
      session = null;
    }
    if (disposed) return;
    if (session === null) {
      video.srcObject = stream;
    } else {
      audioTrack.stop();
      syncVolume();
    }
  });

  return () => {
    disposed = true;
    for (const event of events) video.removeEventListener(event, syncVolume);
    video.srcObject = null;
    // Wait for a pending open before stopping this session. A replacement
    // stream queues its own open after this stop.
    monitorQueue = monitorQueue.then(async () => {
      if (session !== null) await stop_capture_audio(session).catch(() => {});
    });
  };
}

export function CapturePreview() {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [aspectRatio, setAspectRatio] = useState(16 / 9);
  const stream = useCaptureStream();
  const { error, permission, requestingPermission, start, starting, stop } = useCaptureControls();
  const { selectedCameraInputId } = useCaptureInput();

  useEffect(() => {
    const video = videoRef.current;
    if (video) return attachPreview(video, stream);
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
