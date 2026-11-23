#!/usr/bin/env python3
"""Interactively discover USB Bluetooth adapters and install Linux udev rules."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

RULES_PATH = Path("/etc/udev/rules.d/70-ounce-bt.rules")
USB_DEVICES_DIR = Path("/sys/bus/usb/devices")
BLUETOOTH_CLASS_DIR = Path("/sys/class/bluetooth")

_RULE_RE = re.compile(
    r'ATTR\{idVendor\}=="([0-9a-fA-F]{4})".*ATTR\{idProduct\}=="([0-9a-fA-F]{4})"'
)


@dataclass
class UsbBluetoothAdapter:
    vid: str
    pid: str
    manufacturer: str = ""
    product: str = ""
    count: int = 1
    hci_names: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        parts = [p for p in (self.manufacturer, self.product) if p]
        return " ".join(parts) if parts else "USB Bluetooth Adapter"

    def udev_rule(self) -> str:
        return (
            f'SUBSYSTEM=="usb", ATTR{{idVendor}}=="{self.vid}", '
            f'ATTR{{idProduct}}=="{self.pid}", TAG+="uaccess"'
        )


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def _is_bluetooth_usb_device(dev_dir: Path) -> bool:
    """Return True if the USB device or any of its interfaces is Bluetooth (e0/01/01)."""
    if (
        _read_text(dev_dir / "bDeviceClass").lower() == "e0"
        and _read_text(dev_dir / "bDeviceSubClass").lower() == "01"
        and _read_text(dev_dir / "bDeviceProtocol").lower() == "01"
    ):
        return True
    prefix = f"{dev_dir.name}:"
    for child in dev_dir.iterdir():
        if not child.name.startswith(prefix) or not child.is_dir():
            continue
        if (
            _read_text(child / "bInterfaceClass").lower() == "e0"
            and _read_text(child / "bInterfaceSubClass").lower() == "01"
            and _read_text(child / "bInterfaceProtocol").lower() == "01"
        ):
            return True
    return False


def _usb_device_for_hci(hci_dir: Path) -> Path | None:
    """Walk up from /sys/class/bluetooth/hciX/device to its parent USB device dir."""
    device_link = hci_dir / "device"
    if not device_link.exists():
        return None
    current = device_link.resolve()
    for candidate in (current, *current.parents):
        if (candidate / "idVendor").is_file() and (candidate / "idProduct").is_file():
            return candidate
    return None


def discover_usb_bluetooth_adapters(
    usb_devices_dir: Path = USB_DEVICES_DIR,
    bluetooth_class_dir: Path = BLUETOOTH_CLASS_DIR,
) -> list[UsbBluetoothAdapter]:
    """Discover connected USB Bluetooth adapters, grouped by (vid, pid)."""
    hci_by_usb_path: dict[Path, list[str]] = {}
    if bluetooth_class_dir.is_dir():
        for hci_dir in sorted(bluetooth_class_dir.iterdir()):
            if not hci_dir.name.startswith("hci"):
                continue
            usb_dir = _usb_device_for_hci(hci_dir)
            if usb_dir is not None:
                hci_by_usb_path.setdefault(usb_dir, []).append(hci_dir.name)

    candidate_dirs: dict[Path, None] = {}
    if usb_devices_dir.is_dir():
        for dev_dir in sorted(usb_devices_dir.iterdir()):
            if not dev_dir.is_dir():
                continue
            if not ((dev_dir / "idVendor").is_file() and (dev_dir / "idProduct").is_file()):
                continue
            resolved = dev_dir.resolve()
            if resolved in hci_by_usb_path or _is_bluetooth_usb_device(dev_dir):
                candidate_dirs[resolved] = None

    for usb_dir in hci_by_usb_path:
        candidate_dirs.setdefault(usb_dir, None)

    grouped: dict[tuple[str, str], UsbBluetoothAdapter] = {}
    for usb_dir in candidate_dirs:
        vid = _read_text(usb_dir / "idVendor").lower()
        pid = _read_text(usb_dir / "idProduct").lower()
        if len(vid) != 4 or len(pid) != 4:
            continue
        key = (vid, pid)
        hci_names = hci_by_usb_path.get(usb_dir, [])
        if key in grouped:
            grouped[key].count += 1
            grouped[key].hci_names.extend(hci_names)
        else:
            grouped[key] = UsbBluetoothAdapter(
                vid=vid,
                pid=pid,
                manufacturer=_read_text(usb_dir / "manufacturer"),
                product=_read_text(usb_dir / "product"),
                count=1,
                hci_names=list(hci_names),
            )

    for adapter in grouped.values():
        adapter.hci_names.sort()
    return list(grouped.values())


def read_existing_rule_ids(rules_path: Path = RULES_PATH) -> set[tuple[str, str]]:
    """Return (vid, pid) pairs already present in the udev rules file."""
    if not rules_path.is_file():
        return set()
    ids: set[tuple[str, str]] = set()
    for line in _read_text(rules_path).splitlines():
        match = _RULE_RE.search(line)
        if match:
            ids.add((match.group(1).lower(), match.group(2).lower()))
    return ids


def parse_selection(raw: str, total: int) -> list[int]:
    """Parse user selection like 'all', '1,3', or '1 2' into sorted 0-based indices."""
    text = raw.strip().lower()
    if text in {"a", "all", "*"}:
        return list(range(total))
    indices: set[int] = set()
    for token in re.split(r"[,\s]+", text):
        if not token:
            continue
        if not token.isdigit():
            raise ValueError(f"Invalid selection: {token!r}")
        idx = int(token)
        if idx < 1 or idx > total:
            raise ValueError(f"Selection out of range: {idx} (expected 1-{total})")
        indices.add(idx - 1)
    if not indices:
        raise ValueError("No adapters selected")
    return sorted(indices)


def build_rules_content(
    selected: list[UsbBluetoothAdapter],
    existing_ids: set[tuple[str, str]] | None = None,
) -> str:
    """Build the 70-ounce-bt.rules file content, preserving any existing VID:PID rules."""
    lines = ["# Ounce-bt USB Bluetooth adapter permissions (generated by setup-linux-udev.py)"]
    seen: set[tuple[str, str]] = set()
    for adapter in selected:
        key = (adapter.vid, adapter.pid)
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"# {adapter.label}")
        lines.append(adapter.udev_rule())
    for vid, pid in sorted(existing_ids or set()):
        if (vid, pid) in seen:
            continue
        seen.add((vid, pid))
        lines.append(
            f'SUBSYSTEM=="usb", ATTR{{idVendor}}=="{vid}", '
            f'ATTR{{idProduct}}=="{pid}", TAG+="uaccess"'
        )
    return "\n".join(lines) + "\n"


def apply_rules(
    content: str,
    selected: list[UsbBluetoothAdapter],
    rules_path: Path = RULES_PATH,
) -> None:
    """Write rules_path and reload/trigger udev for the selected adapters."""
    prefix = [] if subprocess.os.geteuid() == 0 else ["sudo"]
    subprocess.run(
        [*prefix, "tee", str(rules_path)],
        input=content,
        text=True,
        stdout=subprocess.DEVNULL,
        check=True,
    )
    subprocess.run([*prefix, "udevadm", "control", "--reload-rules"], check=True)
    for adapter in selected:
        subprocess.run(
            [
                *prefix,
                "udevadm",
                "trigger",
                "--subsystem-match=usb",
                f"--attr-match=idVendor={adapter.vid}",
                f"--attr-match=idProduct={adapter.pid}",
            ],
            check=True,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Discover USB Bluetooth adapters and install Ounce-bt Linux udev rules."
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Select all discovered USB Bluetooth adapters without prompting.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the generated udev rules without writing or reloading udev.",
    )
    args = parser.parse_args(argv)

    if sys.platform != "linux":
        print("This script is only supported on Linux.", file=sys.stderr)
        return 1

    adapters = discover_usb_bluetooth_adapters()
    if not adapters:
        print("No USB Bluetooth adapters were detected in /sys/bus/usb/devices.")
        return 1

    existing_ids = read_existing_rule_ids()

    print("Discovered USB Bluetooth adapters:\n")
    for idx, adapter in enumerate(adapters, start=1):
        count_note = f" x{adapter.count}" if adapter.count > 1 else ""
        hci_note = f" [{', '.join(adapter.hci_names)}]" if adapter.hci_names else ""
        status = " (already in rules)" if (adapter.vid, adapter.pid) in existing_ids else ""
        print(
            f"  {idx}. {adapter.vid}:{adapter.pid}  {adapter.label}"
            f"{count_note}{hci_note}{status}"
        )
    print()

    if args.all:
        selected = adapters
    else:
        while True:
            try:
                raw = input("Select adapters (e.g. 1,2 or 'all', 'q' to quit): ")
            except (EOFError, KeyboardInterrupt):
                print("\nCancelled.")
                return 1
            if raw.strip().lower() in {"q", "quit"}:
                print("Cancelled.")
                return 0
            try:
                chosen_indices = parse_selection(raw, len(adapters))
            except ValueError as error:
                print(f"  {error}")
                continue
            selected = [adapters[i] for i in chosen_indices]
            break

    content = build_rules_content(selected, existing_ids)
    print(f"\nGenerated {RULES_PATH}:\n")
    print(content, end="")

    if args.dry_run:
        return 0

    if not args.all:
        try:
            confirm = input(f"\nWrite {RULES_PATH} and reload udev rules? [Y/n]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled.")
            return 1
        if confirm not in {"", "y", "yes"}:
            print("Cancelled.")
            return 0

    try:
        apply_rules(content, selected)
    except subprocess.CalledProcessError as error:
        print(f"\nFailed to apply udev rules (exit code {error.returncode}).", file=sys.stderr)
        return error.returncode

    print("\nudev rules installed and applied.")
    print("If an adapter still reports permission denied, unplug and reconnect it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
