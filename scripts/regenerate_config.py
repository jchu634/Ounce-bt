"""Give a test installation a fresh controller Bluetooth address."""

import argparse
import json
import os
import secrets
from pathlib import Path

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config" / "config.json"


def regenerate_config(path: Path) -> str:
    if path.exists():
        with path.open(encoding="utf-8") as source:
            settings = json.load(source)
        if not isinstance(settings, dict):
            raise ValueError(f"{path} must contain a JSON object")
    else:
        settings = {}

    address = "98:B6:E9:" + ":".join(f"{byte:02X}" for byte in secrets.token_bytes(3))
    settings["bt_address"] = address
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as output:
        json.dump(settings, output, indent=2)
        output.write("\n")
    os.replace(temporary, path)
    return address


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help="config.json to update (default: repository config/config.json)",
    )
    args = parser.parse_args()
    address = regenerate_config(args.config.expanduser())
    print(f"Updated {args.config}: bt_address={address}")
    print("Restart Ounce-bt to patch rtl8761bu_config.bin with this address.")


if __name__ == "__main__":
    main()
