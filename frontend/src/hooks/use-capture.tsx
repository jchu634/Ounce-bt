import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Effect } from "effect";
import {
  type CameraDevice,
  CameraError,
  type CameraPermissionState,
  acquireStream,
  describeError,
  enumerateCameras,
  releaseStream,
  requestPermission,
} from "@/src/lib/webcam";

type CaptureContextValue = {
  readonly cameras: readonly CameraDevice[];
  readonly error: string | null;
  readonly permission: CameraPermissionState;
  readonly requestingPermission: boolean;
  readonly selectedAudioInputId: string;
  readonly selectedCameraInputId: string;
  readonly starting: boolean;
  readonly stream: MediaStream | null;
  readonly selectInput: (deviceId: string) => void;
  readonly selectInputs: (inputs: {
    readonly audioDeviceId: string;
    readonly videoDeviceId: string;
  }) => void;
  readonly requestAccess: () => Promise<void>;
  readonly start: (deviceId: string) => Promise<void>;
  readonly stop: () => void;
};

const CaptureContext = createContext<CaptureContextValue | null>(null);

const AUDIO_INPUT_STORAGE_KEY = "ounce-bt.audio-input";

function readSavedAudioInputId(): string {
  try {
    return localStorage.getItem(AUDIO_INPUT_STORAGE_KEY) ?? "";
  } catch {
    return "";
  }
}

function saveAudioInputId(deviceId: string): void {
  try {
    localStorage.setItem(AUDIO_INPUT_STORAGE_KEY, deviceId);
  } catch {
    // Capture still works when storage is unavailable.
    console.log("Localstorage audio input storage key write failed");
  }
}

function useCaptureContext(): CaptureContextValue {
  const context = useContext(CaptureContext);
  if (!context) {
    throw new Error("Capture hooks must be used inside CaptureProvider");
  }
  return context;
}

export function CaptureProvider({
  children,
}: {
  readonly children: ReactNode;
}) {
  const activeStreamRef = useRef<MediaStream | null>(null);
  const [cameras, setCameras] = useState<readonly CameraDevice[]>([]);
  const [selectedAudioInputId, setSelectedAudioInputId] = useState(
    readSavedAudioInputId,
  );
  const [selectedCameraInputId, setSelectedCameraInputId] = useState("");
  const [stream, setStream] = useState<MediaStream | null>(null);
  const [starting, setStarting] = useState(false);
  const [requestingPermission, setRequestingPermission] = useState(false);
  const [permission, setPermission] = useState<CameraPermissionState>(() =>
    typeof navigator.permissions?.query === "function"
      ? "prompt"
      : "unsupported",
  );
  const [error, setError] = useState<string | null>(null);

  const syncActiveStream = useCallback((nextStream: MediaStream | null) => {
    activeStreamRef.current = nextStream;
    setStream(nextStream);
  }, []);

  const refreshCameras = useCallback(async () => {
    const devices = await Effect.runPromise(enumerateCameras).catch(
      (): readonly CameraDevice[] => [],
    );
    setCameras(devices);
    setSelectedCameraInputId(
      (currentId) => currentId || devices[0]?.deviceId || "",
    );
  }, []);

  const stop = useCallback(() => {
    const current = activeStreamRef.current;
    syncActiveStream(null);
    if (current) void Effect.runPromise(releaseStream(current));
  }, [syncActiveStream]);

  useEffect(() => {
    if (!stream) return;
    const tracks = stream.getVideoTracks();
    const stopIfVideoEnded = () => {
      if (
        activeStreamRef.current === stream &&
        tracks.every((track) => track.readyState === "ended")
      ) {
        stop();
      }
    };
    for (const track of tracks) track.addEventListener("ended", stopIfVideoEnded);
    stopIfVideoEnded();
    return () => {
      for (const track of tracks) track.removeEventListener("ended", stopIfVideoEnded);
    };
  }, [stop, stream]);

  const startWithInputs = async (deviceId: string, audioDeviceId: string) => {
    setError(null);
    setStarting(true);
    const previous = activeStreamRef.current;
    syncActiveStream(null);
    if (previous) await Effect.runPromise(releaseStream(previous));

    try {
      const nextStream = await Effect.runPromise(
        acquireStream(deviceId, audioDeviceId),
      );
      syncActiveStream(nextStream);
      setPermission("granted");
      await refreshCameras();
    } catch (cause: unknown) {
      const captureError = cause instanceof CameraError ? cause : null;
      setError(
        captureError ? describeError(captureError) : "Unable to access camera.",
      );
      if (captureError?.reason === "denied") setPermission("denied");
    } finally {
      setStarting(false);
    }
  };

  const start = (deviceId: string) =>
    startWithInputs(deviceId, selectedAudioInputId);

  const requestAccess = useCallback(async () => {
    setError(null);
    setRequestingPermission(true);
    try {
      await Effect.runPromise(requestPermission);
      setPermission("granted");
    } catch (cause: unknown) {
      const captureError = cause instanceof CameraError ? cause : null;
      setError(
        captureError ? describeError(captureError) : "Unable to access camera.",
      );
      setPermission(
        captureError?.reason === "unsupported" ? "unsupported" : "denied",
      );
    } finally {
      setRequestingPermission(false);
    }
  }, []);

  const selectInput = (deviceId: string) => {
    setSelectedCameraInputId(deviceId);
    if (activeStreamRef.current) {
      void startWithInputs(deviceId, selectedAudioInputId);
    }
  };

  const selectInputs = ({
    audioDeviceId,
    videoDeviceId,
  }: {
    readonly audioDeviceId: string;
    readonly videoDeviceId: string;
  }) => {
    setSelectedCameraInputId(videoDeviceId);
    setSelectedAudioInputId(audioDeviceId);
    saveAudioInputId(audioDeviceId);
    if (activeStreamRef.current) {
      void startWithInputs(videoDeviceId, audioDeviceId);
    }
  };

  useEffect(() => {
    let cancelled = false;
    let status: PermissionStatus | null = null;
    const permissions = navigator.permissions;
    if (!permissions?.query) {
      return;
    }

    void permissions
      .query({ name: "camera" as PermissionName })
      .then((nextStatus) => {
        if (cancelled) return;
        status = nextStatus;
        setPermission(nextStatus.state);
        nextStatus.onchange = () => setPermission(nextStatus.state);
      })
      .catch(() => {
        if (!cancelled) setPermission("unsupported");
      });

    return () => {
      cancelled = true;
      if (status) status.onchange = null;
    };
  }, []);

  useEffect(() => {
    if (permission !== "granted" && permission !== "unsupported") return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- syncs the browser device list.
    void refreshCameras();
    const handleDeviceChange = () => void refreshCameras();
    navigator.mediaDevices?.addEventListener?.(
      "devicechange",
      handleDeviceChange,
    );
    return () => {
      navigator.mediaDevices?.removeEventListener?.(
        "devicechange",
        handleDeviceChange,
      );
    };
  }, [permission, refreshCameras]);

  useEffect(
    () => () => {
      const current = activeStreamRef.current;
      activeStreamRef.current = null;
      if (current) current.getTracks().forEach((track) => track.stop());
    },
    [],
  );

  return (
    <CaptureContext.Provider
      value={{
        cameras,
        error,
        permission,
        requestingPermission,
        selectedAudioInputId,
        selectedCameraInputId,
        starting,
        stream,
        selectInput,
        selectInputs,
        requestAccess,
        start,
        stop,
      }}
    >
      {children}
    </CaptureContext.Provider>
  );
}

export function useCaptureControls() {
  const {
    error,
    permission,
    requestAccess,
    requestingPermission,
    start,
    starting,
    stop,
  } = useCaptureContext();
  return {
    error,
    permission,
    requestAccess,
    requestingPermission,
    start,
    starting,
    stop,
  } as const;
}

export function useCaptureInput() {
  const {
    cameras,
    permission,
    selectedAudioInputId,
    selectedCameraInputId,
    selectInput,
    selectInputs,
  } = useCaptureContext();
  return {
    cameras,
    permission,
    selectedAudioInputId,
    selectedCameraInputId,
    selectInput,
    selectInputs,
  } as const;
}

export function useCaptureStream(): MediaStream | null {
  return useCaptureContext().stream;
}
