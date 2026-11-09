# Linux Support

## Supported launch settings

Linux uses Bumble's USB transport with the adapter's existing firmware and
public Bluetooth address.

Download the Linux release ZIP for your architecture.\
It contains the AppImage,
`run-with-hci-caps.sh`, an AppImage checksum and launch instructions.\
Extract it and run the launcher as your desktop user.

e.g.
```bash
unzip Ounce-bt-0.1.3-linux-x86_64.zip
cd Ounce-bt-0.1.3-linux-x86_64
chmod +x Ounce-bt-0.1.3-x86_64.AppImage run-with-hci-caps.sh
./run-with-hci-caps.sh "$PWD/Ounce-bt-0.1.3-x86_64.AppImage" usb:0
```

`usb:0` selects the first adapter in Bumble's USB enumeration.\
If it selects the
wrong adapter:

1. Run `lsusb` and find your Bluetooth adapter.
2. Replace `usb:0` with `usb:<vendor-id>:<product-id>`, using the four-digit
   hexadecimal IDs shown by `lsusb`. For example, an adapter listed as
   `ID 2357:0604` can be selected with `usb:2357:0604`.

If your system lacks FUSE, use the same launcher with
`APPIMAGE_EXTRACT_AND_RUN=1`:

```bash
APPIMAGE_EXTRACT_AND_RUN=1 ./run-with-hci-caps.sh "$PWD/Ounce-bt-0.1.3-x86_64.AppImage" usb:0
```

Startup errors appear in the application dialog and log.

## Escalated Priviledges

Ounce-bt uses the Bumble library to handle Bluetooth.\
Bumble uses its own host stack, hence it needs direct control 
of the adapter rather than a normal connection managed by the desktop's Bluetooth service. 

Linux controls access to this hardware and to privileged
Bluetooth operations.

The supplied launcher script asks for escalated priviledges as it needs them to give the application additional priviledges via `sudo setpriv`

For bumble, the application is granted
- `CAP_NET_RAW` allows raw and packet socket operations, including low-level
  Bluetooth packet operations through Linux's raw HCI interface.
- `CAP_NET_ADMIN` allows network administration, including taking exclusive control of a Bluetooth adapter through Linux's HCI user channel.

Note, the launcher uses sudo to add permissions to the application, then runs it as your desktop user (not root).
The launcher shell is replaced during startup; the application retains these additional capabilities while running.

## USB device permissions

The USB transport requires read/write permission on the selected `/dev/bus/usb` device.\
If access is denied, create a udev rule for your adapter in
`/etc/udev/rules.d/70-ounce-bt.rules`:

```udev
SUBSYSTEM=="usb", ATTR{idVendor}=="VVVV", ATTR{idProduct}=="PPPP", TAG+="uaccess"
```

Replace `VVVV` and `PPPP` with your adapter's four-digit vendor and product IDs
from `lsusb`. For example, `ID 2357:0604` means `VVVV` becomes `2357` and `PPPP`
becomes `0604`. Save the file with administrator privileges, then reload the
rules:

```bash
sudo udevadm control --reload-rules
```

Unplug and reconnect the adapter to apply the rule. The `uaccess` tag grants USB
device access to the user in the active local desktop session. This configures
USB device access separately from the launcher's process capabilities. Continue
using the same `run-with-hci-caps.sh` launch command after applying the rule.

Bumble claims the adapter's USB interface while Ounce-bt is running, so BlueZ
cannot use that adapter at the same time. Use a dedicated adapter if you also
use Bluetooth input devices or audio. Linux kernel drivers handle the adapter
outside Ounce-bt; no Windows-style WinUSB driver replacement is needed.

## Configuration and data

The AppImage stores writable files in these locations:

| Files | Default location |
| --- | --- |
| Settings | `~/.config/ounce-bt/config.json` |
| Macros and custom presets | `~/.local/share/ounce-bt/macros` and `presets` |
| Packet log | `~/.local/state/ounce-bt/switch_packets.log` |
| Pairing keys | Bumble's per-user key store, or the configured `pairing_dir` |

`XDG_CONFIG_HOME`, `XDG_DATA_HOME` and `XDG_STATE_HOME` override their respective
base directories. Settings and pairing keys remain outside the AppImage when
you replace it with a newer build.

## Build

Install `uv`, Node.js and `pnpm`, a C compiler, `curl`, `file`, and the Qt runtime
system libraries. The [Linux build workflow](../.github/workflows/build-linux.yml)
lists the system packages used by CI. Then run:

```bash
./scripts/build-linux.sh
```

The script builds the frontend, creates an isolated Python 3.12 build
environment, and packages the app with PyInstaller and PySide6's WebEngine
hooks. It generates `dist/Ounce-bt-<version>-linux-<arch>.zip`, containing the
AppImage, `run-with-hci-caps.sh`, the AppImage's SHA-256 checksum and launch
instructions in one folder. The build uses appimagetool 1.9.1 and retains the
loose AppImage in `dist/` for local testing.

`--skip-frontend` reuses an existing frontend build. `PYTHON_VERSION` changes
the build Python, and `APPIMAGETOOL` selects a locally verified appimagetool
executable instead of downloading it.

Build on Ubuntu 22.04 for the release's glibc baseline. A build made on a newer
distribution can depend on that host's newer glibc. The GitHub Linux workflow
uses Ubuntu 22.04, runs backend checks and tests the packaged Qt desktop under
Xvfb. Nightly releases publish the Linux ZIP alongside Windows assets. Hardware
pairing still requires a physical adapter and Switch.

Run the packaging smoke test without claiming a physical adapter:

```bash
uv run python scripts/smoke-linux.py build/linux/Ounce-bt.AppDir/AppRun
```

The test starts the desktop against a nonexistent adapter, checks the error
response, loads the packaged frontend and a built-in preset, and clicks the
error dialog's **Close application** button through Qt WebEngine's local
debugging interface. It then verifies that the process exits and the backend
port stops listening.
