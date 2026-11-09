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

# Run Backend
uv run main.py
```
