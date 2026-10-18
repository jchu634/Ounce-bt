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

The Vite dev server proxies `/ws` and `/api` to the Python backend, so the frontend can use relative URLs (`/ws`, `/api/...`) in both dev and prod.

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

Settings can overridden for a single run with these command-line arguments.\
Run `uv run main.py --help` for the full help text.

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

The Realtek firmware binaries, although required, are not distributed with Ounce-bt.
Place `rtl8761bu_fw.bin` and `rtl8761bu_config.bin` in the same folder as the
executable.

If either file is missing, the frontend will notify you.

### Credits

This project includes code adapted from Brikwerk's [NXBT](https://github.com/Brikwerk/nxbt) project.

This project utilised typenoob's bumble implementation [(NXBT)](https://github.com/typenoob/nxbt) for understanding the pairing protocol.
