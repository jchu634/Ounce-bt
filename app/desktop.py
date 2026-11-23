"""Own the native window and the backend event loop for one application run."""

import asyncio
import json
import logging
import os
import secrets
import sys
import threading
from pathlib import Path
from urllib.parse import urlsplit

import webview

from lib.config import application_dir
from lib.server.files import validate_name

logger = logging.getLogger("switch_pair")


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

    def save_json(self, name, contents):
        self._check_origin()
        filename = f"{validate_name(name)}.json"
        json.loads(contents)
        paths = self._window.create_file_dialog(
            webview.FileDialog.SAVE,
            save_filename=filename,
            file_types=("JSON files (*.json)",),
        )
        if not paths:
            return False
        path = paths if isinstance(paths, str) else paths[0]
        self._check_origin()
        Path(path).write_text(contents, encoding="utf-8")
        return True


class WindowsDesktopBridge(DesktopBridge):
    def __init__(self, token, origin):
        super().__init__(token, origin)
        from app.audio_monitor import AudioMonitor

        self._audio = AudioMonitor()

    def start_capture_audio(self, label):
        self._check_origin()
        try:
            return self._audio.start(label)
        except (OSError, RuntimeError) as error:
            logger.warning("Native capture audio unavailable: %s", error)
            return None

    def set_capture_volume(self, session, volume):
        self._check_origin()
        self._audio.set_volume(session, volume)

    def stop_capture_audio(self, session):
        self._check_origin()
        self._audio.stop(session)


def _configure_linux_media_permissions(window, expected_origin):
    """Grant camera and microphone access for the local app origin in Qt WebEngine.

    pywebview's Qt backend passes raw ints to ``QWebEnginePage.setFeaturePermission``
    (which raises ``TypeError`` in PySide6) and relies on ``--use-fake-ui-for-media-stream``
    without updating Qt's permission store, leaving ``navigator.permissions.query``
    stuck in ``"prompt"``.
    """
    native = getattr(window, "native", None)
    webview_widget = getattr(native, "webview", None)
    if webview_widget is None:
        return
    page = webview_widget.page()
    if page is None:
        return

    from PySide6 import QtCore, QtWebEngineCore

    QWebEnginePage = QtWebEngineCore.QWebEnginePage

    def is_app_origin(url):
        parsed = urlsplit(url.toString())
        return (parsed.scheme, parsed.netloc) == expected_origin

    broken_handler = getattr(page, "onFeaturePermissionRequested", None)
    if broken_handler is not None:
        try:
            page.featurePermissionRequested.disconnect(broken_handler)
        except (AttributeError, RuntimeError, TypeError):
            pass

    permission_cls = getattr(QtWebEngineCore, "QWebEnginePermission", None)
    profile = getattr(native, "profile", None) or page.profile()
    if permission_cls is not None:
        media_permission_types = (
            permission_cls.PermissionType.MediaVideoCapture,
            permission_cls.PermissionType.MediaAudioCapture,
            permission_cls.PermissionType.MediaAudioVideoCapture,
        )
        if profile is not None and hasattr(profile, "queryPermission"):
            origin_url = QtCore.QUrl(f"{expected_origin[0]}://{expected_origin[1]}")
            for permission_type in (
                permission_cls.PermissionType.MediaVideoCapture,
                permission_cls.PermissionType.MediaAudioCapture,
            ):
                permission = profile.queryPermission(origin_url, permission_type)
                if permission.isValid():
                    permission.grant()

        if hasattr(page, "permissionRequested"):

            def on_permission_requested(permission):
                if (
                    is_app_origin(permission.origin())
                    and permission.permissionType() in media_permission_types
                ):
                    permission.grant()
                else:
                    permission.deny()

            page._ounce_permission_handler = on_permission_requested
            page.permissionRequested.connect(on_permission_requested)
            return

    media_features = (
        QWebEnginePage.Feature.MediaAudioCapture,
        QWebEnginePage.Feature.MediaVideoCapture,
        QWebEnginePage.Feature.MediaAudioVideoCapture,
    )

    def on_feature_permission_requested(url, feature):
        policy = (
            QWebEnginePage.PermissionPolicy.PermissionGrantedByUser
            if is_app_origin(url) and feature in media_features
            else QWebEnginePage.PermissionPolicy.PermissionDeniedByUser
        )
        page.setFeaturePermission(url, feature, policy)

    page._ounce_feature_permission_handler = on_feature_permission_requested
    page.featurePermissionRequested.connect(on_feature_permission_requested)


def run_application(config, args, backend):
    restart_requested = threading.Event()

    async def restartable_backend(*backend_args, **kwargs):
        return await backend(
            *backend_args, **kwargs, restart_callback=restart_requested.set
        )

    if not config.web_enabled:
        asyncio.run(restartable_backend(config, args))
        return restart_requested.is_set()
    if not config.webview_enabled:
        if config.ws_auth_required:
            raise ValueError("Browser mode requires ws_auth_required=false")
        asyncio.run(restartable_backend(config, args, shutdown_event=asyncio.Event()))
        return restart_requested.is_set()
    if config.web_host not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("The desktop web server must bind to localhost")

    token = secrets.token_urlsafe(32) if config.ws_auth_required else None
    # Cache busting nonce to prevent fetching a stale build
    launch_nonce = secrets.token_hex(16)
    host = f"[{config.web_host}]" if ":" in config.web_host else config.web_host
    expected_origin = ("http", f"{host}:{config.web_port}")
    url = f"http://{host}:{config.web_port}/?launch={launch_nonce}"
    bridge_class = WindowsDesktopBridge if sys.platform == "win32" else DesktopBridge
    bridge = bridge_class(token, expected_origin)
    ready = threading.Event()
    finished = threading.Event()
    closed = threading.Event()
    failures = []
    loop = asyncio.new_event_loop()
    stop = asyncio.Event()

    async def run_backend():
        await restartable_backend(
            config, args, shutdown_event=stop, ws_token=token, ready=ready
        )

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
            "Ounce-bt", url, js_api=bridge, width=1550, height=800, min_size=(400, 500)
        )
        bridge._window = window
        window.events.closed += request_stop

        def monitor_backend():
            finished.wait()
            if not closed.is_set():
                window.destroy()

        options = {}
        if sys.platform == "linux":
            # qtpy otherwise chooses whichever Qt binding it finds first.
            os.environ["QT_API"] = "pyside6"
            # Wayland identifies windows by the matching desktop-file name.
            # Set it before pywebview constructs QApplication / its first window.
            from PySide6.QtGui import QGuiApplication

            QGuiApplication.setApplicationName("Ounce-bt")
            QGuiApplication.setDesktopFileName("ounce-bt")
            if hasattr(window.events, "before_show"):
                window.events.before_show += (
                    lambda: _configure_linux_media_permissions(window, expected_origin)
                )
            options["gui"] = "qt"
            options["icon"] = str(application_dir() / "frontend/public/icon-512.png")
        webview.start(monitor_backend, private_mode=False, **options)
    finally:
        try:
            if isinstance(bridge, WindowsDesktopBridge):
                bridge._audio.close()
        finally:
            request_stop()
            thread.join()
    if failures:
        raise failures[0]

    return restart_requested.is_set()
