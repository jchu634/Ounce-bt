"""Build SDL3 from source with SDL_HIDAPI_LIBUSB enabled and verify Switch 2 support."""

from __future__ import annotations

import argparse
import hashlib
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

SDL3_VERSION = "3.4.20"
SDL3_URL = f"https://github.com/libsdl-org/SDL/releases/download/release-{SDL3_VERSION}/SDL3-{SDL3_VERSION}.tar.gz"
SDL3_SHA256 = "f3bb06f55bed9557227a700af2ea62e49497ebdf58037732a731a5fb3ef8581f"
LIBUSB_VERSION = "1.0.30"
LIBUSB_URL = f"https://github.com/libusb/libusb/releases/download/v{LIBUSB_VERSION}/libusb-{LIBUSB_VERSION}.tar.bz2"
LIBUSB_SHA256 = "fea36f34f9156400209595e300840767ab1a385ede1dc7ee893015aea9c6dbaf"

REQUIRED_BINARY_MARKERS = (b"HIDAPI_SWITCH2", b"libusb-1.0")


def _download(url: str, dest: Path, expected_sha256: str | None = None) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and (
        expected_sha256 is None
        or hashlib.sha256(dest.read_bytes()).hexdigest() == expected_sha256
    ):
        return dest
    print(f"Downloading {url} ...", flush=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    with urllib.request.urlopen(url, timeout=60) as resp, open(tmp, "wb") as out:
        shutil.copyfileobj(resp, out)
    if expected_sha256 is not None:
        actual = hashlib.sha256(tmp.read_bytes()).hexdigest()
        if actual != expected_sha256:
            tmp.unlink(missing_ok=True)
            raise RuntimeError(f"SHA-256 mismatch for {url}: expected {expected_sha256}, got {actual}")
    os.replace(tmp, dest)
    return dest


def _extract_tar(archive: Path, target_dir: Path, sentinel: Path) -> None:
    if sentinel.exists():
        return
    target_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:*") as tf:
        tf.extractall(target_dir, filter="data")


def _find_msvc_lib_exe() -> Path:
    if found := shutil.which("lib.exe"):
        return Path(found)
    vswhere = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / (
        "Microsoft Visual Studio/Installer/vswhere.exe"
    )
    if vswhere.is_file():
        install = subprocess.check_output(
            [str(vswhere), "-latest", "-products", "*", "-property", "installationPath"],
            text=True,
        ).strip()
        if install:
            tools = Path(install) / "VC/Tools/MSVC"
            for candidate in sorted(tools.glob("*/bin/Hostx64/x64/lib.exe"), reverse=True):
                return candidate
    raise RuntimeError("Could not locate MSVC lib.exe to generate libusb-1.0.lib")


def _prepare_windows_libusb(work_dir: Path) -> tuple[Path, Path]:
    archive = _download(LIBUSB_URL, work_dir / f"libusb-{LIBUSB_VERSION}.tar.bz2", LIBUSB_SHA256)
    src_root = work_dir / f"libusb-{LIBUSB_VERSION}"
    header = src_root / "libusb" / "libusb.h"
    _extract_tar(archive, work_dir, header)
    def_file = src_root / "libusb" / "libusb-1.0.def"
    if not header.is_file() or not def_file.is_file():
        raise RuntimeError(f"Missing libusb.h or libusb-1.0.def under {src_root}")

    machine = "ARM64" if platform.machine().lower() in ("arm64", "aarch64") else "X64"
    implib = work_dir / "libusb-1.0.lib"
    if not implib.is_file():
        lib_exe = _find_msvc_lib_exe()
        subprocess.run(
            [
                str(lib_exe),
                "/nologo",
                f"/def:{def_file}",
                "/name:libusb-1.0.dll",
                f"/out:{implib}",
                f"/machine:{machine}",
            ],
            check=True,
        )
    return header.parent, implib


def verify_sdl3_binary(path: Path) -> None:
    """Fail if the compiled SDL3 binary was built without libusb / Switch 2 support."""
    if not path.is_file():
        raise RuntimeError(f"Missing SDL3 binary: {path}")
    data = path.read_bytes()
    missing = [marker.decode() for marker in REQUIRED_BINARY_MARKERS if marker not in data]
    if missing:
        raise RuntimeError(
            f"SDL3 binary {path} was built without required libusb/Switch 2 support "
            f"(missing: {', '.join(missing)})"
        )


def _output_library_path(output_dir: Path) -> Path:
    if sys.platform == "win32":
        return output_dir / "SDL3.dll"
    return output_dir / "libSDL3.so.0"


def build_sdl3(work_dir: Path, output_dir: Path, *, force: bool = False) -> Path:
    target = _output_library_path(output_dir)
    ready = target.is_file() and (
        sys.platform != "win32" or (output_dir / "libusb-1.0.dll").is_file()
    )
    if not force and ready:
        try:
            verify_sdl3_binary(target)
            print(f"Using verified libusb-enabled SDL3 binary: {target}", flush=True)
            return target
        except RuntimeError:
            pass

    work_dir.mkdir(parents=True, exist_ok=True)
    archive = _download(SDL3_URL, work_dir / f"SDL3-{SDL3_VERSION}.tar.gz", SDL3_SHA256)
    src_dir = work_dir / f"SDL3-{SDL3_VERSION}"
    _extract_tar(archive, work_dir, src_dir / "CMakeLists.txt")

    build_dir = work_dir / "cmake-build"
    cmake_args = [
        "cmake",
        "-S",
        str(src_dir),
        "-B",
        str(build_dir),
        "-DBUILD_SHARED_LIBS=ON",
        "-DSDL_SHARED=ON",
        "-DSDL_STATIC=OFF",
        "-DSDL_TEST_LIBRARY=OFF",
        "-DSDL_TESTS=OFF",
        "-DSDL_EXAMPLES=OFF",
        "-DSDL_HIDAPI=ON",
        "-DSDL_HIDAPI_LIBUSB=ON",
        "-DSDL_HIDAPI_LIBUSB_SHARED=ON",
    ]
    if sys.platform == "win32":
        include_dir, implib = _prepare_windows_libusb(work_dir)
        arch = "ARM64" if platform.machine().lower() in ("arm64", "aarch64") else "x64"
        cmake_args += [
            "-A",
            arch,
            f"-DLibUSB_INCLUDE_PATH={include_dir}",
            f"-DLibUSB_LIBRARY={implib}",
        ]
    else:
        cmake_args += ["-DCMAKE_BUILD_TYPE=Release"]
        if shutil.which("ninja"):
            cmake_args += ["-G", "Ninja"]

    subprocess.run(cmake_args, check=True)

    cache_text = (build_dir / "CMakeCache.txt").read_text(encoding="utf-8", errors="replace")
    if "HAVE_HIDAPI_LIBUSB:INTERNAL=1" not in cache_text and "HAVE_LIBUSB_H:INTERNAL=1" not in cache_text:
        raise RuntimeError(
            "SDL3 CMake configuration did not enable libusb (HAVE_HIDAPI_LIBUSB is off). "
            "Install libusb-1.0 development files and retry."
        )

    build_cmd = ["cmake", "--build", str(build_dir), "--target", "SDL3-shared", "--parallel"]
    if sys.platform == "win32":
        build_cmd += ["--config", "Release"]
    subprocess.run(build_cmd, check=True)

    output_dir.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        built = build_dir / "Release" / "SDL3.dll"
        if not built.is_file():
            built = build_dir / "SDL3.dll"
        verify_sdl3_binary(built)
        shutil.copy2(built, target)
        # Stage libusb-1.0.dll alongside SDL3.dll so SDL_LoadObject("libusb-1.0.dll") always succeeds.
        import libusb_package

        libusb_dll = Path(libusb_package.get_library_path())
        shutil.copy2(libusb_dll, output_dir / "libusb-1.0.dll")
    else:
        candidates = sorted(build_dir.glob("libSDL3.so*"))
        real_libs = [p for p in candidates if p.is_file() and not p.is_symlink()]
        if not real_libs:
            raise RuntimeError(f"Could not find built libSDL3.so* in {build_dir}")
        verify_sdl3_binary(real_libs[0])
        for old in output_dir.glob("libSDL3.so*"):
            old.unlink()
        shutil.copy2(real_libs[0], target)
        verify_sdl3_binary(target)

    print(f"Built verified libusb-enabled SDL3 binary: {target}", flush=True)
    return target


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=repo_root / "build" / "sdl3",
        help="Working directory for SDL3 source and CMake build files",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=repo_root / "build" / "sdl3" / "bin",
        help="Output directory for the built SDL3 shared library",
    )
    parser.add_argument("--force", action="store_true", help="Force a clean rebuild")
    parser.add_argument(
        "--verify",
        type=Path,
        default=None,
        help="Verify an existing SDL3 shared library has libusb/Switch 2 support and exit",
    )
    args = parser.parse_args()
    if args.verify is not None:
        verify_sdl3_binary(args.verify.resolve())
        print(f"Verified libusb-enabled SDL3 binary: {args.verify}", flush=True)
        return
    build_sdl3(args.work_dir.resolve(), args.output_dir.resolve(), force=args.force)


if __name__ == "__main__":
    main()
