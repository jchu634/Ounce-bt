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

#### Frontend build

Regenerate the frontend build for the backend+webview app using

```bash
pnpm run build
```

#### Backend

```bash
# Install Python deps
uv sync

# Build SDL3 with libusb support (required for wired Switch 2 Pro; run automatically by release builds)
uv run python scripts/build-sdl3.py

# Run Backend
uv run main.py
```

#### Linux

On Linux, Bumble needs `CAP_NET_RAW` and `CAP_NET_ADMIN` to claim the USB Bluetooth adapter. Running `uv run main.py` directly will fail to initialize Bluetooth; launch it through `scripts/run-with-hci-caps.sh` instead:

```bash
./scripts/run-with-hci-caps.sh uv run main.py
```

To target a specific adapter (see `lsusb`), pass its transport spec:

```bash
./scripts/run-with-hci-caps.sh uv run main.py usb:0
# or
./scripts/run-with-hci-caps.sh uv run main.py usb:<vendor-id>:<product-id>
```

If USB device access is denied, run the interactive udev setup script to discover your adapters and install `/etc/udev/rules.d/70-ounce-bt.rules`:

```bash
./scripts/setup-linux-udev.py
```

See [Linux documentation](linux.md#usb-device-permissions) for manual udev setup details.

#### Using the Vite dev server with the backend

By default, `config/config.json` has `"ws_auth_required": true` and `"webview_enabled": true`, which restricts WebSocket connections to the embedded desktop webview. To test against the Vite dev server (`http://localhost:5173`) in a regular browser:

1. In `config/config.json`, set `"ws_auth_required": false` (and optionally `"webview_enabled": false` to run the backend without opening the desktop window).
2. Start the backend:
   - Linux: `./scripts/run-with-hci-caps.sh uv run main.py`
   - Windows: `uv run main.py`
3. In another terminal, start the frontend dev server:
   ```bash
   cd frontend
   pnpm run dev
   ```
4. Open the Vite URL (default `http://localhost:5173`), which proxies `/api` and `/ws` to `http://127.0.0.1:9127`.
