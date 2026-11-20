"""Monitor capture-card audio outside the Windows WebView renderer."""

from array import array
from collections import deque
from ctypes import CDLL, c_int, c_uint32
from pathlib import Path
from threading import Lock

import pygame
from pygame._sdl2 import INIT_AUDIO, audio, init_subsystem


class AudioMonitor:
    def __init__(self):
        self._lock = Lock()
        self._pause_device = None
        self._closed = False
        self._session = 0
        self._devices: tuple[audio.AudioDevice, audio.AudioDevice] | None = None
        self._volume = 0.0

    def start(self, label: str) -> int | None:
        with self._lock:
            if self._closed:
                return None
            if self._pause_device is None:
                dll = Path(pygame.__file__).parent / "SDL2.dll"
                sdl = CDLL(str(dll) if dll.is_file() else "SDL2.dll")
                pause_device = sdl.SDL_PauseAudioDevice
                pause_device.argtypes = (c_uint32, c_int)
                pause_device.restype = None
                init_subsystem(INIT_AUDIO)
                self._pause_device = pause_device
            # Browser and SDL names can differ for USB devices. Only open an
            # exact, unambiguous match so a fallback cannot select a microphone.
            label = label.removeprefix("Default - ").removeprefix("Communications - ")
            if audio.get_audio_device_names(True).count(label) != 1:
                return None

            self._stop()
            frames = 1024
            chunks: deque[bytes] = deque(maxlen=6)
            silence = bytes(frames * 2 * 2)  # 16-bit stereo
            primed = False

            def capture(_device, samples):
                chunks.append(bytes(samples))

            def play(_device, samples):
                nonlocal primed
                if not primed and len(chunks) < 3:
                    samples[:] = silence
                    return
                try:
                    chunk = chunks.popleft()
                except IndexError:
                    primed = False
                    samples[:] = silence
                    return
                primed = True
                volume = self._volume
                if volume == 0:
                    samples[:] = silence
                elif volume == 1:
                    samples[:] = chunk
                else:
                    scaled = array(
                        "h", (int(value * volume) for value in array("h", chunk))
                    )
                    samples[:] = scaled.tobytes()

            recorder = audio.AudioDevice(
                label, True, 48000, audio.AUDIO_S16, 2, frames, 0, capture
            )
            try:
                speaker = audio.AudioDevice(
                    None, False, 48000, audio.AUDIO_S16, 2, frames, 0, play
                )
            except Exception:
                recorder.close()
                raise
            self._devices = (speaker, recorder)
            try:
                recorder.pause(False)
                speaker.pause(False)
            except Exception:
                self._stop()
                raise
            self._session += 1
            return self._session

    def set_volume(self, session: int, volume: float) -> None:
        with self._lock:
            if session == self._session and self._devices is not None:
                self._volume = min(1.0, max(0.0, float(volume)))

    def stop(self, session: int) -> None:
        with self._lock:
            if session == self._session:
                self._stop()

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._stop()

    def _stop(self) -> None:
        self._volume = 0.0
        if self._devices is not None:
            speaker, recorder = self._devices
            self._devices = None
            # SDL waits for the audio callback to return. ctypes releases the
            # GIL while pausing, so a Python callback can finish before close.
            self._pause_device(speaker.deviceid, 1)
            self._pause_device(recorder.deviceid, 1)
            try:
                speaker.close()
            finally:
                recorder.close()
