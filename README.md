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

### Configuration

Configuration is loaded from `config/config.json`.
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

The bluetooth firmware is not distributed with Ounce-bt for licensing reasons.\
`rtl8761bu_fw.bin` can be found easily from the linux kernel git.\
Place it in the same folder as the executable.

If firmware is missing, the frontend will notify you.

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
