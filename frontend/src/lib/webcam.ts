import { Data, Effect } from "effect";

export type CameraDevice = {
  readonly deviceId: string;
  readonly label: string;
};

export class CameraError extends Data.TaggedError("CameraError")<{
  readonly reason: "denied" | "notFound" | "inUse" | "unsupported" | "unknown";
  readonly cause: unknown;
}> {}

const toCameraError = (cause: unknown): CameraError => {
  const e = cause as DOMException | undefined;
  switch (e?.name) {
    case "NotAllowedError":
    case "SecurityError":
      return new CameraError({ reason: "denied", cause });
    case "NotFoundError":
    case "OverconstrainedError":
      return new CameraError({ reason: "notFound", cause });
    case "NotReadableError":
      return new CameraError({ reason: "inUse", cause });
    default:
      return new CameraError({ reason: "unknown", cause });
  }
};

export const describeError = (err: CameraError): string => {
  switch (err.reason) {
    case "denied":
      return "Camera permission denied.";
    case "notFound":
      return "No matching camera found.";
    case "inUse":
      return "Camera is already in use by another application.";
    case "unsupported":
      return "This browser does not support camera APIs.";
    default:
      return "Unable to access camera.";
  }
};

export type CameraPermissionState = "granted" | "denied" | "prompt" | "unsupported";

export const requestPermission = Effect.gen(function* () {
  const md = navigator.mediaDevices;
  if (!md?.getUserMedia) {
    return yield* new CameraError({ reason: "unsupported", cause: null });
  }
  const stream = yield* Effect.tryPromise({
    try: () => md.getUserMedia({ video: true, audio: false }),
    catch: (e) => toCameraError(e),
  });
  yield* Effect.sync(() => stream.getTracks().forEach((t) => t.stop()));
});

export const enumerateCameras = Effect.gen(function* () {
  const md = navigator.mediaDevices;

  if (!md?.enumerateDevices) {
    return yield* new CameraError({ reason: "unsupported", cause: null });
  }
  const devices = yield* Effect.tryPromise({
    try: () => md.enumerateDevices(),
    catch: (e) => toCameraError(e),
  });
  return devices
    .filter((d) => d.kind === "videoinput")
    .map((d, i) => ({
      deviceId: d.deviceId,
      label: d.label || `Camera ${i + 1}`,
    })) satisfies ReadonlyArray<CameraDevice>;
});

export const captureAudioConstraints = (deviceId: string): MediaTrackConstraints => ({
  ...(deviceId ? { deviceId: { exact: deviceId } } : {}),
  echoCancellation: { exact: false },
  noiseSuppression: { exact: false },
  autoGainControl: { exact: false },
});

export const acquireStream = (deviceId: string, audioDeviceId: string | false) =>
  Effect.gen(function* () {
    const md = navigator.mediaDevices;
    if (!md?.getUserMedia) {
      return yield* new CameraError({ reason: "unsupported", cause: null });
    }
    return yield* Effect.tryPromise({
      try: () =>
        md.getUserMedia({
          video: deviceId ? { deviceId: { exact: deviceId } } : true,
          audio: audioDeviceId === false ? false : captureAudioConstraints(audioDeviceId),
        }),
      catch: (e) => toCameraError(e),
    });
  });

export const releaseStream = (stream: MediaStream) =>
  Effect.sync(() => stream.getTracks().forEach((t) => t.stop()));
