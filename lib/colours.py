import re

from lib.controller import ControllerVariant

DEFAULT_CONTROLLER_COLOURS = {
    "body": "#000000",
    "buttons": "#FFFFFF",
    "left_grip": "#828282",
    "right_grip": "#828282",
}


def default_colours(variant: ControllerVariant) -> dict[str, str]:
    if variant == ControllerVariant.LEFT:
        return {"body": "#00B9D6", "buttons": "#001E1E"}
    if variant == ControllerVariant.RIGHT:
        return {"body": "#FF3C28", "buttons": "#1E0A0A"}
    return dict(DEFAULT_CONTROLLER_COLOURS)


def normalize_controller_colours(
    value: object, base: dict[str, str] | None = None
) -> dict[str, str]:
    """Validate a partial colour update and return a complete RGB hex palette."""
    if not isinstance(value, dict):
        raise TypeError("controller_colours must be an object")
    colours = dict(DEFAULT_CONTROLLER_COLOURS if base is None else base)
    for name, colour in value.items():
        if name not in colours:
            raise ValueError(f"unknown controller colour: {name}")
        if (
            not isinstance(colour, str)
            or re.fullmatch(r"#[0-9a-fA-F]{6}", colour) is None
        ):
            raise ValueError(f"{name} must be a colour in #RRGGBB format")
        colours[name] = colour.upper()
    return colours
