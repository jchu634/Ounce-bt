"""Configure and load PySDL3 using libusb-enabled SDL3 binaries."""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from typing import Any

from lib.config import application_dir

_LOCK = threading.Lock()
_SDL3: Any = None
_DLL_DIR_HANDLES: list[Any] = []


def _register_windows_dll_dir(directory: Path) -> None:
    if sys.platform != "win32" or not directory.is_dir():
        return
    text = str(directory)
    if text not in os.environ.get("PATH", "").split(os.pathsep):
        os.environ["PATH"] = text + os.pathsep + os.environ.get("PATH", "")
    if hasattr(os, "add_dll_directory"):
        _DLL_DIR_HANDLES.append(os.add_dll_directory(text))


def _is_packaged() -> bool:
    return bool(
        getattr(sys, "_MEIPASS", None)
        or getattr(sys, "frozen", False)
        or "__compiled__" in globals()
    )


def _resolve_binary_dir() -> Path | None:
    root = application_dir()
    for candidate in (root / "sdl3" / "bin", root / "build" / "sdl3" / "bin"):
        if candidate.is_dir() and (
            (candidate / "SDL3.dll").is_file() or any(candidate.glob("libSDL3.so*"))
        ):
            return candidate
    return None


def bundled_libusb_path() -> Path | None:
    """Return the bundled Windows libusb-1.0.dll alongside SDL3, if present."""
    if sys.platform != "win32":
        return None
    bundled = _resolve_binary_dir()
    if bundled is None:
        return None
    candidate = bundled / "libusb-1.0.dll"
    return candidate if candidate.is_file() else None


def configure_sdl3_environment() -> None:
    """Disable PySDL3 runtime network checks, locate bundled SDL3, and expose libusb."""
    os.environ.setdefault("SDL_CHECK_VERSION", "0")
    os.environ.setdefault("SDL_DOC_GENERATOR", "0")
    os.environ.setdefault("SDL_CHECK_BINARY_VERSION", "0")
    os.environ.setdefault("SDL_LOG_LEVEL", "2")

    bundled = _resolve_binary_dir()
    if "SDL_BINARY_PATH" not in os.environ:
        if bundled is not None:
            _register_windows_dll_dir(bundled)
            os.environ["SDL_BINARY_PATH"] = str(bundled)
            os.environ.setdefault("SDL_DISABLE_METADATA", "1")
            os.environ.setdefault("SDL_DOWNLOAD_BINARIES", "0")
            os.environ.setdefault("SDL_FIND_BINARIES", "0")
        elif _is_packaged():
            raise RuntimeError(
                f"Bundled libusb-enabled SDL3 binary is missing under {application_dir() / 'sdl3' / 'bin'}."
            )

    if sys.platform == "win32" and (bundled is None or not (bundled / "libusb-1.0.dll").is_file()):
        try:
            import libusb_package

            libusb_path = libusb_package.get_library_path()
            if libusb_path:
                _register_windows_dll_dir(Path(libusb_path).parent)
        except ImportError:
            pass


def load_sdl3() -> Any:
    """Import and return the ``sdl3`` module once."""
    global _SDL3
    if _SDL3 is not None:
        return _SDL3
    with _LOCK:
        if _SDL3 is None:
            configure_sdl3_environment()
            import sdl3

            _SDL3 = sdl3
        return _SDL3


def sdl3_error(sdl: Any) -> str:
    """Return the latest SDL3 error message as a decoded string."""
    raw = sdl.SDL_GetError()
    return raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw or "")
