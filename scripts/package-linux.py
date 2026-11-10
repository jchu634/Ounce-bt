"""Bundle an existing Linux AppImage and its launcher into one release ZIP."""

import argparse
import hashlib
import shutil
from pathlib import Path
from zipfile import ZipFile, ZipInfo


def package_appimage(appimage: Path, version: str) -> Path:
    appimage = appimage.resolve()
    if not appimage.is_file() or appimage.suffix != ".AppImage":
        raise ValueError("Expected an existing .AppImage file")
    name, architecture = appimage.stem.rsplit("-", 1)
    bundle_name = f"{name}-linux-{architecture}"
    output = appimage.parent / f"{name}-{version}-linux-{architecture}.zip"
    launcher = appimage.parent / "run-with-hci-caps.sh"
    shutil.copy2(Path(__file__).resolve().with_name(launcher.name), launcher)
    # Keep the loose files executable when packaging on Linux.
    appimage.chmod(appimage.stat().st_mode | 0o111)
    launcher.chmod(0o755)
    with appimage.open("rb") as source:
        checksum = hashlib.file_digest(source, "sha256").hexdigest()
    checksum_file = appimage.with_name(f"{appimage.name}.sha256")
    checksum_file.write_text(
        f"{checksum}  {appimage.name}\n", encoding="utf-8", newline="\n"
    )
    instructions = f"""Ounce-bt for Linux

Extract this ZIP, open a terminal in the extracted {bundle_name} folder,
and run as your desktop user:

chmod +x {appimage.name} run-with-hci-caps.sh
./run-with-hci-caps.sh "$PWD/{appimage.name}" usb:0

The launcher uses sudo setpriv (util-linux) for CAP_NET_RAW and CAP_NET_ADMIN.
It keeps the application running under your desktop user and graphical session.
The selected USB adapter also needs read/write device permissions.
usb:0 selects the first Bluetooth USB adapter. To select a specific adapter,
use its USB vendor/product ID instead, for example usb:2357:0604.

On systems without FUSE, prefix the launch command with:
APPIMAGE_EXTRACT_AND_RUN=1

Verify the AppImage checksum from this folder with:
sha256sum -c {checksum_file.name}
"""
    temporary = output.with_suffix(".zip.tmp")
    try:
        # AppImages are already compressed. Store them without recompression.
        with ZipFile(temporary, "w") as archive:
            for path in (appimage, launcher, checksum_file):
                entry = ZipInfo.from_file(path, f"{bundle_name}/{path.name}")
                # Windows file modes cannot represent Unix executable permissions.
                entry.create_system = 3
                mode = 0o100644 if path == checksum_file else 0o100755
                entry.external_attr = mode << 16
                with path.open("rb") as source, archive.open(entry, "w") as target:
                    shutil.copyfileobj(source, target)
            readme = ZipInfo(f"{bundle_name}/README.txt")
            readme.create_system = 3
            readme.external_attr = 0o100644 << 16
            archive.writestr(readme, instructions)
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("appimage", type=Path)
    parser.add_argument("version", help="Application version for the release ZIP filename")
    args = parser.parse_args()
    print(f"Linux release ZIP: {package_appimage(args.appimage, args.version)}")
