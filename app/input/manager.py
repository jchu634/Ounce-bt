"""Coordinate manual input, macro playback, controller selection, and preset changes while broadcasting state to clients."""

from __future__ import annotations

import asyncio
import logging
import queue
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from app.input.macro_source import MacroPlayerThread
from app.input.pygame_source import PygameInputThread
from lib.input.macros import load_macro, validate_macro
from lib.input.presets import PresetConfig, PresetSelection, load_preset
from lib.input.state import NEUTRAL, Button, ControllerState

if TYPE_CHECKING:
    from app.input.controller_service import ControllerService

logger = logging.getLogger("switch_pair")


Mode = Literal["manual", "macro"]


class MacroActiveError(RuntimeError):
    """A controller/preset mutation was refused because a macro runs."""


class InputManager:
    def __init__(
        self,
        command_queue: queue.Queue,
        macros_dir: Path,
        macro_rate_hz: int = 120,
    ):
        self.command_queue = command_queue
        self.macros_dir = Path(macros_dir)
        self.macro_rate_hz = macro_rate_hz
        self.mode: Mode = "manual"
        self.pygame_threads: list[PygameInputThread] = []
        self._macro: MacroPlayerThread | None = None
        self._macro_name: str | None = None
        # Reentrant: ``on_finish`` fires from the macro thread while the
        # asyncio thread may still be inside ``cancel_macro``.
        self._lock = threading.RLock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._subscribers: list[asyncio.Queue] = []
        self._service: ControllerService | None = None
        self.current_preset: PresetConfig | None = None
        self.current_preset_name: str | None = None
    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Register the running asyncio loop so thread-side transitions can
        marshal broadcasts back onto the loop thread."""
        self._loop = loop

    def ensure_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Bind ``loop`` only when none is bound yet (the WS endpoint uses
        this so broadcasts are always marshalled thread-safely even when
        the manager was constructed outside a loop, e.g. in tests)."""
        with self._lock:
            if self._loop is None:
                self._loop = loop

    def subscribe(self) -> asyncio.Queue:
        """Get a queue that receives a status dict on every transition.
        The queue is loop-bound; consume it from the same loop."""
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass

    def _emit_frame(self, payload: dict) -> None:
        loop = self._loop
        if loop is not None and loop.is_running():
            for q in list(self._subscribers):
                try:
                    loop.call_soon_threadsafe(q.put_nowait, payload)
                except RuntimeError:
                    # Loop closed between check and schedule; drop silently.
                    pass
        else:
            for q in list(self._subscribers):
                try:
                    q.put_nowait(payload)
                except Exception:
                    logger.exception("status broadcast failed")

    def _emit_status(self) -> None:
        self._emit_frame({**self.status(), "type": "status"})

    def _emit_controllers(self) -> None:
        self._emit_frame(self.controllers_payload())

    def status(self) -> dict:
        with self._lock:
            macro_info = None
            if self._macro is not None:
                state = "paused" if self._macro.is_paused() else "running"
                macro_info = {"name": self._macro_name, "state": state}
            return {"mode": self.mode, "macro": macro_info}

    def list_macro_files(self) -> list[str]:
        """Return macro names (file stems) available under ``macros_dir``."""
        if not self.macros_dir.exists():
            return []
        return sorted(p.stem for p in self.macros_dir.glob("*.json") if p.is_file())

    def attach_pygame_threads(self, threads: list) -> None:
        """Register input threads (PygameInputThread or ControllerService —
        anything with ``pause``/``resume``/``stop``)."""
        self.pygame_threads.extend(threads)

    def set_controller_service(self, service: ControllerService) -> None:
        self._service = service

    def set_preset(self, preset: PresetConfig, source: str | None = None) -> None:
        with self._lock:
            self.current_preset = preset
            self.current_preset_name = source

    def on_controller_preset_changed(self, selection: PresetSelection) -> None:
        """Record the preset selected by the controller service."""
        self.set_preset(selection.config, selection.source)

    def controllers_payload(self) -> dict:
        """Frame payload describing devices, active selection, preset.

        Safe to call from the asyncio thread. Never call this from the
        service's own ``on_change`` callback (it would deadlock on the
        mailbox); use :meth:`on_controllers_changed` instead.
        """
        controllers: list[dict] = []
        active: str | None = None
        available = False
        if self._service is not None:
            try:
                status = self._service.status()
                controllers = status.get("controllers", [])
                active = status.get("active")
                available = bool(status.get("available"))
            except RuntimeError as e:
                logger.warning(f"controller service unavailable: {e}")
        return {
            "type": "controllers",
            "controllers": controllers,
            "active": active,
            "available": available,
            "preset": self.current_preset_name,
        }

    def on_controllers_changed(
        self, controllers: list[dict], active: str | None
    ) -> None:
        """``on_change`` callback for the ControllerService (service thread).

        Builds the frame from the callback arguments rather than querying
        the service mailbox (which would deadlock).
        """
        self._emit_frame(
            {
                "type": "controllers",
                "controllers": controllers,
                "active": active,
                "available": True,
                "preset": self.current_preset_name,
            }
        )

    def select_controller(self, ident: str | int) -> dict:
        """Switch the active physical controller. Returns its info dict.

        Raises :class:`MacroActiveError` while a macro runs and
        ``ValueError`` when no device matches.
        """
        with self._lock:
            if self.mode == "macro":
                raise MacroActiveError(
                    "cannot switch controllers while a macro is running"
                )
        if self._service is None:
            raise ValueError("no controller service is attached")
        info = self._service.select(ident)
        try:
            return info.to_dict()
        finally:
            self._emit_controllers()

    def apply_preset(self, source: str) -> PresetConfig:
        """Load, validate and apply a mapping preset at runtime.

        Raises the same errors as ``load_preset`` plus
        :class:`MacroActiveError` while a macro runs.
        """
        preset = load_preset(source)
        with self._lock:
            if self.mode == "macro":
                raise MacroActiveError(
                    "cannot switch presets while a macro is running"
                )
        self.set_preset(preset, source)
        if self._service is not None:
            self._service.set_preset(preset, source)
        logger.info(f"Applied controller preset: {preset.name}")
        self._emit_controllers()
        return preset

    def set_mode(self, mode: Mode) -> None:
        with self._lock:
            if mode == self.mode:
                return
            if mode == "macro":
                for t in self.pygame_threads:
                    t.pause()
                self.mode = "macro"
            else:  # -> manual
                if self._macro is not None:
                    self._macro.stop()
                    self._drain_and_neutralize()
                    self._clear_macro()
                for t in self.pygame_threads:
                    t.resume()
                self.mode = "manual"
        self._emit_status()

    def start_macro(self, macro: dict) -> None:
        """Start a fresh macro dict. Validates it first, cancels any
        currently running macro (immediate stop + queue drain + NEUTRAL),
        flips mode to ``macro`` and pauses physical input."""
        validate_macro(macro)
        with self._lock:
            self._cancel_internal()
            name = macro.get("name", "<unnamed>")
            thread = MacroPlayerThread(
                macro,
                self.command_queue,
                rate_hz=self.macro_rate_hz,
                on_finish=self._on_macro_finished,
            )
            self._macro = thread
            self._macro_name = name
            if self.mode != "macro":
                for t in self.pygame_threads:
                    t.pause()
                self.mode = "macro"
            thread.start()
        logger.info(f"Started macro '{name}'")
        self._emit_status()

    def start_macro_by_name(self, name: str) -> None:
        path = self.macros_dir / f"{name}.json"
        macro = load_macro(path)
        macro["name"] = name
        self.start_macro(macro)

    def cancel_macro(self) -> None:
        with self._lock:
            self._cancel_internal()
            if self.mode == "macro":
                for t in self.pygame_threads:
                    t.resume()
                self.mode = "manual"
        self._emit_status()

    def pause_macro(self) -> None:
        with self._lock:
            if self._macro is not None and not self._macro.is_paused():
                self._macro.pause()
        self._emit_status()

    def resume_macro(self) -> None:
        with self._lock:
            if self._macro is not None and self._macro.is_paused():
                self._macro.resume()
        self._emit_status()

    def submit_state(self, state: ControllerState) -> bool:
        """Enqueue an ad-hoc state. Returns True if accepted, False if the
        manager is in macro mode (caller should emit an error frame)."""
        with self._lock:
            if self.mode == "macro":
                return False
        self.command_queue.put_nowait(state)
        return True

    def shutdown(self) -> None:
        with self._lock:
            if self._macro is not None:
                self._macro.stop()
                self._clear_macro()
            for t in self.pygame_threads:
                t.stop()

    def _cancel_internal(self) -> None:
        """Stop the current macro, drain the queue, push NEUTRAL. Caller
        holds ``_lock``. Does NOT switch mode."""
        if self._macro is None:
            return
        name = self._macro_name
        self._macro.stop()
        self._drain_and_neutralize()
        self._clear_macro()
        logger.info(f"Cancelled macro '{name}'")

    def _drain_and_neutralize(self) -> None:
        """Drain whatever the macro already enqueued (so a held state
        doesn't linger for a few ticks) and push one NEUTRAL so the
        Switch releases held inputs immediately."""
        drained = 0
        while True:
            try:
                self.command_queue.get_nowait()
            except queue.Empty:
                break
            drained += 1
        self.command_queue.put_nowait(NEUTRAL)
        if drained:
            logger.debug(f"drained {drained} queued states on macro stop")

    def _clear_macro(self) -> None:
        self._macro = None
        self._macro_name = None

    def _on_macro_finished(self) -> None:
        """Invoked from the macro thread (natural end or stop). Flip back
        to manual so physical input resumes."""
        with self._lock:
            name = self._macro_name
            self._clear_macro()
            if self.mode == "macro":
                for t in self.pygame_threads:
                    t.resume()
                self.mode = "manual"
        logger.info(f"Macro '{name}' finished; returning to manual mode")
        self._emit_status()



def state_from_event(action: dict) -> ControllerState:
    """Resolve a single ``press``/``release``/``stick`` action into a
    delta-applied :class:`ControllerState`.

    ``press``/``release`` produce a state containing only that button;
    ``stick`` produces a state with the named stick moved (and the other
    at neutral). The caller is expected to merge consecutive deltas when
    accumulating button state across frames; for the common case of a
    one-shot button tap, this is sufficient.
    """
    kind = action.get("do")
    if kind == "press":
        return ControllerState(Button.by_name(action["button"]))
    if kind == "release":
        return ControllerState(Button(0))
    if kind == "stick":
        side = str(action.get("side", "left")).lower()
        x = float(action.get("x", 0.0))
        y = float(action.get("y", 0.0))
        if side == "right":
            return ControllerState(Button(0), (0.0, 0.0), (x, y))
        return ControllerState(Button(0), (x, y), (0.0, 0.0))
    raise ValueError(f"unsupported event action: {kind!r}")
