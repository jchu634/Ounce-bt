"""External Realtek firmware and persistent controller identity."""

import os
import secrets
from pathlib import Path

from lib.config import Config

FIRMWARE_NAME = "rtl8761bu_fw.bin"
CONFIG_NAME = "rtl8761bu_config.bin"
CONFIG_HEADER = bytes([0x55, 0xAB, 0x23, 0x87, 0x09, 0x00, 0x30, 0x00, 0x06])

def _address_offset(contents: bytes) -> int:
    """Find the six-byte BD_ADDR entry in a Realtek config binary."""
    if len(contents) < 6 or contents[:4] != CONFIG_HEADER[:4]:
        raise ValueError(f"{CONFIG_NAME} has an invalid header")
    if int.from_bytes(contents[4:6], "little") != len(contents) - 6:
        raise ValueError(f"{CONFIG_NAME} has an invalid length")
    offset = 6
    while offset + 3 <= len(contents):
        entry_type = int.from_bytes(contents[offset : offset + 2], "little")
        size = contents[offset + 2]
        offset += 3
        if offset + size > len(contents):
            break
        if entry_type == 0x0030 and size == 6:
            return offset
        offset += size
    raise ValueError(f"{CONFIG_NAME} has no six-byte Bluetooth address entry")


def prepare_bluetooth(config: Config, root: Path) -> None:
    """Keep the saved identity and Realtek address override in sync."""
    path = root / CONFIG_NAME
    contents = path.read_bytes()
    address_offset = _address_offset(contents)
    generated = not config.bt_address or not config.bt_address.strip()
    address = (
        "98:B6:E9:" + ":".join(f"{b:02X}" for b in secrets.token_bytes(3))
        if generated
        else config.bt_address
    )
    parts = address.split(":")
    if len(parts) != 6 or any(len(part) != 2 for part in parts):
        raise ValueError("bt_address must contain six colon-separated hex bytes")
    mac = bytes(int(part, 16) for part in parts)
    updated = contents[:address_offset] + mac[::-1] + contents[address_offset + 6 :]
    if updated != contents:
        temporary = path.with_suffix(".bin.tmp")
        temporary.write_bytes(updated)
        temporary.replace(path)
    if generated:
        config.bt_address = address
        config.save()
    # Bumble otherwise searches its own cache rather than the application root.
    os.environ["BUMBLE_RTK_FIRMWARE_DIR"] = str(root)


def missing_firmware(root: Path) -> str | None:
    for name in (FIRMWARE_NAME, CONFIG_NAME):
        path = root / name
        if not path.is_file() or not path.stat().st_size:
            return name
    return None
