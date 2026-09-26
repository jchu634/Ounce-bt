"""External Realtek firmware and persistent controller identity."""

import os
import secrets
from pathlib import Path

from lib.config import Config

FIRMWARE_NAME = "rtl8761bu_fw.bin"
CONFIG_NAME = "rtl8761bu_config.bin"
CONFIG_HEADER = bytes([0x55, 0xAB, 0x23, 0x87, 0x09, 0x00, 0x30, 0x00, 0x06])


def prepare_bluetooth(config: Config, root: Path) -> None:
    """Keep the saved identity and Realtek address override in sync."""
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
    path = root / CONFIG_NAME
    contents = CONFIG_HEADER + mac[::-1]
    if not path.is_file() or path.read_bytes() != contents:
        temporary = path.with_suffix(".bin.tmp")
        temporary.write_bytes(contents)
        temporary.replace(path)
    if generated:
        config.bt_address = address
        config.save()
    # Bumble otherwise searches its own cache rather than the application root.
    os.environ["BUMBLE_RTK_FIRMWARE_DIR"] = str(root)


def missing_firmware(root: Path) -> str | None:
    path = root / FIRMWARE_NAME
    return None if path.is_file() and path.stat().st_size else FIRMWARE_NAME
