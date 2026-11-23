"""Validate Realtek firmware files and synchronise the saved Bluetooth identity with the firmware configuration."""

import lzma
import os
import secrets
from collections.abc import Sequence
from pathlib import Path

from lib.config import Config

FIRMWARE_NAME = "rtl8761bu_fw.bin"
CONFIG_NAME = "rtl8761bu_config.bin"
CONFIG_HEADER = bytes([0x55, 0xAB, 0x23, 0x87, 0x09, 0x00, 0x30, 0x00, 0x06])
LINUX_SYSTEM_FIRMWARE_DIRS = (
    Path("/lib/firmware/rtl_bt"),
    Path("/usr/lib/firmware/rtl_bt"),
)

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


def prepare_bluetooth(
    config: Config, root: Path, *, address_override: str | None = None
) -> None:
    """Keep the saved identity and Realtek address override in sync."""
    generated = not address_override and (not config.bt_address or not config.bt_address.strip())
    address = address_override or (
        "98:B6:E9:" + ":".join(f"{b:02X}" for b in secrets.token_bytes(3))
        if generated
        else config.bt_address
    )
    patch_address(root / CONFIG_NAME, root / CONFIG_NAME, address)
    if generated:
        config.bt_address = address
        config.save()
    # Bumble otherwise searches its own cache rather than the application root.
    os.environ["BUMBLE_RTK_FIRMWARE_DIR"] = str(root)


def patch_address_bytes(contents: bytes, address: str) -> bytes:
    parts = address.split(":")
    if len(parts) != 6 or any(len(part) != 2 for part in parts):
        raise ValueError("bt_address must contain six colon-separated hex bytes")
    mac = bytes(int(part, 16) for part in parts)
    if contents == CONFIG_HEADER[:4] + b"\x00\x00":
        return CONFIG_HEADER + mac[::-1]
    address_offset = _address_offset(contents)
    return contents[:address_offset] + mac[::-1] + contents[address_offset + 6 :]


def patch_address(source: Path, path: Path, address: str) -> None:
    contents = source.read_bytes()
    updated = patch_address_bytes(contents, address)
    if source != path or updated != contents:
        temporary = path.with_suffix(".bin.tmp")
        temporary.write_bytes(updated)
        temporary.replace(path)


def read_firmware_bytes(name: str, search_dirs: Sequence[Path]) -> bytes | None:
    """Read a Realtek firmware/config file (plain or .xz) from the first matching dir."""
    for directory in search_dirs:
        plain = directory / name
        if plain.is_file() and plain.stat().st_size:
            return plain.read_bytes()
        xz_path = directory / f"{name}.xz"
        if xz_path.is_file() and xz_path.stat().st_size:
            return lzma.decompress(xz_path.read_bytes())
    return None


def stage_linux_firmware(
    search_dirs: Sequence[Path], target_dir: Path, address: str
) -> bool:
    """Stage decompressed Realtek firmware with a per-adapter BD_ADDR on Linux."""
    fw_bytes = read_firmware_bytes(FIRMWARE_NAME, search_dirs)
    cfg_bytes = read_firmware_bytes(CONFIG_NAME, search_dirs)
    if fw_bytes is None or cfg_bytes is None:
        return False
    patched_cfg = patch_address_bytes(cfg_bytes, address)
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / FIRMWARE_NAME).write_bytes(fw_bytes)
    (target_dir / CONFIG_NAME).write_bytes(patched_cfg)
    return True


def missing_firmware(root: Path) -> str | None:
    for name in (FIRMWARE_NAME, CONFIG_NAME):
        path = root / name
        if not path.is_file() or not path.stat().st_size:
            return name
    return None
