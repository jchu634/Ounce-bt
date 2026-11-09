#!/usr/bin/env bash
# Build on Ubuntu 22.04 for the release's glibc baseline; newer hosts also work.
set -euo pipefail
if [[ $(uname -s) != Linux ]]; then
    echo 'This build requires Linux.' >&2
    exit 1
fi
repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_root"
build_root="$repo_root/build/linux"
python_version=${PYTHON_VERSION:-3.12}
case $(uname -m) in
    x86_64) app_arch=x86_64 ;;
    aarch64) app_arch=aarch64 ;;
    *) echo 'Supported architectures: x86_64, aarch64' >&2; exit 1 ;;
esac
if [[ ${1:-} != --skip-frontend ]]; then
    pnpm --dir frontend install --frozen-lockfile
    pnpm --dir frontend build
fi
test -f frontend/dist/index.html
mkdir -p "$build_root" dist
export UV_PROJECT_ENVIRONMENT="$build_root/.venv"
uv sync --locked --no-dev --group build --python "$python_version"
# Qt hooks cannot discover plugins if their shared-library dependencies are
# missing on the build host. Fail before producing an incomplete bundle.
uv run --no-sync --python "$python_version" python -c 'from PySide6 import QtCore, QtWebEngineWidgets; print("Qt plugin directory:", QtCore.QLibraryInfo.path(QtCore.QLibraryInfo.PluginsPath))'
uv run --no-sync --python "$python_version" python -m PyInstaller --noconfirm --clean \
    --distpath "$build_root/dist" --workpath "$build_root/pyinstaller" \
    scripts/ounce-bt-linux.spec

app_dir="$build_root/Ounce-bt.AppDir"
rm -rf -- "$app_dir"
mkdir -p "$app_dir/usr/lib" "$app_dir/usr/share/icons/hicolor/512x512/apps" "$app_dir/usr/share/applications"
cp -a "$build_root/dist/Ounce-bt" "$app_dir/usr/lib/ounce-bt"
install -m 755 scripts/appimage/AppRun "$app_dir/AppRun"
install -m 644 scripts/appimage/ounce-bt.desktop "$app_dir/ounce-bt.desktop"
cp "$app_dir/ounce-bt.desktop" "$app_dir/usr/share/applications/ounce-bt.desktop"
install -m 644 frontend/public/icon-512.png "$app_dir/ounce-bt.png"
cp "$app_dir/ounce-bt.png" "$app_dir/.DirIcon"
cp "$app_dir/ounce-bt.png" "$app_dir/usr/share/icons/hicolor/512x512/apps/ounce-bt.png"

# Extract the build tool so FUSE is not needed in CI. Override APPIMAGETOOL
# with a locally verified executable to build without downloading this tool.
appimage_tool=${APPIMAGETOOL:-}
if [[ -z $appimage_tool ]]; then
    tool_image="$build_root/appimagetool-$app_arch.AppImage"
    curl --fail --location --retry 3 \
        "https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-$app_arch.AppImage" \
        --output "$tool_image"
    chmod +x "$tool_image"
    (cd "$build_root" && "$tool_image" --appimage-extract > /dev/null)
    appimage_tool="$build_root/squashfs-root/AppRun"
fi
version=$(uv run --no-sync --python "$python_version" python -c 'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])')
output="$repo_root/dist/Ounce-bt-$app_arch.AppImage"
ARCH="$app_arch" "$appimage_tool" --no-appstream "$app_dir" "$output"
"$output" --appimage-extract-and-run --help
uv run --no-sync --python "$python_version" python scripts/package-linux.py "$output" "$version"
printf 'Linux AppImage: %s\n' "$output"
