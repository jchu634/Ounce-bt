from __future__ import annotations

import logging
import threading
import time

# TODO Make Lazy for python 3.15
from pygame import event, joystick
from pygame import init as pygame_init

from lib.input.presets import PresetConfig
from lib.input.state import Button, ControllerState

logger = logging.getLogger("switch_pair")


# Default mapping from an Xbox/SDL-style gamepad (pygame button indices)
# to Switch buttons. Nintendo labels sit in the *positions* Xbox uses for
# the other letter, so we swap A/B and X/Y to keep physical placement
# (bottom = primary action). These values are used when no ``preset`` is
# supplied; a :class:`PresetConfig` overrides every map below at once.
DEFAULT_BUTTON_MAP: dict[int, Button] = {
    0: Button.B,  # Xbox A  -> Nintendo B (bottom)
    1: Button.A,  # Xbox B  -> Nintendo A (right)
    2: Button.Y,  # Xbox X  -> Nintendo Y (left)
    3: Button.X,  # Xbox Y  -> Nintendo X (top)
    4: Button.L,  # LB
    5: Button.R,  # RB
    6: Button.MINUS,  # Back
    7: Button.PLUS,  # Start
    8: Button.STICK_L,  # Left stick click
    9: Button.STICK_R,  # Right stick click
    10: Button.HOME,  # Guide
}

# Analog trigger axes treated as digital above ``trigger_threshold``.
DEFAULT_TRIGGER_MAP: dict[int, Button] = {4: Button.ZL, 5: Button.ZR}
DEFAULT_LEFT_STICK: tuple[int, int] = (0, 1)
DEFAULT_RIGHT_STICK: tuple[int, int] = (2, 3)
DEFAULT_DPAD_HAT: int | None = 0


class PygameInputThread(threading.Thread):
    """Daemon thread that polls a physical gamepad via pygame and pushes
    ``ControllerState`` snapshots onto a thread-safe command queue.

    ``pump=False`` when running under :class:`ControllerService`, which
    owns the pygame event pump (hotplug detection) on its own thread.
    ``start_paused=True`` creates the thread already paused (used when a
    macro is running and the device is switched underneath it).
    """

    def __init__(
        self,
        command_queue,
        device_index: int = 0,
        rate_hz: int = 120,
        deadzone: float = 0.12,
        trigger_threshold: float = 0.30,
        button_map: dict[int, Button] | None = None,
        preset: PresetConfig | None = None,
        pump: bool = True,
        start_paused: bool = False,
    ):
        super().__init__(name="pygame-input", daemon=True)
        self._queue = command_queue
        self._device_index = device_index
        self._period = 1.0 / rate_hz
        self._deadzone = deadzone
        self._trigger_threshold = trigger_threshold
        self._pump = pump

        # Preset is primary source of truth
        if preset is not None:
            self._button_map = preset.button_map
            self._trigger_map = preset.trigger_map
            self._left_stick = preset.left_stick
            self._right_stick = preset.right_stick
            self._dpad_hat = preset.dpad_hat
        else:
            self._button_map = button_map or DEFAULT_BUTTON_MAP
            self._trigger_map = DEFAULT_TRIGGER_MAP
            self._left_stick = DEFAULT_LEFT_STICK
            self._right_stick = DEFAULT_RIGHT_STICK
            self._dpad_hat = DEFAULT_DPAD_HAT
        self._stop_event = threading.Event()

        # Set = running, cleared = paused.
        # While paused keep pumping pygame events but skip enqueuing snapshots
        self._pause = threading.Event()
        if not start_paused:
            self._pause.set()

    def stop(self):
        self._stop_event.set()
        # Release a paused thread so it can observe the stop event and exit.
        self._pause.set()

    def pause(self):
        self._pause.clear()

    def resume(self):
        self._pause.set()

    def is_paused(self) -> bool:
        return not self._pause.is_set() and not self._stop_event.is_set()

    def run(self):
        try:
            if self._pump:
                pygame_init()
        except Exception as e1:
            logger.error(f"pygame init failed, falling back to joystick init: {e1}")
            # Headless / no-display environments: fall back to joystick-only.
            try:
                joystick.init()
            except Exception as e:
                logger.error(f"pygame init failed: {e}")
                return

        stick = None
        try:
            count = joystick.get_count()
            if count <= self._device_index:
                logger.error(
                    f"No joystick at index {self._device_index} ({count} detected)"
                )
                return
            stick = joystick.Joystick(self._device_index)
            stick.init()
            logger.info(
                f"Pygame input following '{stick.get_name()}' "
                f"({stick.get_numaxes()} axes, {stick.get_numbuttons()} "
                f"buttons, {stick.get_numhats()} hats)"
            )
            self._loop(stick)
        except Exception:
            logger.exception("Pygame input thread crashed")
        finally:
            # Close only this instance; ``joystick.quit()`` tears down whole module
            # and any other open devices (e.g. probes from the ControllerService enumeration).
            if stick is not None:
                try:
                    stick.quit()
                except Exception:
                    logger.debug("failed to close pygame joystick", exc_info=True)

    def _loop(self, stick):
        n_axes = stick.get_numaxes()
        n_buttons = stick.get_numbuttons()
        n_hats = stick.get_numhats()

        while not self._stop_event.is_set():
            # Some SDL drivers accumulate state internally and can stall if
            # event.pump() stops being called. When a ControllerService owns
            # the pump we skip it here; otherwise pump defensively even
            # while paused. We just skip the enqueue when paused.
            if self._pump:
                event.pump()
            if not self._pause.is_set():
                time.sleep(self._period)
                continue

            buttons = Button(0)

            for i in range(n_buttons):
                if i not in self._button_map:
                    continue
                if stick.get_button(i):
                    buttons |= self._button_map[i]

            # Analog triggers — treat as digital above a threshold.
            for i, btn in self._trigger_map.items():
                if i >= n_axes:
                    continue
                v = stick.get_axis(i)
                if v >= self._trigger_threshold:
                    buttons |= btn

            lx, ly = self._axis(stick, *self._left_stick, n_axes)
            rx, ry = self._axis(stick, *self._right_stick, n_axes)

            # D-pad from the configured hat (if any).
            if self._dpad_hat is not None and self._dpad_hat < n_hats:
                hx, hy = stick.get_hat(self._dpad_hat)
                if hx < 0:
                    buttons |= Button.LEFT
                elif hx > 0:
                    buttons |= Button.RIGHT
                if hy < 0:
                    buttons |= Button.DOWN
                elif hy > 0:
                    buttons |= Button.UP

            self._queue.put(ControllerState(buttons, (lx, ly), (rx, ry)))
            time.sleep(self._period)

    def _axis(self, stick, ix, iy, n_axes):
        if ix >= n_axes or iy >= n_axes:
            return 0.0, 0.0
        x = self._deadzone_apply(stick.get_axis(ix))
        y = self._deadzone_apply(stick.get_axis(iy))
        # SDL reports Y positive = down; flip so up is positive.
        return x, -y

    def _deadzone_apply(self, v):
        if abs(v) <= self._deadzone:
            return 0.0
        # Rescale outside the deadzone so the stick feels responsive.
        sign = 1.0 if v > 0 else -1.0
        return sign * min(1.0, abs(v))
