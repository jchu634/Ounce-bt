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
uv run main.py --input controller
```

### Command-line interface

```
python main.py [device_config] [transport_spec] [bt_address] [options]
```

All positionals are optional; any value may instead come from the config store.

| Flag              | Default               | Purpose                                                                            |
| ----------------- | --------------------- | ---------------------------------------------------------------------------------- |
| `device_config`   | `pro_controller.json` | Bumble device config JSON                                                          |
| `transport_spec`  | _(required)_          | e.g. `usb:0`                                                                       |
| `bt_address`      | `98:b6:e9:12:34:57`   | Controller Bluetooth address                                                       |
| `--input SPEC`    | _(from config)_       | Add an input source (`controller`, `controller:<idx>`, `macro:<path>`); repeatable |
| `--web-host HOST` | `127.0.0.1`           | Web server bind host                                                               |
| `--web-port PORT` | `9127`                | Web server bind port                                                               |
| `--no-web`        | off                   | Don't launch the web server / WebSocket                                            |

CLI flags override the config store for that single run; they do **not** write back. To persist changes, use `PATCH /api/config`.

### Configuration store

A JSON file at `%APPDATA%\ounce-bt\config.json` (or `$XDG_CONFIG_HOME/ounce-bt/config.json` on POSIX) holds runtime settings. Loaded at startup, mutated at runtime via the API, written atomically on change.

| Key                     | Default               | Notes                        |
| ----------------------- | --------------------- | ---------------------------- |
| `web_host`              | `127.0.0.1`           | Web server bind host         |
| `web_port`              | `9127`                | Web server bind port         |
| `bt_address`            | `98:b6:e9:12:34:57`   | Controller Bluetooth address |
| `transport_spec`        | _(none)_              | e.g. `usb:0`                 |
| `device_config`         | `pro_controller.json` | Bumble device config path    |
| `input_specs`           | `[]`                  | List of `--input` specs      |
| `last_camera_device_id` | `""`                  | Set by the frontend          |
| `tick_rate_hz`          | `132`                 | Main controller loop rate    |
| `macro_rate_hz`         | `120`                 | Macro player enqueue rate    |

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
