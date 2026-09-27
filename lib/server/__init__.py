"""
Starlette application hosting the built frontend, the macro WebSocket
and the REST API.

Routes (ordered WS/REST before static so the catch-all SPA mount doesn't
shadow them)::

    /ws                                WebSocket: runtime channel
    GET  /api/config                   current config as JSON
    PATCH /api/config                  merge-update config (persists)
    GET  /api/control-mode             {"mode": ..., "macro": {...}|null}
    PUT  /api/control-mode             {"mode": "manual"|"macro"}
    GET  /api/macros                   {"names": [...]}
    GET  /api/macros/{name}            {"name": ..., "contents": "<raw json>"}
    PUT  /api/macros/{name}            {"contents": "<raw json>"} (validated)
    DELETE /api/macros/{name}          409 while that macro is running
    GET  /api/controllers              device list + active + preset
    PUT  /api/controllers/active       {"guid"|"name"|"index": ...}
    GET  /api/presets                  {"presets": [{name, builtin, ...}]}
    GET  /api/presets/{name}           {"name": ..., "contents": "<raw json>"}
    PUT  /api/presets/{name}           custom presets only (validated)
    DELETE /api/presets/{name}         custom presets only; 409 when active
    POST /api/presets/{name}/activate  select + persist + apply
    /                                  StaticFiles(frontend/dist, html=True)
"""

from __future__ import annotations

import asyncio
import logging
import secrets
from pathlib import Path

from starlette.applications import Starlette
from starlette.background import BackgroundTask
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocket, WebSocketDisconnect

from lib.bluetooth import BluetoothService
from lib.config import ConfigStore
from lib.input.macro_source import MacroValidationError, validate_macro
from lib.input.manager import InputManager, MacroActiveError, state_from_event
from lib.input.presets import (
    PresetValidationError,
    delete_preset,
    list_preset_infos,
    preset_name_is_builtin,
    read_preset_text,
    save_preset_text,
    validate_preset,
)
from lib.server.files import (
    DocError,
    JsonDocStore,
    UnsafeNameError,
    parse_json_text,
)
from lib.server.protocol import (
    MacroCancel,
    MacroPause,
    MacroResume,
    MacroStartByName,
    MacroStartInline,
    ProtocolError,
    error_frame,
    frame_text,
    parse_message,
    status_frame,
)

logger = logging.getLogger("switch_pair")


def _error(message: str, detail: str | None = None, status: int = 400) -> JSONResponse:
    body: dict = {"error": message}
    if detail is not None:
        body["detail"] = detail
    return JSONResponse(body, status_code=status)


async def macro_ws_endpoint(websocket: WebSocket) -> None:
    token = websocket.app.state.ws_token
    if token is not None:
        protocols = websocket.scope.get("subprotocols", [])
        supplied = next((p[11:] for p in protocols if p.startswith("ounce-auth.")), "")
        if "ounce-bt" not in protocols or not secrets.compare_digest(
            supplied.encode("utf-8"), token.encode("utf-8")
        ):
            await websocket.close(code=1008)
            return
    await websocket.accept(subprotocol="ounce-bt" if token is not None else None)
    manager: InputManager = websocket.app.state.manager
    # Guarantee thread-safe broadcasts even when the manager was built
    # without a bound loop (tests / library embedding).
    manager.ensure_loop(asyncio.get_running_loop())
    status_q = manager.subscribe()

    # Exactly one outstanding websocket.receive() at any time (multiple
    # concurrent receive() calls race disconnects and raise).
    incoming: asyncio.Queue[str | None] = asyncio.Queue()

    async def reader() -> None:
        try:
            while True:
                event = await websocket.receive()
                text = event.get("text") or ""
                if text:
                    incoming.put_nowait(text)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            incoming.put_nowait(None)  # disconnect sentinel

    reader_task = asyncio.create_task(reader())

    initial = manager.status()
    try:
        await websocket.send_text(status_frame(initial["mode"], initial["macro"]))
        await websocket.send_text(frame_text(manager.controllers_payload()))
    except WebSocketDisconnect:
        reader_task.cancel()
        await asyncio.gather(reader_task, return_exceptions=True)
        manager.unsubscribe(status_q)
        return

    try:
        # Persistent get-tasks, renewed immediately after consumption so
        # no frame is ever stranded in an abandoned task.
        incoming_task = asyncio.create_task(incoming.get())
        status_task = asyncio.create_task(status_q.get())
        while True:
            done, _pending = await asyncio.wait(
                {incoming_task, status_task},
                return_when=asyncio.FIRST_COMPLETED,
            )

            if incoming_task in done:
                text = incoming_task.result()
                if text is None:
                    break
                incoming_task = asyncio.create_task(incoming.get())
                try:
                    await _dispatch_ws(text, websocket, manager)
                except ProtocolError as e:
                    await websocket.send_text(error_frame(str(e)))
                except WebSocketDisconnect:
                    break
                except Exception as e:
                    logger.exception("error handling WS message")
                    try:
                        await websocket.send_text(
                            error_frame("internal error", detail=str(e))
                        )
                    except WebSocketDisconnect:
                        break

            if status_task in done:
                payload = status_task.result()
                status_task = asyncio.create_task(status_q.get())
                try:
                    await websocket.send_text(frame_text(payload))
                except WebSocketDisconnect:
                    break
    except WebSocketDisconnect:
        pass
    finally:
        # Sync-only teardown: awaiting here gives the test-client/portal
        # cancellation a window to strike mid-cleanup and leave the app
        # task in a half-cancelled state. The cancelled tasks unwind on
        # their own (reader swallows its own disconnect errors).
        for task in (incoming_task, status_task, reader_task):
            task.cancel()
        manager.unsubscribe(status_q)


async def _dispatch_ws(text: str, websocket: WebSocket, manager: InputManager) -> None:
    msg = parse_message(text)

    if hasattr(msg, "action"):  # EventMessage
        accepted = manager.submit_state(state_from_event(msg.action))
        if not accepted:
            await websocket.send_text(
                error_frame("manual input disabled while macro running")
            )
        return

    if hasattr(msg, "buttons"):  # StateMessage
        accepted = manager.submit_state(msg.to_state())
        if not accepted:
            await websocket.send_text(
                error_frame("manual input disabled while macro running")
            )
        return

    if isinstance(msg, MacroStartInline):
        try:
            manager.start_macro(msg.macro)
        except MacroValidationError as e:
            await websocket.send_text(
                error_frame(
                    "invalid macro",
                    detail=str(e),
                )
            )
        return
    if isinstance(msg, MacroStartByName):
        try:
            manager.start_macro_by_name(msg.name)
        except (FileNotFoundError, ValueError) as e:
            await websocket.send_text(error_frame(f"could not load macro: {e}"))
        return
    if isinstance(msg, MacroCancel):
        manager.cancel_macro()
        return
    if isinstance(msg, MacroPause):
        manager.pause_macro()
        return
    if isinstance(msg, MacroResume):
        manager.resume_macro()
        return


async def bluetooth_control(request: Request) -> Response:
    service: BluetoothService = request.app.state.bluetooth
    try:
        if request.method != "GET":
            try:
                body = await request.json()
            except ValueError:
                return _error("invalid JSON body")
            if not isinstance(body, dict):
                return _error("expected a JSON object")
            if request.method == "PUT":
                if not isinstance(body.get("pairing"), bool):
                    return _error("pairing must be a boolean")
                await service.set_pairing(body["pairing"])
            elif request.method == "POST" and body.get("action") == "disconnect":
                await service.disconnect()
            else:
                if not isinstance(body.get("address"), str):
                    return _error("address must be a saved device address")
                if request.method == "DELETE":
                    await service.forget(body["address"])
                else:
                    await service.reconnect(body["address"])
        return JSONResponse(await service.status())
    except ValueError as e:
        return _error(str(e), status=409)
    except Exception as e:
        logger.exception("Bluetooth operation failed")
        return _error(f"Bluetooth operation failed: {e}", status=503)


async def macros_list(request: Request) -> Response:
    store: JsonDocStore = request.app.state.macro_store
    return JSONResponse({"names": store.list_names()})


async def macro_get(request: Request) -> Response:
    store: JsonDocStore = request.app.state.macro_store
    name = request.path_params["name"]
    try:
        contents = store.read_text(name)
    except UnsafeNameError as e:
        return _error(str(e))
    except DocError as e:
        return _error(str(e), status=404)
    return JSONResponse({"name": name, "contents": contents})


async def macro_put(request: Request) -> Response:
    store: JsonDocStore = request.app.state.macro_store
    name = request.path_params["name"]
    try:
        body = await request.json()
    except ValueError:
        return _error("invalid JSON body")
    contents = body.get("contents") if isinstance(body, dict) else None
    if not isinstance(contents, str):
        return _error("expected {'contents': '<macro json text>'}")

    macro, parse_err = parse_json_text(contents, label="macro")
    if parse_err is not None:
        return JSONResponse({"error": "invalid JSON", **parse_err}, status_code=400)

    try:
        validate_macro(macro)
    except MacroValidationError as e:
        return JSONResponse(
            {"error": "invalid macro", "detail": str(e), "path": e.path},
            status_code=400,
        )

    try:
        store.write_text(name, contents)
    except UnsafeNameError as e:
        return _error(str(e))
    logger.info(f"Saved macro '{name}'")
    return JSONResponse({"name": name, "saved": True})


async def macro_rename(request: Request) -> Response:
    store: JsonDocStore = request.app.state.macro_store
    name = request.path_params["name"]
    try:
        body = await request.json()
    except ValueError:
        return _error("invalid JSON body")
    new_name = body.get("name") if isinstance(body, dict) else None
    if not isinstance(new_name, str):
        return _error("expected {'name': '<new macro name>'}")
    running = request.app.state.manager.status().get("macro") or {}
    if running.get("name") == name:
        return _error(f"macro '{name}' is currently running", status=409)
    try:
        new_name = store.rename(name, new_name)
    except UnsafeNameError as e:
        return _error(str(e))
    except DocError as e:
        return _error(str(e), status=404)
    return JSONResponse({"name": new_name})


async def macro_delete(request: Request) -> Response:
    store: JsonDocStore = request.app.state.macro_store
    manager: InputManager = request.app.state.manager
    name = request.path_params["name"]
    running = manager.status().get("macro") or {}
    if running.get("name") == name:
        return _error(f"macro '{name}' is currently running", status=409)
    try:
        store.delete(name)
    except UnsafeNameError as e:
        return _error(str(e))
    except DocError as e:
        return _error(str(e), status=404)
    logger.info(f"Deleted macro '{name}'")
    return JSONResponse({"name": name, "deleted": True})


async def controllers_get(request: Request) -> Response:
    manager: InputManager = request.app.state.manager
    payload = await asyncio.to_thread(manager.controllers_payload)
    return JSONResponse(payload)


async def controller_select(request: Request) -> Response:
    manager: InputManager = request.app.state.manager
    store: ConfigStore = request.app.state.config_store
    try:
        body = await request.json()
    except ValueError:
        return _error("invalid JSON body")
    if not isinstance(body, dict):
        return _error("expected a JSON object")

    ident = body.get("guid") or body.get("name")
    if ident is None and "index" in body:
        ident = body["index"]
    if ident is None or ident == "":
        return _error("provide 'guid', 'name' or 'index'")

    try:
        info = await asyncio.to_thread(manager.select_controller, ident)
    except MacroActiveError as e:
        return _error(str(e), status=409)
    except ValueError as e:
        return _error(str(e), status=404)
    except RuntimeError as e:
        return _error(str(e), status=503)

    # Persist the selection (GUID) so it survives restarts.
    if info.get("guid"):
        store.update({"controller_guid": info["guid"]})
    payload = await asyncio.to_thread(manager.controllers_payload)
    return JSONResponse(payload)


async def presets_list(request: Request) -> Response:
    store: ConfigStore = request.app.state.config_store
    manager: InputManager = request.app.state.manager
    active = manager.current_preset_name or store.config.preset
    infos = [
        {**info, "active": info["filename"] == active} for info in list_preset_infos()
    ]
    return JSONResponse({"presets": infos, "active": active})


async def preset_get(request: Request) -> Response:
    name = request.path_params["name"]
    try:
        contents = read_preset_text(name)
    except FileNotFoundError:
        return _error(f"preset '{name}' does not exist", status=404)
    except ValueError as e:
        return _error(str(e))
    return JSONResponse({"name": name, "contents": contents})


async def preset_put(request: Request) -> Response:
    name = request.path_params["name"]
    if preset_name_is_builtin(name):
        return _error(
            f"'{name}' is a built-in preset; duplicate it under a new "
            f"name to customise",
            status=403,
        )
    try:
        body = await request.json()
    except ValueError:
        return _error("invalid JSON body")
    contents = body.get("contents") if isinstance(body, dict) else None
    if not isinstance(contents, str):
        return _error("expected {'contents': '<preset json text>'}")

    data, parse_err = parse_json_text(contents, label="preset")
    if parse_err is not None:
        return JSONResponse({"error": "invalid JSON", **parse_err}, status_code=400)

    try:
        validate_preset(data)
    except PresetValidationError as e:
        return JSONResponse(
            {"error": "invalid preset", "detail": str(e), "path": e.path},
            status_code=400,
        )

    try:
        save_preset_text(name, contents)
    except (PermissionError, ValueError) as e:
        return _error(str(e), status=403)
    logger.info(f"Saved preset '{name}'")
    return JSONResponse({"name": name, "saved": True})


async def preset_delete(request: Request) -> Response:
    store: ConfigStore = request.app.state.config_store
    name = request.path_params["name"]
    if preset_name_is_builtin(name):
        return _error(
            f"'{name}' is a built-in preset and cannot be deleted",
            status=403,
        )
    if store.config.preset == name or name in store.config.controller_presets.values():
        return _error(
            f"preset '{name}' is active or assigned to a controller",
            status=409,
        )
    try:
        delete_preset(name)
    except FileNotFoundError as e:
        return _error(str(e), status=404)
    except PermissionError as e:
        return _error(str(e), status=403)
    logger.info(f"Deleted preset '{name}'")
    return JSONResponse({"name": name, "deleted": True})


async def preset_activate(request: Request) -> Response:
    manager: InputManager = request.app.state.manager
    store: ConfigStore = request.app.state.config_store
    name = request.path_params["name"]
    if name not in [info["filename"] for info in list_preset_infos()]:
        return _error(f"preset '{name}' does not exist", status=404)

    try:
        preset = await asyncio.to_thread(manager.apply_preset, name)
    except MacroActiveError as e:
        return _error(str(e), status=409)
    except FileNotFoundError as e:
        return _error(str(e), status=404)
    except (ValueError, TypeError) as e:
        return _error(f"could not load preset: {e}")

    # Persist the selection so it survives restarts (and so the config
    # store stays the single source of truth).
    payload = await asyncio.to_thread(manager.controllers_payload)
    changes: dict = {"preset": name}
    active_guid = payload.get("active")
    if active_guid:
        controller_presets = dict(store.config.controller_presets)
        controller_presets[str(active_guid).casefold()] = name
        changes["controller_presets"] = controller_presets
    store.update(changes)
    payload["applied"] = preset.name
    return JSONResponse(payload)


async def config_get(request: Request) -> Response:
    store: ConfigStore = request.app.state.config_store
    return JSONResponse(store.snapshot())


async def config_patch(request: Request) -> Response:
    store: ConfigStore = request.app.state.config_store
    manager: InputManager = request.app.state.manager
    try:
        body = await request.json()
    except ValueError:
        return _error("invalid JSON body")
    if not isinstance(body, dict):
        return _error("expected a JSON object")
    requested_preset = body.get("preset")
    if requested_preset is not None and requested_preset != manager.current_preset_name:
        # Apply first: the persisted config must never claim a preset that
        # the runtime rejected or could not load.
        try:
            await asyncio.to_thread(manager.apply_preset, requested_preset)
        except MacroActiveError as e:
            return _error(str(e), status=409)
        except FileNotFoundError as e:
            return _error(str(e), status=404)
        except (ValueError, TypeError) as e:
            return _error(f"could not load preset: {e}")
    if requested_preset is not None:
        payload = await asyncio.to_thread(manager.controllers_payload)
        active_guid = payload.get("active")
        if active_guid:
            controller_presets = dict(store.config.controller_presets)
            controller_presets[str(active_guid).casefold()] = requested_preset
            body["controller_presets"] = controller_presets
    changed = store.update(body)
    return JSONResponse({"changed": changed, "config": store.snapshot()})


async def control_mode_get(request: Request) -> Response:
    manager: InputManager = request.app.state.manager
    return JSONResponse(manager.status())


async def control_mode_put(request: Request) -> Response:
    manager: InputManager = request.app.state.manager
    try:
        body = await request.json()
    except ValueError:
        return _error("invalid JSON body")
    mode = body.get("mode") if isinstance(body, dict) else None
    if mode not in ("manual", "macro"):
        return _error("mode must be 'manual' or 'macro'")
    manager.set_mode(mode)
    return JSONResponse(manager.status())


class SPAStaticFiles(StaticFiles):
    """StaticFiles with SPA history fallback: unknown paths (client-side
    routes like /macros) serve index.html so the router can pick them up."""

    async def get_response(self, path: str, scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except HTTPException as e:
            if e.status_code == 404:
                return await super().get_response("index.html", scope)
            raise


async def _frontend_not_built(request: Request) -> Response:
    return JSONResponse(
        {
            "error": "frontend not built",
            "detail": "Run `pnpm build` in the frontend/ directory, then restart.",
        },
        status_code=503,
    )


async def startup_status(request: Request) -> JSONResponse:
    firmware = request.app.state.missing_firmware
    if firmware:
        status = {"kind": "missing_firmware", "filename": firmware}
    elif request.app.state.usb_driver_error:
        status = {"kind": "usb_driver_error"}
    elif request.app.state.transport_pending:
        status = {"kind": "checking"}
    else:
        status = {"kind": "ready"}
    return JSONResponse(
        {**status, "ws_auth_required": request.app.state.ws_token is not None}
    )


async def close_application(request: Request) -> JSONResponse:
    event = request.app.state.shutdown_event
    if event is None:
        return _error("Application shutdown is unavailable", status=409)
    # A JSON content type prevents cross-origin HTML forms from closing the app.
    if request.headers.get("content-type", "").split(";", 1)[0] != "application/json":
        return _error("Expected application/json", status=415)

    async def request_shutdown():
        event.set()

    return JSONResponse({"closing": True}, background=BackgroundTask(request_shutdown))


def build_app(
    manager: InputManager,
    config_store: ConfigStore,
    frontend_dist: Path,
    macro_store: JsonDocStore | None = None,
    bluetooth: BluetoothService | None = None,
    missing_firmware: str | None = None,
    usb_driver_error: bool = False,
    shutdown_event: asyncio.Event | None = None,
    ws_token: str | None = None,
) -> Starlette:
    """Construct the Starlette application.

    ``frontend_dist`` is the React production build directory. If it
    doesn't exist (frontend not yet built) we fall back to a stub route
    so the WebSocket and REST API remain usable for testing.
    ``macro_store`` overrides the macro directory (tests).
    """
    if macro_store is None:
        macro_store = JsonDocStore(manager.macros_dir)

    routes = [
        Route("/api/startup", startup_status, methods=["GET"]),
        Route("/api/application/close", close_application, methods=["POST"]),
        Route(
            "/api/bluetooth",
            bluetooth_control,
            methods=["GET", "PUT", "POST", "DELETE"],
        ),
        WebSocketRoute("/ws", macro_ws_endpoint),
        Route("/api/config", config_get, methods=["GET"]),
        Route("/api/config", config_patch, methods=["PATCH"]),
        Route("/api/control-mode", control_mode_get, methods=["GET"]),
        Route("/api/control-mode", control_mode_put, methods=["PUT"]),
        Route("/api/macros", macros_list, methods=["GET"]),
        Route("/api/macros/{name}", macro_get, methods=["GET"]),
        Route("/api/macros/{name}", macro_put, methods=["PUT"]),
        Route("/api/macros/{name}", macro_rename, methods=["PATCH"]),
        Route("/api/macros/{name}", macro_delete, methods=["DELETE"]),
        Route("/api/controllers", controllers_get, methods=["GET"]),
        Route("/api/controllers/active", controller_select, methods=["PUT"]),
        Route("/api/presets", presets_list, methods=["GET"]),
        Route("/api/presets/{name}", preset_get, methods=["GET"]),
        Route("/api/presets/{name}", preset_put, methods=["PUT"]),
        Route("/api/presets/{name}", preset_delete, methods=["DELETE"]),
        Route("/api/presets/{name}/activate", preset_activate, methods=["POST"]),
    ]

    if frontend_dist.exists() and (frontend_dist / "index.html").exists():
        routes.append(
            Mount(
                "/",
                app=SPAStaticFiles(directory=str(frontend_dist), html=True),
                name="frontend",
            )
        )
        logger.info(f"Serving frontend from {frontend_dist}")
    else:
        routes.append(Route("/", _frontend_not_built, methods=["GET"]))
        logger.warning(
            f"Frontend build not found at {frontend_dist}; "
            f"serving API only. Run `pnpm build` in frontend/."
        )

    app = Starlette(routes=routes)
    app.state.manager = manager
    app.state.bluetooth = bluetooth if bluetooth is not None else BluetoothService()
    app.state.config_store = config_store
    app.state.macro_store = macro_store
    app.state.missing_firmware = missing_firmware
    app.state.usb_driver_error = usb_driver_error
    app.state.transport_pending = False
    app.state.shutdown_event = shutdown_event
    app.state.ws_token = (
        (ws_token or secrets.token_urlsafe(32))
        if config_store.config.ws_auth_required
        else None
    )
    return app
