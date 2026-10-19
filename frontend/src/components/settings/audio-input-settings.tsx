import { useEffect, useRef, useState } from "react";
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

export function AudioInputSettings({
  disabled,
  selectedId,
  onSelectedIdChange,
}: {
  disabled: boolean;
  selectedId: string;
  onSelectedIdChange: (deviceId: string) => void;
}) {
  const [inputs, setInputs] = useState<MediaDeviceInfo[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [testing, setTesting] = useState(false);
  const [level, setLevel] = useState(0);
  const cleanupRef = useRef<(() => void) | null>(null);
  const activeRef = useRef(false);

  useEffect(() => {
    activeRef.current = true;
    const mediaDevices = navigator.mediaDevices;
    if (!mediaDevices?.enumerateDevices) return;
    let active = true;
    const refresh = async () => {
      try {
        const devices = await mediaDevices.enumerateDevices();
        if (active)
          setInputs(devices.filter((device) => device.kind === "audioinput" && device.deviceId));
      } catch {
        if (active) setError("Unable to list audio inputs.");
      }
    };
    void refresh();
    mediaDevices.addEventListener?.("devicechange", refresh);
    return () => {
      activeRef.current = false;
      active = false;
      mediaDevices.removeEventListener?.("devicechange", refresh);
      cleanupRef.current?.();
    };
  }, []);

  const stopTest = () => {
    cleanupRef.current?.();
    cleanupRef.current = null;
    setTesting(false);
    setLevel(0);
  };

  const startTest = async () => {
    if (!navigator.mediaDevices?.getUserMedia) {
      setError("This browser does not support microphone access.");
      return;
    }
    setError(null);
    let stream: MediaStream | null = null;
    try {
      const acquiredStream = await navigator.mediaDevices.getUserMedia({
        video: false,
        audio: selectedId ? { deviceId: { exact: selectedId } } : true,
      });
      if (!activeRef.current || disabled) {
        acquiredStream.getTracks().forEach((track) => track.stop());
        return;
      }
      stream = acquiredStream;
      const context = new AudioContext();
      const source = context.createMediaStreamSource(acquiredStream);
      const analyser = context.createAnalyser();
      analyser.fftSize = 2048;
      source.connect(analyser);
      const samples = new Uint8Array(analyser.fftSize);
      let frame = 0;
      const updateLevel = () => {
        analyser.getByteTimeDomainData(samples);
        let sum = 0;
        for (const sample of samples) {
          const amplitude = (sample - 128) / 128;
          sum += amplitude * amplitude;
        }
        setLevel(Math.min(100, Math.round(Math.sqrt(sum / samples.length) * 300)));
        frame = requestAnimationFrame(updateLevel);
      };
      cleanupRef.current = () => {
        cancelAnimationFrame(frame);
        source.disconnect();
        acquiredStream.getTracks().forEach((track) => track.stop());
        void context.close();
      };
      setTesting(true);
      updateLevel();
      const devices = await navigator.mediaDevices.enumerateDevices();
      setInputs(devices.filter((device) => device.kind === "audioinput" && device.deviceId));
    } catch (cause) {
      stream?.getTracks().forEach((track) => track.stop());
      setError(
        cause instanceof DOMException && cause.name === "NotAllowedError"
          ? "Microphone permission denied. Enable it in your browser's site settings."
          : "Unable to access the selected audio input.",
      );
    }
  };

  const selected = inputs.find((input) => input.deviceId === selectedId);
  return (
    <div className="flex flex-col items-start gap-3">
      <div className="flex w-full flex-wrap items-center gap-2">
        <Select
          disabled={disabled}
          value={selectedId}
          onValueChange={(id) => {
            if (id === null) return;
            stopTest();
            onSelectedIdChange(id);
          }}
        >
          <SelectTrigger className="w-1/2 min-w-[min(100%,16rem)]" aria-label="Audio input">
            <SelectValue className="min-w-0 truncate" placeholder="Audio input">
              {selected?.label}
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              <SelectLabel>Audio input</SelectLabel>
              {inputs.map((input, index) => (
                <SelectItem key={input.deviceId || index} value={input.deviceId}>
                  {input.label || `Microphone ${index + 1}`}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
        <Button
          type="button"
          variant="outline"
          disabled={disabled}
          onClick={() => {
            if (testing) stopTest();
            else void startTest();
          }}
        >
          {testing ? "Stop test" : "Test audio"}
        </Button>
        {testing && (
          <div
            className="max-w-40 min-w-24 flex-1"
            role="meter"
            aria-label="Microphone input level"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={level}
          >
            <div className="h-3 overflow-hidden rounded bg-muted">
              <div className="h-full bg-primary" style={{ width: `${level}%` }} />
            </div>
          </div>
        )}
      </div>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}
