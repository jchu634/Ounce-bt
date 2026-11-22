"""Monitor capture-card audio outside the Windows WebView renderer using SDL3 streams."""

from __future__ import annotations

import ctypes
from threading import Event, Lock, Thread
from typing import Any

from lib.sdl3 import load_sdl3, sdl3_error

SAMPLE_RATE = 48000
CHANNELS = 2
CHUNK_BYTES = 1024 * CHANNELS * 2  # 1024 frames of 16-bit stereo (~21 ms)
MAX_QUEUED_BYTES = CHUNK_BYTES * 6


class AudioMonitor:
    def __init__(self, sdl: Any | None = None):
        self._lock = Lock()
        self._sdl = sdl
        self._audio_initialized = False
        self._closed = False
        self._session = 0
        self._streams: tuple[Any, Any] | None = None
        self._pump_stop: Event | None = None
        self._pump_thread: Thread | None = None

    def _ensure_audio(self) -> Any:
        sdl = self._sdl or load_sdl3()
        self._sdl = sdl
        if not self._audio_initialized:
            if not sdl.SDL_InitSubSystem(sdl.SDL_INIT_AUDIO):
                raise RuntimeError(f"SDL3 audio init failed: {sdl3_error(sdl)}")
            self._audio_initialized = True
        return sdl

    def _find_recording_device(self, sdl: Any, label: str) -> int | None:
        count = ctypes.c_int(0)
        ids = sdl.SDL_GetAudioRecordingDevices(ctypes.byref(count))
        if not ids:
            return None
        try:
            matches = []
            for i in range(count.value):
                device_id = int(ids[i])
                raw = sdl.SDL_GetAudioDeviceName(device_id)
                name = raw.decode("utf-8", errors="replace") if raw else ""
                if name == label:
                    matches.append(device_id)
            return matches[0] if len(matches) == 1 else None
        finally:
            sdl.SDL_free(ids)

    def start(self, label: str) -> int | None:
        with self._lock:
            if self._closed:
                return None
            sdl = self._ensure_audio()
            # Browser and SDL names can differ for USB devices. Only open an
            # exact, unambiguous match so a fallback cannot select a microphone.
            clean = label.removeprefix("Default - ").removeprefix("Communications - ")
            device_id = self._find_recording_device(sdl, clean)
            if device_id is None:
                return None

            self._stop()
            spec = sdl.SDL_AudioSpec(
                format=sdl.SDL_AUDIO_S16,
                channels=CHANNELS,
                freq=SAMPLE_RATE,
            )
            null_cb = sdl.SDL_AudioStreamCallback()
            recorder = sdl.SDL_OpenAudioDeviceStream(
                device_id, ctypes.byref(spec), null_cb, None
            )
            if not recorder:
                raise RuntimeError(f"Could not open capture audio: {sdl3_error(sdl)}")
            speaker = sdl.SDL_OpenAudioDeviceStream(
                sdl.SDL_AUDIO_DEVICE_DEFAULT_PLAYBACK,
                ctypes.byref(spec),
                null_cb,
                None,
            )
            if not speaker:
                sdl.SDL_DestroyAudioStream(recorder)
                raise RuntimeError(f"Could not open playback audio: {sdl3_error(sdl)}")

            sdl.SDL_SetAudioStreamGain(speaker, 0.0)
            stop_event = Event()
            self._streams = (speaker, recorder)
            self._pump_stop = stop_event

            if not (
                sdl.SDL_ResumeAudioStreamDevice(recorder)
                and sdl.SDL_ResumeAudioStreamDevice(speaker)
            ):
                self._stop()
                raise RuntimeError(f"Could not start capture audio: {sdl3_error(sdl)}")

            thread = Thread(
                target=self._pump,
                args=(sdl, recorder, speaker, stop_event),
                name="audio-monitor",
                daemon=True,
            )
            self._pump_thread = thread
            thread.start()
            self._session += 1
            return self._session

    @staticmethod
    def _pump(sdl: Any, recorder: Any, speaker: Any, stop_event: Event) -> None:
        buf = (ctypes.c_ubyte * CHUNK_BYTES)()
        while not stop_event.is_set():
            transferred = False
            while not stop_event.is_set():
                read = sdl.SDL_GetAudioStreamData(recorder, buf, CHUNK_BYTES)
                if read <= 0:
                    break
                transferred = True
                if sdl.SDL_GetAudioStreamQueued(speaker) > MAX_QUEUED_BYTES:
                    sdl.SDL_ClearAudioStream(speaker)
                sdl.SDL_PutAudioStreamData(speaker, buf, read)
            stop_event.wait(0.005 if transferred else 0.01)

    def set_volume(self, session: int, volume: float) -> None:
        with self._lock:
            if session == self._session and self._streams is not None and self._sdl is not None:
                gain = min(1.0, max(0.0, float(volume)))
                self._sdl.SDL_SetAudioStreamGain(self._streams[0], gain)

    def stop(self, session: int) -> None:
        with self._lock:
            if session == self._session:
                self._stop()

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._stop()
            if self._audio_initialized and self._sdl is not None:
                self._audio_initialized = False
                self._sdl.SDL_QuitSubSystem(self._sdl.SDL_INIT_AUDIO)

    def _stop(self) -> None:
        stop_event, self._pump_stop = self._pump_stop, None
        thread, self._pump_thread = self._pump_thread, None
        if stop_event is not None:
            stop_event.set()
        if thread is not None:
            thread.join(timeout=1.0)
        if self._streams is not None and self._sdl is not None:
            speaker, recorder = self._streams
            self._streams = None
            try:
                self._sdl.SDL_DestroyAudioStream(speaker)
            finally:
                self._sdl.SDL_DestroyAudioStream(recorder)
