## Ounce-bt

Nintendo Switch Pro Controller emulation using the [Bumble](https://github.com/nickoala/bumble) Bluetooth framework, with a Starlette-served web UI and WebSocket for live macro control.

### Development Setup

#### Frontend

```bash

cd frontend

# Install deps
pnpm install

# Run frontend
pnpm run dev
```

#### Backend

```bash
# Install Python deps
uv sync

# Run Backend
uv run main.py
```

### Windows builds and installer

Install Node.js 24, pnpm 11.16.0, uv, Visual Studio 2022 Build Tools with
the Desktop development with C++ workload, and Inno Setup 6. Python 3.14
is installed by uv if needed.

Run from the repository root:

```powershell
./scripts/build-windows.ps1
ISCC /DAppVersion=0.1.1 installer/ounce-bt.iss
```

If ISCC is not on PATH, run it using its full installation path.
The build script works from any current directory. Use `-SkipFrontend` to
reuse an existing `frontend/dist` build.

The standalone application is written to `build/windows/main.dist/` and the
installer to `dist/Ounce-bt-0.1.1-windows-x64-setup.exe`. Keep the entire
standalone directory together. It contains the frontend and three built-in
controller presets, but no application config, Bluetooth device config,
firmware, pairing data, or user macros.

The installer installs for the current user under
`%LOCALAPPDATA%\Programs\Ounce-bt`. It generates `config/config.json` and
`config/pro_controller.json` beside the installed executable. Presets and
macros default to `Documents\Ounce-bt\presets` and `Documents\Ounce-bt\macros`;
both folders can be changed during setup. Other settings use the defaults
in `lib/config.py`, including generating a fresh Bluetooth address on first
use. Existing config is preserved on upgrades, and the folder selection page
is skipped when that installation already has config.

Setup asks for user-supplied `rtl8761bu_fw.bin` and `rtl8761bu_config.bin`
files. Both are required to start the app and neither is included in build
artifacts. Existing files are kept on upgrade. The app patches the Bluetooth
address entry in the config binary to match its saved `bt_address`.
User config, Bluetooth files, presets, and macros are retained on uninstall.
The target PC needs the Microsoft Edge WebView2 runtime and a USB Bluetooth
adapter configured for Bumble. The installer does not install USB drivers.

`.github/workflows/frontend.yml` runs lint, tests, and the TypeScript/Vite
build on pull requests and pushes to `main`, using Windows runners.
`.github/workflows/build-windows.yml` builds the app and installer on every
tag push and through **Actions > Build Windows app > Run workflow**.
Download the installer or standalone app from that run's artifacts.
The installer version comes from `pyproject.toml`; update it before tagging.
The workflow does not publish a GitHub release.

### Configuration

Configuration is loaded from `config/config.json`.
For a fresh test identity, run `uv run python scripts/regenerate_config.py`.
The script changes only `bt_address` in the repository config. Use
`--config PATH` for another installation. Restart the app so it writes the
new address into `rtl8761bu_config.bin`, then pair the Switch again.
If that file is absent, the app checks:

- Windows: `%APPDATA%/ounce-bt/config.json`
- Linux: `$XDG_CONFIG_HOME/ounce-bt/config.json`, defaulting to `~/.config/ounce-bt/config.json`

#### Arguments

Settings can also be overridden for a single run with command-line arguments. Run `uv run main.py --help` for the full help text.

| Argument                                             | Description                                                |
| ---------------------------------------------------- | ---------------------------------------------------------- |
| `[device_config]`                                    | Optional Bumble device configuration JSON path.            |
| `[transport_spec]`                                   | Optional Bluetooth transport, defaults to `usb:0`.         |
| `[bt_address]`                                       | Optional controller Bluetooth address.                     |
| `--input controller\|controller:<idx>\|macro:<path>` | Enable an input source; repeat to enable multiple sources. |
| `--web-host HOST`                                    | Web server bind host. Defaults to `127.0.0.1`.             |
| `--web-port PORT`                                    | Web server bind port. Defaults to `9127`.                  |
| `--nolog`                                            | Disable logging for this run.                              |
| `--preset NAME\|PATH`                                | Controller mapping preset                                  |

Command-line values override configuration for the current run and are not saved.

### BT Firmware

The Realtek firmware and config binary are not distributed with Ounce-bt.
Place `rtl8761bu_fw.bin` and `rtl8761bu_config.bin` in the same folder as the
executable. On startup, Ounce-bt writes its saved or newly generated address
into the config binary. It adds the address entry if the binary contains only
the empty `55 AB 23 87 00 00` header.

If either file is missing, the frontend will notify you.

### WebSocket protocol

Connect to `ws://<host>:<port>/ws`. The server sends a `status` frame on connect and on every mode/macro transition. Text frames are JSON.

**Client → server**

```jsonc
// Full controller-state snapshot (lowest-latency manual path)
{"type": "state", "buttons": ["A","B"], "left": [0.0, 1.0], "right": [0.0, 0.0]}

// Single action (one-shot taps; for chorded input use "state")
{"type": "event", "action": {"do": "press", "button": "A"}}
{"type": "event", "action": {"do": "release", "button": "A"}}
{"type": "event", "action": {"do": "stick", "side": "left", "x": 0.0, "y": 1.0}}

// Macro control
{"type": "macro", "op": "start", "macro": {"name": "...", "repeat": 1, "actions": [...]}}
{"type": "macro", "op": "start", "name": "press-a-three-times"}   // load from macros/<name>.json
{"type": "macro", "op": "cancel"}      // immediate stop, drains queue, pushes NEUTRAL
{"type": "macro", "op": "pause"}
{"type": "macro", "op": "resume"}
```

Valid button names: `A B X Y L R ZL ZR UP DOWN LEFT RIGHT PLUS MINUS HOME CAPTURE STICK_L STICK_R`.

`event` semantics: each frame replaces the current controller state (latest-wins consumer). For chorded/persistent input, prefer `state` snapshots.

**Server → client**

```jsonc
{"type": "status", "mode": "manual"|"macro", "macro": {"name": "...", "state": "running"|"paused"}|null}
{"type": "error", "message": "...", "detail": "..."?}
```

### Macros

JSON files under `macros/`. Schema:

```jsonc
{
  "name": "example",
  "repeat": 0, // 0 = loop forever, N = play N times
  "actions": [
    { "do": "press", "button": "A" },
    { "do": "wait", "ms": 50 },
    { "do": "release", "button": "A" },
    { "do": "wait", "ms": 50 },
    { "do": "stick", "side": "left", "x": 0.0, "y": 1.0 },
    { "do": "wait", "ms": 200 },
    { "do": "stick", "side": "left", "x": 0.0, "y": 0.0 },
    {
      "do": "loop",
      "count": 3,
      "actions": [
        { "do": "press", "button": "B" },
        { "do": "wait", "ms": 30 },
        { "do": "release", "button": "B" },
        { "do": "wait", "ms": 30 },
      ],
    },
  ],
}
```

### Frontend development

```bash
cd frontend
pnpm dev    # http://localhost:5173 -- proxies /ws and /api to :9127
pnpm build  # emits frontend/dist/ which Starlette serves in prod
```

The Vite dev server proxies `/ws` and `/api` to the Python backend, so the frontend can use relative URLs (`/ws`, `/api/...`) in both dev and prod.

### Credits

This project includes code adapted from Brikwerk's [NXBT](https://github.com/Brikwerk/nxbt) project.

This project utilised typenoob's bumble implementation [(NXBT)](https://github.com/typenoob/nxbt) for understanding the pairing protocol.
