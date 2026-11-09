from __future__ import annotations

import logging
import threading
import time

# TODO Make Lazy for python 3.15
from pygame import event, joystick
from pygame import init as pygame_init
from pygame._sdl2 import controller as sdl_controller

from lib.input.presets import PresetConfig
from lib.input.rumble import RumbleData
from lib.input.state import Button, ControllerState

logger = logging.getLogger("switch_pair")

RUMBLE_TIMEOUT_SECONDS = 0.25
RUMBLE_DURATION_MS = 100
RUMBLE_REFRESH_SECONDS = 0.05


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


class XboxGamepad:
    """Expose SDL's portable controller layout using the Xbox preset indices.

    Raw joystick indices differ between Linux, Windows and device drivers.
    SDL resolves those differences, including trigger ranges and D-pad buttons.
    Keep the historical preset indices so custom raw presets remain compatible.
    """

    # SDL: A B X Y, shoulders, back/start, stick clicks, guide.
    _BUTTONS = (0, 1, 2, 3, 9, 10, 4, 6, 7, 8, 5)

    def __init__(self, controller, stick):
        self._controller = controller
        self._stick = stick

    def get_numaxes(self):
        return 6

    def get_numbuttons(self):
        return len(self._BUTTONS)

    def get_numhats(self):
        return 1

    def get_axis(self, index):
        value = self._controller.get_axis(index)
        if index >= 4:
            # SDL triggers are 0..32767; the raw Xbox preset expects -1..1.
            return max(-1.0, min(1.0, value / 32767.0 * 2.0 - 1.0))
        return max(-1.0, min(1.0, value / 32767.0))

    def get_button(self, index):
        return self._controller.get_button(self._BUTTONS[index])

    def get_hat(self, index):
        # SDL D-pad: up=11, down=12, left=13, right=14.
        button = self._controller.get_button
        return int(button(14)) - int(button(13)), int(button(11)) - int(button(12))

    def rumble(self, *args):
        return self._stick.rumble(*args)

    def stop_rumble(self):
        return self._stick.stop_rumble()


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

        self._standard_gamepad = (
            preset.standard_gamepad if preset is not None else button_map is None
        )

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
        self._rumble_lock = threading.Lock()
        self._rumble = (0.0, 0.0)
        self._rumble_deadline = 0.0
        self._rumble_playing = False
        self._rumble_supported = True
        self._rumble_refresh = 0.0
        self._played_rumble = (0.0, 0.0)
        self._stop_event = threading.Event()

        # Set = running, cleared = paused.
        # While paused keep pumping pygame events but skip enqueuing snapshots
        self._pause = threading.Event()
        if not start_paused:
            self._pause.set()

    def set_rumble(self, rumble: RumbleData | None) -> None:
        with self._rumble_lock:
            self._rumble = rumble.strengths() if rumble is not None else (0.0, 0.0)
            self._rumble_deadline = time.monotonic() + RUMBLE_TIMEOUT_SECONDS

    def _update_rumble(self, stick) -> None:
        if not self._rumble_supported:
            return
        now = time.monotonic()
        with self._rumble_lock:
            strengths = self._rumble if now < self._rumble_deadline else (0.0, 0.0)
        try:
            if strengths == (0.0, 0.0):
                if self._rumble_playing:
                    stick.stop_rumble()
                    self._rumble_playing = False
            elif (
                not self._rumble_playing
                or now >= self._rumble_refresh
                or strengths != self._played_rumble
            ):
                # Refresh a finite effect. SDL also stops it if this thread dies.
                self._rumble_supported = stick.rumble(*strengths, RUMBLE_DURATION_MS)
                self._rumble_playing = self._rumble_supported
                self._played_rumble = strengths
                self._rumble_refresh = now + RUMBLE_REFRESH_SECONDS
                if not self._rumble_supported:
                    logger.info("Selected controller does not support vibration")
        except Exception:
            self._rumble_supported = False
            logger.warning("Controller vibration unavailable", exc_info=True)

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
        gamepad = None
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
            source = stick
            if self._standard_gamepad:
                sdl_controller.init()
                if sdl_controller.is_controller(self._device_index):
                    gamepad = sdl_controller.Controller(self._device_index)
                    source = XboxGamepad(gamepad, stick)
                    logger.info("Using SDL's portable Xbox controller mapping")
                else:
                    logger.warning("SDL has no controller mapping; using raw preset indices")
            self._loop(source)
        except Exception:
            logger.exception("Pygame input thread crashed")
        finally:
            if gamepad is not None:
                gamepad.quit()
            # Close only this instance; ``joystick.quit()`` tears down whole module
            # and any other open devices (e.g. probes from the ControllerService enumeration).
            if stick is not None:
                try:
                    try:
                        if self._rumble_playing:
                            stick.stop_rumble()
                    finally:
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
            self._update_rumble(stick)
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
