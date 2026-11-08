"""Own pygame operations on one daemon thread and handle controller discovery, capture, and lifecycle requests through a thread-safe mailbox."""

from __future__ import annotations

import concurrent.futures
import logging
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.input.pygame_source import PygameInputThread
from lib.input.presets import PresetConfig, PresetSelection
from lib.input.rumble import RumbleData
from lib.input.state import NEUTRAL

logger = logging.getLogger("switch_pair")

# The service pumps events / checks for hotplug at this rate.
POLL_HZ = 20
OP_TIMEOUT_SECONDS = 5.0

# pygame 2+ constants; guarded for safety on odd builds.
_JOY_ADDED = "JOYDEVICEADDED"
_JOY_REMOVED = "JOYDEVICEREMOVED"


@dataclass(frozen=True)
class ControllerInfo:
    """One connected physical gamepad.

    ``guid`` is the SDL GUID: stable across replugs (for a given driver),
    making it the canonical identity for selection and persistence.
    ``index`` is the *current* pygame device index and shifts when devices
    are added or removed.
    """

    guid: str
    index: int
    name: str
    axes: int
    buttons: int
    hats: int

    def to_dict(self) -> dict:
        return {
            "guid": self.guid,
            "index": self.index,
            "name": self.name,
            "axes": self.axes,
            "buttons": self.buttons,
            "hats": self.hats,
        }


def resolve_controller(
    ident: str | int, controllers: list[ControllerInfo]
) -> ControllerInfo | None:
    """Match an identifier (GUID, name, or index) against a device list.

    GUID first (canonical), then exact name, then integer index.
    """
    if not controllers:
        return None
    if isinstance(ident, int):
        for c in controllers:
            if c.index == ident:
                return c
        return None
    ident = str(ident).strip().lower()
    for c in controllers:
        if c.guid.lower() == ident:
            return c
    for c in controllers:
        if c.name.lower() == ident:
            return c
    try:
        idx = int(ident)
    except ValueError:
        return None
    for c in controllers:
        if c.index == idx:
            return c
    return None


class ControllerService(threading.Thread):
    """Mailbox-driven pygame owner.

    ``on_change`` fires from the service thread whenever the device list
    or active selection changes (including hotplug); marshal it onto the
    asyncio loop in the callback (see ``InputManager``).
    """

    def __init__(
        self,
        command_queue,
        preset: PresetConfig | None = None,
        initial_ident: str | int | None = None,
        poll_hz: int = POLL_HZ,
        on_change: Callable[[list[dict], str | None], None] | None = None,
        preset_resolver: Callable[[str, str], PresetSelection] | None = None,
        on_preset_changed: Callable[[PresetSelection], None] | None = None,
        rate_hz: int = 120,
    ):
        super().__init__(name="controller-service", daemon=True)
        self._queue = command_queue
        self._preset = preset
        self._initial_ident = initial_ident
        self._on_change = on_change
        self._preset_resolver = preset_resolver
        self._on_preset_changed = on_preset_changed
        self._rate_hz = rate_hz
        self._poll_period = 1.0 / poll_hz
        self._mailbox: queue.Queue = queue.Queue()
        self._stop_event = threading.Event()
        self._pyg_ok = False
        self._controllers: list[ControllerInfo] = []
        self._active_guid: str | None = None
        self._capture: PygameInputThread | None = None
        # Mirrors the manager's macro pause state so threads created while
        # a macro runs start paused.
        self._captures_paused = False

    def set_rumble(self, rumble: RumbleData | None) -> None:
        """Publish the latest effect without blocking the Bluetooth loop."""
        capture = self._capture
        if capture is not None:
            capture.set_rumble(rumble)

    def pause(self) -> None:
        """Pause the active capture (macro starting)."""
        self._captures_paused = True
        capture = self._capture
        if capture is not None:
            capture.pause()

    def resume(self) -> None:
        """Resume the active capture (macro ended)."""
        self._captures_paused = False
        capture = self._capture
        if capture is not None:
            capture.resume()

    def is_paused(self) -> bool:
        return self._captures_paused

    def stop(self) -> None:
        self._stop_event.set()

    def status(self) -> dict:
        """Snapshot: controllers + active GUID + availability. Blocks
        briefly while the service thread answers."""
        if not self.is_alive():
            return {
                "controllers": [],
                "active": None,
                "available": False,
            }
        result = self._request("status")
        return result if isinstance(result, dict) else {"controllers": [], "active": None, "available": False}

    def enumerate(self) -> list[dict]:
        payload = self.status()
        return list(payload.get("controllers", []))

    def select(self, ident: str | int) -> ControllerInfo:
        """Switch the active device. Raises ``ValueError`` when it cannot
        be resolved. Blocks while the service swaps capture threads."""
        result = self._request("select", ident)
        if isinstance(result, Exception):
            raise result
        if not isinstance(result, ControllerInfo):
            raise TypeError(f"unexpected select result for {ident!r}")
        return result

    def set_preset(self, preset: PresetConfig, source: str | None = None) -> None:
        """Swap the mapping preset, restarting the capture on the same
        device (or applying it on next select if none is active)."""
        result = self._request("set_preset", (preset, source))
        if isinstance(result, Exception):
            raise result

    def _request(self, op: str, payload: Any = None) -> Any:
        if not self.is_alive():
            raise RuntimeError("controller service is not running")
        fut: concurrent.futures.Future = concurrent.futures.Future()
        self._mailbox.put((op, payload, fut))
        try:
            return fut.result(timeout=OP_TIMEOUT_SECONDS)
        except concurrent.futures.TimeoutError:
            raise RuntimeError(
                f"controller service did not answer '{op}' in time"
            ) from None

    def run(self) -> None:
        self._pyg_ok = self._init_pygame()
        if not self._pyg_ok:
            logger.warning(
                "ControllerService: pygame unavailable; "
                "controller enumeration and capture disabled"
            )
        try:
            if self._pyg_ok:
                self._refresh_controllers()
                selected = False
                if self._initial_ident is not None:
                    try:
                        self._do_select(self._initial_ident)
                        selected = True
                    except ValueError as e:
                        logger.warning(f"Initial controller selection failed: {e}")
                if not selected and self._controllers:
                    self._do_select(self._controllers[0].index)
                self._notify()

            while not self._stop_event.is_set():
                deadline = time.monotonic() + self._poll_period
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    try:
                        op, payload, fut = self._mailbox.get(
                            timeout=remaining
                        )
                    except queue.Empty:
                        break
                    self._handle(op, payload, fut)
                if self._pyg_ok:
                    self._pump_and_handle_hotplug()
        finally:
            self._shutdown_captures()

    def _handle(self, op: str, payload: Any, fut: concurrent.futures.Future) -> None:
        try:
            if op == "status":
                fut.set_result(
                    {
                        "controllers": [c.to_dict() for c in self._controllers],
                        "active": self._active_guid,
                        "available": self._pyg_ok,
                    }
                )
            elif op == "select":
                try:
                    fut.set_result(self._do_select(payload))
                except ValueError as e:
                    fut.set_result(e)
            elif op == "set_preset":
                preset, source = payload
                fut.set_result(self._do_set_preset(preset, source))
            elif op == "shutdown":
                self._stop_event.set()
                fut.set_result(None)
            else:
                fut.set_result(ValueError(f"unknown op: {op!r}"))
        except Exception as e:
            logger.exception(f"ControllerService op '{op}' failed")
            fut.set_result(e)

    def _init_pygame(self) -> bool:
        try:
            from pygame import display, joystick

            # The event queue requires the video subsystem, even without a
            # window or any controllers connected at startup.
            display.init()
            joystick.init()
            return True
        except Exception as e:
            logger.error(f"pygame event/joystick init failed: {e}")
            return False

    # -- pygame-side helpers (service thread only) --------------------------

    def _refresh_controllers(self) -> bool:
        """Re-enumerate devices. Returns True when the list changed."""
        from pygame import joystick

        infos: list[ControllerInfo] = []
        try:
            count = joystick.get_count()
        except Exception:
            count = 0
        for i in range(count):
            probe = None
            try:
                probe = joystick.Joystick(i)
                infos.append(
                    ControllerInfo(
                        guid=probe.get_guid(),
                        index=i,
                        name=probe.get_name(),
                        axes=probe.get_numaxes(),
                        buttons=probe.get_numbuttons(),
                        hats=probe.get_numhats(),
                    )
                )
            except Exception as e:
                logger.warning(f"failed to probe joystick {i}: {e}")
            finally:
                if probe is not None:
                    try:
                        probe.quit()
                    except Exception:
                        logger.debug("probe quit failed", exc_info=True)
        changed = infos != self._controllers
        self._controllers = infos
        return changed

    def _pump_and_handle_hotplug(self) -> None:
        import pygame
        from pygame import event as pyg_event

        try:
            pyg_event.pump()
            added = getattr(pygame, _JOY_ADDED, None)
            removed = getattr(pygame, _JOY_REMOVED, None)
            interesting = tuple(
                t for t in (added, removed) if t is not None
            )
            # Capture reads device state directly. Drain unused input events
            # too so they cannot fill the queue and crowd out hotplug events.
            hotplug_events = [e for e in pyg_event.get() if e.type in interesting]
        except Exception:
            logger.exception("controller hotplug polling failed")
            return

        if not hotplug_events:
            return

        # Creating and closing a second Joystick object for the active SDL
        # device can invalidate the object used by the capture thread. Stop
        # capture while enumeration probes devices, then reopen the selected
        # controller by its stable GUID.
        previous_guid = self._active_guid
        self._stop_capture()
        if previous_guid is not None and not self._captures_paused:
            self._queue.put(NEUTRAL)
        changed = self._refresh_controllers()
        previous = resolve_controller(previous_guid or "", self._controllers)
        if previous is not None:
            try:
                self._do_select(previous.guid)
            except ValueError:
                self._active_guid = None
        elif previous_guid is not None:
            logger.warning(
                f"Active controller ({previous_guid}) was removed"
            )
            self._active_guid = None

        if self._active_guid is None and self._controllers:
            try:
                fallback = self._do_select(self._controllers[0].index)
                logger.info(f"Fell back to '{fallback.name}'")
            except ValueError:
                pass

        if changed or self._active_guid != previous_guid:
            self._notify()

    def _do_select(self, ident: str | int) -> ControllerInfo:
        match = resolve_controller(ident, self._controllers)
        if match is None:
            names = ", ".join(c.name for c in self._controllers) or "none"
            raise ValueError(
                f"no controller matches {ident!r} (connected: {names})"
            )
        if match.guid == self._active_guid and self._capture is not None:
            return match  # already active
        self._stop_capture()
        if self._preset_resolver is not None:
            selection = self._preset_resolver(match.guid, match.name)
            self._preset = selection.config
            self._report_preset(selection)
        self._active_guid = match.guid
        self._capture = PygameInputThread(
            self._queue,
            device_index=match.index,
            preset=self._preset,
            pump=False,
            start_paused=self._captures_paused,
            rate_hz=self._rate_hz,
        )
        self._capture.start()
        logger.info(f"Controller selected: '{match.name}' ({match.guid})")
        self._notify()
        return match

    def _do_set_preset(
        self, preset: PresetConfig, source: str | None = None
    ) -> None:
        self._preset = preset
        self._report_preset(PresetSelection(source or preset.name, preset))
        active = resolve_controller(self._active_guid or "", self._controllers)
        if active is not None:
            self._stop_capture()
            self._capture = PygameInputThread(
                self._queue,
                device_index=active.index,
                preset=preset,
                pump=False,
                start_paused=self._captures_paused,
                rate_hz=self._rate_hz,
            )
            self._capture.start()
            logger.info(
                f"Applied preset '{preset.name}' to '{active.name}'"
            )
        else:
            logger.info(
                f"Preset '{preset.name}' stored; no active controller to restart"
            )

    def _report_preset(self, selection: PresetSelection) -> None:
        callback = self._on_preset_changed
        if callback is None:
            return
        try:
            callback(selection)
        except Exception:
            logger.exception("controller preset callback failed")

    def _stop_capture(self) -> None:
        capture = self._capture
        self._capture = None
        if capture is None:
            return
        capture.stop()
        capture.join(timeout=2.0)
        if capture.is_alive():
            logger.warning("previous capture thread did not stop in time")

    def _shutdown_captures(self) -> None:
        self._stop_capture()

    def _notify(self) -> None:
        cb = self._on_change
        if cb is None:
            return
        try:
            cb([c.to_dict() for c in self._controllers], self._active_guid)
        except Exception:
            logger.exception("controller on_change callback failed")
