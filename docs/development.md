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
