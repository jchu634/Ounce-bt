"""Parse and validate WebSocket input commands and construct controller, macro, and error response frames."""
from __future__ import annotations

import json
from dataclasses import dataclass

from lib.input.state import Button, ControllerState


class ProtocolError(ValueError):
    """Raised when an inbound frame fails validation."""



@dataclass(frozen=True, slots=True)
class EventMessage:
    """A single ``press`` / ``release`` / ``stick`` action."""

    action: dict


@dataclass(frozen=True, slots=True)
class StateMessage:
    """A full controller-state snapshot (lowest-latency manual path)."""

    buttons: tuple[str, ...]
    left: tuple[float, float]
    right: tuple[float, float]

    def to_state(self) -> ControllerState:
        flags = Button(0)
        for name in self.buttons:
            flags |= Button.by_name(name)
        return ControllerState(flags, self.left, self.right)


@dataclass(frozen=True, slots=True)
class MacroStartInline:
    macro: dict


@dataclass(frozen=True, slots=True)
class MacroStartByName:
    name: str


@dataclass(frozen=True, slots=True)
class MacroCancel:
    pass


@dataclass(frozen=True, slots=True)
class MacroPause:
    pass


@dataclass(frozen=True, slots=True)
class MacroResume:
    pass


InboundMessage = (
    EventMessage
    | StateMessage
    | MacroStartInline
    | MacroStartByName
    | MacroCancel
    | MacroPause
    | MacroResume
)



_VALID_EVENT_ACTIONS = {"press", "release", "stick"}


def parse_message(raw: str) -> InboundMessage:
    """Parse a raw JSON text frame into a typed :class:`InboundMessage`.

    Raises :class:`ProtocolError` on malformed JSON, unknown ``type``,
    or shape mismatches. ``Button.by_name`` is deferred so unknown button
    names surface only when the message is applied (it raises ``KeyError``).
    """
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ProtocolError(f"invalid JSON: {e.msg}") from e
    if not isinstance(payload, dict):
        raise ProtocolError("top-level payload must be a JSON object")

    msg_type = payload.get("type")
    if msg_type == "event":
        action = payload.get("action")
        if not isinstance(action, dict):
            raise ProtocolError("'event' requires an 'action' object")
        kind = action.get("do")
        if kind not in _VALID_EVENT_ACTIONS:
            raise ProtocolError(
                f"event action 'do' must be one of {sorted(_VALID_EVENT_ACTIONS)}"
            )
        return EventMessage(action)

    if msg_type == "state":
        return StateMessage(
            buttons=_parse_buttons(payload.get("buttons", [])),
            left=_parse_xy(payload.get("left", [0.0, 0.0])),
            right=_parse_xy(payload.get("right", [0.0, 0.0])),
        )

    if msg_type == "macro":
        op = payload.get("op")
        if op == "start":
            if "macro" in payload:
                macro = payload["macro"]
                if not isinstance(macro, dict) or "actions" not in macro:
                    raise ProtocolError(
                        "'macro.start' inline payload must have 'actions'"
                    )
                return MacroStartInline(macro)
            name = payload.get("name")
            if not isinstance(name, str) or not name.strip():
                raise ProtocolError(
                    "'macro.start' requires either inline 'macro' or a 'name'"
                )
            return MacroStartByName(name.strip())
        if op == "cancel":
            return MacroCancel()
        if op == "pause":
            return MacroPause()
        if op == "resume":
            return MacroResume()
        raise ProtocolError(f"unknown macro op: {op!r}")

    raise ProtocolError(f"unknown message type: {msg_type!r}")


def _parse_buttons(value) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ProtocolError("'buttons' must be a list of button names")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ProtocolError("each button name must be a string")
        out.append(item)
    return tuple(out)


def _parse_xy(value) -> tuple[float, float]:
    if not isinstance(value, list) or len(value) != 2:
        raise ProtocolError("stick value must be a [x, y] pair")
    x, y = value
    if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
        raise ProtocolError("stick coordinates must be numbers")
    return (float(x), float(y))



def status_frame(mode: str, macro: dict | None) -> str:
    payload: dict = {"type": "status", "mode": mode}
    payload["macro"] = macro if macro is not None else None
    return json.dumps(payload)


def error_frame(message: str, detail: str | None = None) -> str:
    payload: dict = {"type": "error", "message": message}
    if detail is not None:
        payload["detail"] = detail
    return json.dumps(payload)


def macros_frame(names: list[str]) -> str:
    return json.dumps({"type": "macros", "names": names})


def frame_text(payload: dict) -> str:
    """Serialise a typed broadcast payload (``status`` / ``controllers``)
    produced by the InputManager subscriber queues."""
    return json.dumps(payload)
