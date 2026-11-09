"""Check the packaged desktop; a physical adapter is used only with --transport."""

import argparse
import json
import os
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from websockets.sync.client import connect


def click_close_button(base: str, debug_port: int) -> None:
    """Click the rendered dialog after the native bridge has initialized."""
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{debug_port}/json", timeout=1
            ) as response:
                pages = json.load(response)
            page = next(
                (page for page in pages if page.get("url", "").startswith(base + "/")),
                None,
            )
            if page:
                with connect(
                    page["webSocketDebuggerUrl"], proxy=None, open_timeout=2
                ) as debugger:
                    debugger.send(
                        json.dumps(
                            {
                                "id": 1,
                                "method": "Runtime.evaluate",
                                "params": {
                                    "expression": """(() => {
                                const button = [...document.querySelectorAll('button')]
                                    .find(button => button.textContent.trim() === 'Close application');
                                if (!window.pywebview?.api || !button || button.disabled) return false;
                                setTimeout(() => button.click(), 100);
                                return true;
                            })()""",
                                    "returnByValue": True,
                                },
                            }
                        )
                    )
                    reply = json.loads(debugger.recv(timeout=3))
                    if reply.get("result", {}).get("result", {}).get("value") is True:
                        return
        except (OSError, urllib.error.URLError, TimeoutError):
            pass
        time.sleep(0.1)
    raise TimeoutError("The native startup dialog close button was not available")


def smoke(executable: Path, transport: str | None = None) -> None:
    with tempfile.TemporaryDirectory(prefix="ounce-smoke-") as temporary:
        root = Path(temporary)
        config = root / "config/ounce-bt/config.json"
        config.parent.mkdir(parents=True)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            debug_port = sock.getsockname()[1]
        # A nonexistent adapter tests the error dialog without disturbing radios.
        config.write_text(
            json.dumps(
                {
                    "transport_spec": transport or "usb:ffff:ffff",
                    "web_port": port,
                    "input_specs": [],
                }
            )
        )
        environment = dict(
            os.environ,
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_DATA_HOME=str(root / "data"),
            XDG_STATE_HOME=str(root / "state"),
        )
        if not transport:
            environment["QTWEBENGINE_REMOTE_DEBUGGING"] = f"127.0.0.1:{debug_port}"
        with (root / "desktop.log").open("w+") as log:
            process = subprocess.Popen(
                [str(executable)], cwd=root, env=environment, stdout=log, stderr=log
            )
            base = f"http://127.0.0.1:{port}"
            try:
                deadline = time.monotonic() + 30
                while True:
                    if process.poll() is not None:
                        raise RuntimeError(
                            f"Desktop exited early: {process.returncode}"
                        )
                    try:
                        with urllib.request.urlopen(
                            base + "/api/startup", timeout=1
                        ) as response:
                            status = json.load(response)
                        if transport and status["kind"] == "ready":
                            break
                        if status["kind"] == "bluetooth_error":
                            if transport:
                                raise RuntimeError(status["message"])
                            assert (
                                "not supported on this platform"
                                not in status["message"]
                            ), status
                            break
                    except (urllib.error.URLError, TimeoutError):
                        pass
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Packaged backend did not start")
                    time.sleep(0.1)
                with urllib.request.urlopen(base, timeout=2) as response:
                    assert b"<html" in response.read().lower(), (
                        "Frontend was not bundled"
                    )
                with urllib.request.urlopen(
                    base + "/api/presets/xbox", timeout=2
                ) as response:
                    assert response.status == 200, "Built-in presets were not bundled"
                if transport:
                    for pairing in (True, False):
                        request = urllib.request.Request(
                            base + "/api/bluetooth",
                            method="PUT",
                            data=json.dumps({"pairing": pairing}).encode(),
                            headers={"Content-Type": "application/json"},
                        )
                        with urllib.request.urlopen(request, timeout=5) as response:
                            bluetooth = json.load(response)
                            assert bluetooth["available"]
                            assert bluetooth["pairing"] is pairing
                    print(
                        f"Physical {transport} initialization and pairing controls passed."
                    )
                # Allow Qt WebEngine to initialize; missing plugins/libs exit here.
                time.sleep(3)
                assert process.poll() is None, "Qt desktop exited during initialization"
                if transport:
                    request = urllib.request.Request(
                        base + "/api/application/close",
                        data=b"{}",
                        headers={"Content-Type": "application/json"},
                    )
                    with urllib.request.urlopen(request, timeout=2) as response:
                        assert response.status == 200
                else:
                    click_close_button(base, debug_port)
                assert process.wait(timeout=15) == 0, "Desktop shutdown failed"
                with socket.socket() as sock:
                    assert sock.connect_ex(("127.0.0.1", port)) != 0, (
                        "Backend port is still listening"
                    )
                print(
                    "Packaged Qt desktop, frontend, presets, close button and process shutdown passed."
                )
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                log.seek(0)
                print(log.read())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    parser.add_argument(
        "--transport", help="explicit physical adapter transport to test"
    )
    options = parser.parse_args()
    smoke(options.executable.resolve(), options.transport)
