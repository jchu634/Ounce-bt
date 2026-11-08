import re


def validate_device_name(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("device name must be text")
    name = value.strip()
    if not name or len(name) > 64:
        raise ValueError("device name must contain 1 to 64 characters")
    if any(ord(character) < 32 or ord(character) == 127 for character in name):
        raise ValueError("device name must not contain control characters")
    return name


def normalize_device_names(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        raise TypeError("switch_device_names must be an object")
    names = {}
    for address, name in value.items():
        if not isinstance(address, str) or not re.fullmatch(
            r"[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}(?:/P)?", address
        ):
            raise ValueError("device names must be keyed by a Bluetooth address")
        names[address.upper()] = validate_device_name(name)
    return names
