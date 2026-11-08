"""Run validated macros as a controller input source."""

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from lib.input.state import Button, ControllerState

logger = logging.getLogger("switch_pair")
SLICE_SECONDS = 0.005


class MacroPlayerThread(threading.Thread):
    """Daemon thread that plays a JSON macro onto a command queue.

    Macro schema (event-based: press / release / wait / stick / loop)::

        {
          "version": 1,
          "name": "example",
          "repeat": 0,            # 0 = loop forever, N = play N times
          "actions": [
            {"do": "press",   "button": "A"},
            {"do": "wait",    "ms": 50},
            {"do": "release", "button": "A"},
            {"do": "wait",    "ms": 50},
            {"do": "stick",   "side": "left", "x": 0.0, "y": 1.0},
            {"do": "wait",    "ms": 200},
            {"do": "stick",   "side": "left", "x": 0.0, "y": 0.0},
            {"do": "loop",    "count": 3, "actions": [
              {"do": "press",   "button": "B"},
              {"do": "wait",    "ms": 30},
              {"do": "release", "button": "B"},
              {"do": "wait",    "ms": 30}
            ]}
          ]
        }

    Button names match the ``Button`` enum (A, B, X, Y, L, R, ZL, ZR,
    UP, DOWN, LEFT, RIGHT, PLUS, MINUS, HOME, CAPTURE, STICK_L, STICK_R).
    """

    def __init__(
        self,
        macro: dict,
        command_queue,
        rate_hz: int = 120,
        on_finish: Callable[[], None] | None = None,
    ):
        super().__init__(name="macro-player", daemon=True)
        self._macro = macro
        self._queue = command_queue
        self._period = 1.0 / rate_hz
        self._stop = threading.Event()
        # Set = running, cleared = paused. Pause freezes the macro in its
        # current (possibly held) state; the steady-state snapshots are
        # not enqueued while paused, but held buttons stay held on the
        # Switch until something else enqueues a fresh state.
        self._pause = threading.Event()
        self._pause.set()
        self._buttons: set[Button] = set()
        self._left: tuple[float, float] = (0.0, 0.0)
        self._right: tuple[float, float] = (0.0, 0.0)
        self._on_finish = on_finish

    def stop(self):
        self._stop.set()
        # Make sure a paused macro can actually exit.
        self._pause.set()

    def pause(self):
        self._pause.clear()

    def resume(self):
        self._pause.set()

    def is_paused(self) -> bool:
        return not self._pause.is_set() and not self._stop.is_set()

    def run(self):
        repeat = int(self._macro.get("repeat", 1))
        name = self._macro.get("name", "<unnamed>")
        logger.info(f"Playing macro '{name}' (repeat={'∞' if repeat == 0 else repeat})")
        try:
            if repeat == 0:
                while not self._stop.is_set():
                    if not self._execute(self._macro["actions"]):
                        break
            else:
                for _ in range(repeat):
                    if self._stop.is_set():
                        break
                    if not self._execute(self._macro["actions"]):
                        break
        finally:
            # Always leave the controller idle when the macro ends.
            self._buttons.clear()
            self._left = (0.0, 0.0)
            self._right = (0.0, 0.0)
            self._queue.put(ControllerState())
            logger.info(f"Macro '{name}' finished")
            if self._on_finish is not None:
                try:
                    self._on_finish()
                except Exception:
                    logger.exception("macro on_finish callback raised")

    def _execute(self, actions: list[dict]) -> bool:
        """Execute a block of actions. Returns False if stopped."""
        for action in actions:
            if self._stop.is_set():
                return False
            kind = action.get("do")
            if kind == "press":
                self._buttons.add(Button.by_name(action["button"]))
                self._emit()
            elif kind == "release":
                self._buttons.discard(Button.by_name(action["button"]))
                self._emit()
            elif kind == "stick":
                self._apply_stick(action)
                self._emit()
            elif kind == "wait":
                self._wait(float(action.get("ms", 0)) / 1000.0)
            elif kind == "loop":
                count = int(action.get("count", 1))
                for _ in range(count):
                    if self._stop.is_set():
                        return False
                    if not self._execute(action.get("actions", [])):
                        return False
            else:
                raise ValueError(f"Unknown macro action: {kind!r}")
        return True

    def _apply_stick(self, action: dict[str, Any]):
        side = action.get("side", "left").lower()
        x = float(action.get("x", 0.0))
        y = float(action.get("y", 0.0))
        if side == "right":
            self._right = (x, y)
        else:
            self._left = (x, y)

    def _wait(self, seconds: float):
        """Hold the current state for ``seconds``, continuously enqueuing
        so the Switch keeps receiving reports at a steady rate."""
        if seconds <= 0:
            return
        end = time.perf_counter() + seconds
        while True:
            if self._stop.is_set():
                return
            # Block while paused (no enqueue, no countdown progress).
            if not self._pause.wait(timeout=SLICE_SECONDS):
                # Timed out waiting for run signal; loop and re-check stop.
                continue
            remaining = end - time.perf_counter()
            if remaining <= 0:
                return
            self._queue.put(self._snapshot())
            time.sleep(min(self._period, remaining, SLICE_SECONDS))

    def _emit(self):
        self._queue.put(self._snapshot())

    def _snapshot(self) -> ControllerState:
        flags = Button(0)
        for b in self._buttons:
            flags |= b
        return ControllerState(flags, self._left, self._right)
