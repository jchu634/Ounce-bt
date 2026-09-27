"""Own the native window and the backend event loop for one application run."""

import asyncio
import secrets
import threading
from urllib.parse import urlsplit
import webview

class DesktopBridge:
    def __init__(self, token, origin):
        self._token = token
        self._origin = origin
        self._window = None

    def _check_origin(self):
        current = urlsplit(self._window.get_current_url() or "")
        if (current.scheme, current.netloc) != self._origin:
            raise PermissionError(
                "The bridge is only available to the application page"
            )

    def get_auth_token(self):
        self._check_origin()
        return self._token

    def close_application(self):
        self._check_origin()
        self._window.destroy()


def run_application(config, args, backend):
    if not config.web_enabled:
        asyncio.run(backend(config, args))
        return
    if not config.webview_enabled:
        if config.ws_auth_required:
            raise ValueError("Browser mode requires ws_auth_required=false")
        asyncio.run(backend(config, args))
        return
    if config.web_host not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("The desktop web server must bind to localhost")


    token = secrets.token_urlsafe(32) if config.ws_auth_required else None
    host = f"[{config.web_host}]" if ":" in config.web_host else config.web_host
    url = f"http://{host}:{config.web_port}"
    bridge = DesktopBridge(token, ("http", f"{host}:{config.web_port}"))
    ready = threading.Event()
    finished = threading.Event()
    closed = threading.Event()
    failures = []
    loop = asyncio.new_event_loop()
    stop = asyncio.Event()

    async def run_backend():
        task = asyncio.create_task(
            backend(
                config,
                args,
                ws_token=token,
                ready=ready,
                shutdown_event=stop,
            )
        )
        stopped = asyncio.create_task(stop.wait())
        try:
            await asyncio.wait({task, stopped}, return_when=asyncio.FIRST_COMPLETED)
            if task.done():
                await task
        finally:
            task.cancel()
            stopped.cancel()
            await asyncio.gather(task, stopped, return_exceptions=True)

    def worker():
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(run_backend())
        except BaseException as error:  # noqa: BLE001 - re-raised on the GUI thread
            failures.append(error)
        finally:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.run_until_complete(loop.shutdown_default_executor())
            loop.close()
            finished.set()
            ready.set()

    def request_stop():
        closed.set()
        try:
            loop.call_soon_threadsafe(stop.set)
        except RuntimeError:
            pass  # The backend has already closed its event loop.

    thread = threading.Thread(target=worker, name="backend")
    thread.start()
    try:
        if not ready.wait(30):
            raise TimeoutError("The local web server did not start within 30 seconds")
        if failures:
            raise failures[0]
        if finished.is_set():
            return
        window = webview.create_window(
            "Ounce-bt", url, js_api=bridge, width=1280, height=800
        )
        bridge._window = window
        window.events.closed += request_stop

        def monitor_backend():
            finished.wait()
            if not closed.is_set():
                window.destroy()

        webview.start(monitor_backend, private_mode=False)
    finally:
        request_stop()
        thread.join()
    if failures:
        raise failures[0]
