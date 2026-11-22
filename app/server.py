"""Serve the frontend and handle HTTP and WebSocket requests for controllers, macros, presets, and settings."""

from __future__ import annotations

import asyncio
import logging
import secrets
import sys
from pathlib import Path

from starlette.applications import Starlette
from starlette.background import BackgroundTask
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocket, WebSocketDisconnect

from app.bluetooth import (
    AdapterSession,
    BluetoothDisconnectingError,
    BluetoothPageTimeoutError,
    BluetoothService,
    configure_adapter_outputs,
)
from app.input.controller_service import ControllerRoute
from app.input.manager import InputManager, MacroActiveError, state_from_event
from lib.colours import normalize_controller_colours
from lib.config import (
    ConfigStore,
    new_profile_address,
    normalize_controller_motion,
    normalize_controller_vibration,
)
from lib.controller import ControllerVariant
from lib.device_names import normalize_device_names, validate_device_name
from lib.input.macros import (
    MacroCapabilityError,
    MacroValidationError,
    validate_macro,
    validate_macro_capabilities,
)
from lib.input.presets import (
    PresetValidationError,
    delete_preset,
    list_preset_infos,
    load_preset,
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
    validate_name,
)
from lib.server.protocol import (
    EventMessage,
    InboundMessage,
    MacroCancel,
    MacroPause,
    MacroResume,
    MacroStartByName,
    MacroStartInline,
    ProtocolError,
    SelectAdapter,
    StateMessage,
    error_frame,
    frame_text,
    parse_message,
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
    primary: InputManager = websocket.app.state.manager
    sessions: dict[str, AdapterSession] = websocket.app.state.adapter_sessions
    if websocket.app.state.startup_phase is not None and not sessions:
        await websocket.close(code=1013)
        return
    await websocket.accept(subprotocol="ounce-bt" if token is not None else None)
    managers = {"primary": primary}
    managers.update({
        slot.id: slot.input_manager for slot in sessions.values() if slot.input_manager
    })
    selected = ("primary",)
    manual_targets: set[InputManager] = set()

    def target_for(adapter_id: str) -> str:
        slot = sessions.get(adapter_id)
        return slot.input_owner.id if slot else adapter_id

    def selection_status() -> dict:
        has_joycons = any(
            adapter_id in sessions and sessions[adapter_id].mapping_variant() != ControllerVariant.PRO
            for adapter_id in selected
        )
        output = {"has_joycons": True} if has_joycons else {}
        if len(selected) == 1 and target_for(selected[0]) == selected[0]:
            return {**managers[selected[0]].status_payload(), **output}
        statuses = {
            adapter_id: managers[target_for(adapter_id)].status() for adapter_id in selected
        }
        return {
            "type": "status",
            "adapter_id": selected[0],
            **statuses[selected[0]],
            "adapter_statuses": statuses,
            **output,
        }

    status_q: asyncio.Queue = asyncio.Queue()
    for source in managers.values():
        source.ensure_loop(asyncio.get_running_loop())
        source.subscribe(status_q)

    # Exactly one outstanding websocket.receive() at any time (multiple
    # concurrent receive() calls race disconnects and raise).
    incoming: asyncio.Queue[str | None] = asyncio.Queue()

    async def reader() -> None:
        try:
            while True:
                event = await websocket.receive()
                if event["type"] == "websocket.disconnect":
                    return
                text = event.get("text") or ""
                if text:
                    incoming.put_nowait(text)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            incoming.put_nowait(None)  # disconnect sentinel

    reader_task = asyncio.create_task(reader())
    incoming_task = asyncio.create_task(incoming.get())
    status_task = asyncio.create_task(status_q.get())

    try:
        await websocket.send_text(frame_text(selection_status()))
        await websocket.send_text(frame_text(primary.controllers_payload()))
        # Persistent get-tasks, renewed immediately after consumption so
        # no frame is ever stranded in an abandoned task.
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
                    message = parse_message(text)
                    if isinstance(message, SelectAdapter):
                        if any(adapter_id not in managers for adapter_id in message.adapter_ids):
                            raise ProtocolError("Unknown adapter")
                        if set(selected) != set(message.adapter_ids):
                            for manager in manual_targets:
                                manager.release_manual_input()
                            manual_targets.clear()
                            selected = message.adapter_ids
                        await websocket.send_text(frame_text(selection_status()))
                    elif isinstance(message, (EventMessage, StateMessage)):
                        state = (
                            state_from_event(message.action)
                            if isinstance(message, EventMessage) else message.to_state()
                        )
                        accepted = False
                        for adapter_id in dict.fromkeys(map(target_for, selected)):
                            manager = managers[adapter_id]
                            if manager.submit_state(state):
                                accepted = True
                                manual_targets.add(manager)
                        if not accepted:
                            await websocket.send_text(
                                error_frame("manual input disabled while macro running")
                            )
                    else:
                        targets = tuple(dict.fromkeys(map(target_for, selected)))
                        error = _dispatch_macro(
                            message, [managers[target] for target in targets],
                            {sessions[target].mapping_variant() if target in sessions
                             else ControllerVariant.PRO for target in targets},
                        )
                        if error is not None:
                            await websocket.send_text(error)
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
                if payload["type"] == "status":
                    if payload.get("adapter_id", "primary") not in map(target_for, selected):
                        continue
                    payload = selection_status()
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
        for source in managers.values():
            source.unsubscribe(status_q)
        for manager in manual_targets:
            if manager.adapter_id is not None:
                manager.release_manual_input()


def _dispatch_macro(
    msg: InboundMessage, managers: list[InputManager], variants: set[ControllerVariant],
) -> str | None:
    if isinstance(msg, (MacroStartInline, MacroStartByName)):
        try:
            macro = msg.macro if isinstance(msg, MacroStartInline) else managers[0].read_named_macro(msg.name)
            validate_macro(macro)
            for variant in sorted(variants):
                validate_macro_capabilities(macro, variant)
        except MacroCapabilityError as error:
            return error_frame("Macro is incompatible with the selected controller", detail=error.message,
                               code="macro_capability")
        except (FileNotFoundError, ValueError) as e:
            if isinstance(msg, MacroStartInline):
                return error_frame("invalid macro", detail=str(e))
            return error_frame(f"could not load macro: {e}")
        for manager in managers:
            manager.start_macro(macro)
    else:
        for manager in managers:
            if isinstance(msg, MacroCancel):
                manager.cancel_macro()
            elif isinstance(msg, MacroPause):
                manager.pause_macro()
            elif isinstance(msg, MacroResume):
                manager.resume_macro()
    return None


async def bluetooth_control(request: Request) -> Response:
    service: BluetoothService = request.app.state.bluetooth
    sessions: dict[str, AdapterSession] = request.app.state.adapter_sessions
    if session_id := request.path_params.get("session_id"):
        if session_id not in sessions:
            return _error("Unknown adapter", status=404)
        service = sessions[session_id].bluetooth
    store: ConfigStore = request.app.state.config_store
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
                    names = dict(store.config.switch_device_names)
                    if len(sessions) <= 1 and names.pop(body["address"].upper(), None) is not None:
                        store.update({"switch_device_names": names})
                elif request.method == "PATCH":
                    if body["address"] not in (await service.status())["peers"]:
                        raise ValueError("Select a previously paired device")
                    name = validate_device_name(body.get("name"))
                    store.update(
                        {
                            "switch_device_names": {
                                **store.config.switch_device_names,
                                body["address"].upper(): name,
                            }
                        }
                    )
                else:
                    await service.reconnect(body["address"])
        status = await service.status()
        status["names"] = {
            address: store.config.switch_device_names.get(
                address.upper(), f"Switch Device {index}"
            )
            for index, address in enumerate(status["peers"], 1)
        }
        return JSONResponse(status)
    except BluetoothDisconnectingError as e:
        return JSONResponse({"error": str(e), "code": "disconnecting"}, status_code=409)
    except BluetoothPageTimeoutError as e:
        return JSONResponse({"error": str(e), "code": "page_timeout"}, status_code=503)
    except (TypeError, ValueError) as e:
        return _error(str(e), status=409)
    except Exception as e:
        logger.exception("Bluetooth operation failed")
        return _error(f"Bluetooth operation failed: {e}", status=503)


async def adapters_get(request: Request) -> Response:
    try:
        return JSONResponse(await adapter_inventory(request.app.state.adapter_sessions))
    except RuntimeError as error:
        return _error(str(error), status=503)


async def adapter_inventory(sessions: dict[str, AdapterSession]) -> dict:
    primary = sessions.get("primary")
    controllers = (
        await asyncio.to_thread(primary.controller.status)
        if primary and primary.controller
        else {}
    )
    assignments = controllers.get("assignments", {})
    return {
        "adapters": [
            {
                "id": session.id,
                "transport": session.transport,
                "local_address": session.local_address,
                "controller_id": assignments.get(session.id),
                "error": session.error,
                "controller_type": session.bluetooth.controller_type,
                "combined_with": session.combined_partner.id if session.combined_partner else None,
                "preset": (
                    session.controller.preset_name
                    if isinstance(session.controller, ControllerRoute)
                    else session.input_manager.current_preset_name
                    if session.input_manager
                    else None
                ),
                "macro_mode": bool(
                    session.input_manager and session.input_manager.status()["mode"] == "macro"
                ),
            }
            for session in sessions.values()
        ],
        "controllers": [
            {
                "id": pad["instance_id"],
                "name": pad["name"],
                "guid": pad["guid"],
                "gamepad_type": pad.get("gamepad_type", "standard"),
                "has_gyro": bool(pad.get("has_gyro", False)),
                "has_accel": bool(pad.get("has_accel", False)),
                "has_rumble": bool(pad.get("has_rumble", False)),
            }
            for pad in controllers.get("controllers", [])
            if pad.get("instance_id") is not None
        ],
        "controllers_available": controllers.get("available", False),
    }


async def adapter_assign(request: Request) -> Response:
    sessions: dict[str, AdapterSession] = request.app.state.adapter_sessions
    session_id = request.path_params["session_id"]
    if session_id not in sessions:
        return _error("Unknown adapter", status=404)
    service = sessions["primary"].controller
    if service is None:
        return _error("Controller service is unavailable", status=503)
    try:
        body = await request.json()
    except ValueError:
        return _error("invalid JSON body")
    if not isinstance(body, dict) or "controller_id" not in body:
        return _error("controller_id is required")
    instance_id = body["controller_id"]
    if instance_id is not None and type(instance_id) is not int:
        return _error("controller_id must be an instance ID or null")
    try:
        await asyncio.to_thread(service.assign, session_id, instance_id)
    except ValueError as error:
        return _error(str(error), status=409)
    except RuntimeError as error:
        return _error(str(error), status=503)
    return await adapters_get(request)


async def adapter_colours(request: Request) -> Response:
    slot = request.app.state.adapter_sessions.get(request.path_params["session_id"])
    if slot is None:
        return _error("Unknown adapter", status=404)
    store: ConfigStore = request.app.state.config_store
    profile_index = slot.profile_index
    if request.method == "PATCH":
        try:
            body = await request.json()
        except ValueError:
            return _error("invalid JSON body")
    variant = slot.bluetooth.controller_type
    requested_variant = request.query_params.get("controller_type")
    if requested_variant is not None and requested_variant != variant:
        return _error("Controller type changed. Reopen the colour editor.", status=409)
    profile = store.config.adapter_profiles[profile_index] if profile_index is not None else None
    if profile is not None:
        colours = profile.colours_for(variant)
    else:
        colours = store.config.colours_for_adapter(slot.transport, primary=slot.primary)
    changed = False
    if request.method == "PATCH":
        try:
            updated = normalize_controller_colours(body, colours)
        except (TypeError, ValueError) as error:
            return _error(str(error))
        changed = updated != colours
        if changed:
            if profile is not None and variant != ControllerVariant.PRO:
                store.update_adapter_profile(profile_index, joycon_colours={
                    **profile.joycon_colours, variant: updated,
                })
            elif profile_index is not None:
                store.update_adapter_profile(profile_index, colours=updated)
            elif slot.primary:
                store.update({"controller_colours": updated})
            else:
                store.update({"adapter_colours": {
                    **store.config.adapter_colours, slot.transport.casefold(): updated
                }})
            colours = updated
    radio = slot.bluetooth
    return JSONResponse({
        "controller_colours": colours,
        "controller_type": variant,
        "colours_reconnect_required": changed and bool(
            radio.connection or radio.connected or radio.reconnecting
        ),
    })


async def adapter_controller_type(request: Request) -> Response:
    sessions: dict[str, AdapterSession] = request.app.state.adapter_sessions
    slot = sessions.get(request.path_params["session_id"])
    if slot is None:
        return _error("Unknown adapter", status=404)
    if slot.profile_index is None or slot.bluetooth.device is None or slot.error:
        return _error("Bluetooth is not ready", status=503)
    try:
        body = await request.json()
        variant = ControllerVariant(body["controller_type"])
    except (KeyError, TypeError, ValueError):
        return _error("Select a controller type")

    store: ConfigStore = request.app.state.config_store
    profiles = store.config.adapter_profiles
    index = slot.profile_index
    previous_partner = profiles[index].combined_with
    changes = {index: {"controller_type": variant, "combined_with": None}}
    if previous_partner is not None:
        changes[previous_partner] = {"combined_with": None}
    if variant == ControllerVariant.COMBINED:
        companion_id = body.get("companion_id")
        companion = sessions.get(companion_id) if isinstance(companion_id, str) else None
        if (
            companion is None or companion is slot or companion.profile_index is None
            or companion.bluetooth.device is None or companion.error
        ):
            return _error("Select a second Bluetooth adapter for the right Joy-Con")
        right = companion.profile_index
        if profiles[right].combined_with not in (None, index):
            return _error("The second adapter already belongs to a Joycons pair", status=409)
        changes[index] = {"controller_type": ControllerVariant.LEFT, "combined_with": right}
        changes[right] = {"controller_type": ControllerVariant.RIGHT, "combined_with": index}

    affected = [item for item in sessions.values() if item.profile_index in changes]
    try:
        for item in affected:
            item.bluetooth.check_output_change()
            if item.input_manager and item.input_manager.status()["mode"] == "macro":
                raise ValueError("Stop the macro before changing controller type.")
        store.update_adapter_profiles(changes)
        configure_adapter_outputs(sessions, store.config.adapter_profiles)
        for item in affected:
            if item.input_manager:
                item.input_manager.release_manual_input()
                item.input_manager.broadcast_status()
    except ValueError as error:
        return _error(str(error), status=409)
    except OSError as error:
        return _error(f"Could not save controller type: {error}", status=503)
    return await adapters_get(request)


def macro_is_running(request: Request, name: str) -> bool:
    managers = [request.app.state.manager, *(
        slot.input_manager for slot in request.app.state.adapter_sessions.values()
        if not slot.primary and slot.input_manager
    )]
    return any((manager.status().get("macro") or {}).get("name") == name for manager in managers)


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
    if macro_is_running(request, name):
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
    name = request.path_params["name"]
    if macro_is_running(request, name):
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
    try:
        name = validate_name(request.path_params["name"])
    except UnsafeNameError as error:
        return _error(str(error), status=403)
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
    if (
        store.config.preset == name
        or name in store.config.controller_presets.values()
        or name in store.config.adapter_presets.values()
        or any(profile.preset == name for profile in store.config.adapter_profiles)
    ):
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

    session_id = request.path_params.get("session_id")
    if session_id:
        sessions = request.app.state.adapter_sessions
        slot = sessions.get(session_id)
        if slot is None:
            return _error("Unknown adapter", status=404)
        if not slot.primary:
            service = sessions["primary"].controller
            if service is None:
                return _error("Controller service is unavailable", status=503)
            try:
                preset = load_preset(name)
                await asyncio.to_thread(service.set_preset, preset, name, session_id=session_id)
            except (FileNotFoundError, TypeError, ValueError, RuntimeError) as error:
                return _error(str(error), status=409)
            if slot.profile_index is not None:
                store.update_adapter_profile(slot.profile_index, preset=name)
            else:
                store.update({"adapter_presets": {
                    **store.config.adapter_presets, slot.transport.casefold(): name
                }})
            return await adapters_get(request)

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
    primary = request.app.state.adapter_sessions.get("primary")
    if primary is not None and primary.profile_index is not None:
        store.update_adapter_profile(primary.profile_index, preset=name)
        if session_id:
            return await adapters_get(request)
        payload["applied"] = preset.name
        return JSONResponse(payload)
    changes: dict = {"preset": name}
    active_guid = payload.get("active")
    if active_guid:
        controller_presets = dict(store.config.controller_presets)
        controller_presets[str(active_guid).casefold()] = name
        changes["controller_presets"] = controller_presets
    store.update(changes)
    if session_id:
        return await adapters_get(request)
    payload["applied"] = preset.name
    return JSONResponse(payload)


DEBUG_RESTART_KEYS = {
    "nolog",
    "bumble_logging",
    "ws_auth_required",
    "macro_rate_hz",
    "tick_rate_hz",
    "bt_address",
}


def validate_debug_changes(body):
    for key in ("debug_enabled", "nolog", "bumble_logging", "ws_auth_required"):
        if key in body and not isinstance(body[key], bool):
            raise ValueError(f"{key} must be a boolean")
    for key in ("macro_rate_hz", "tick_rate_hz"):
        if key in body and (type(body[key]) is not int or not 1 <= body[key] <= 1000):
            raise ValueError(f"{key} must be an integer between 1 and 1000")
    if {"bt_address", "adapter_address_seed", "adapter_addresses", "adapter_profiles"} & body.keys():
        raise ValueError("Use Regenerate BD address to change the Bluetooth identity")


async def _bluetooth_debug_status(
    service: BluetoothService, names: dict[str, str], *, include_unbonded_names: bool = False
) -> dict:
    state = service.state
    bluetooth = await service.status()
    addresses = set(bluetooth["peers"])
    if include_unbonded_names:
        addresses.update(names)
    if bluetooth["address"]:
        addresses.add(bluetooth["address"])
    return {
        "bd_address": str(service.device.public_address) if service.device else None,
        "bluetooth": bluetooth,
        "switch_devices": [
            {
                "address": address,
                "name": names.get(address.upper())
                or (
                    f"Switch Device {bluetooth['peers'].index(address) + 1}"
                    if address in bluetooth["peers"]
                    else "Switch Device"
                ),
            }
            for address in sorted(addresses)
        ],
        "acl_connected": service.connection is not None,
        "hid_control_ready": bool(state and state.ctrl_ready.is_set()),
        "hid_interrupt_ready": bool(state and state.intr_ready.is_set()),
        "session_stopped": bool(state and state.session_stop.is_set()),
    }


async def debug_status(request: Request) -> Response:
    state = request.app.state
    config = state.config_store.config
    sessions = state.adapter_sessions
    names = config.switch_device_names
    primary = await _bluetooth_debug_status(
        state.bluetooth, names, include_unbonded_names=len(sessions) <= 1
    )
    try:
        inventory = await adapter_inventory(sessions)
    except RuntimeError as error:
        return _error(str(error), status=503)
    controller_names = {pad["id"]: pad["name"] for pad in inventory["controllers"]}
    adapters = []
    for adapter in inventory["adapters"]:
        session = sessions[adapter["id"]]
        diagnostics = (
            primary
            if session.primary
            else await _bluetooth_debug_status(session.bluetooth, names)
        )
        adapters.append(
            {
                **adapter,
                **diagnostics,
                "controller_name": controller_names.get(adapter["controller_id"]),
                "address_regeneration_available": sys.platform == "win32"
                and session.bluetooth.device is not None,
                "input": session.input_manager.status() if session.input_manager else None,
            }
        )
    return JSONResponse(
        {
            **primary,
            "adapters": adapters,
            "input": state.manager.status(),
            "controllers": await asyncio.to_thread(state.manager.controllers_payload),
            "ws_auth_required": state.ws_token is not None,
            "address_regeneration_available": sys.platform == "win32"
            and state.bluetooth.device is not None,
            "restart_available": state.restart_callback is not None,
        }
    )


async def debug_apply(request: Request) -> Response:
    store = request.app.state.config_store
    if request.headers.get("content-type", "").split(";", 1)[0] != "application/json":
        return _error("Expected application/json", status=415)
    if not store.config.debug_enabled:
        return _error("Debug settings are disabled", status=403)
    try:
        body = await request.json()
        if not isinstance(body, dict) or set(body) - {"changes", "regenerate_address"}:
            raise ValueError("Invalid debug settings request")
        changes = body.get("changes", {})
        if not isinstance(changes, dict) or set(changes) - (
            DEBUG_RESTART_KEYS - {"bt_address"}
        ):
            raise ValueError("Unknown debug setting")
        validate_debug_changes(changes)
        regenerate = body.get("regenerate_address", False)
        if not isinstance(regenerate, (bool, str)) or regenerate == "":
            raise TypeError("regenerate_address must be a boolean or adapter ID")
        if changes.get("ws_auth_required") and not store.config.webview_enabled:
            raise ValueError("WebSocket authentication requires desktop mode")
        if regenerate and sys.platform != "win32":
            raise ValueError("This platform uses the adapter's hardware address")
    except (ValueError, TypeError) as error:
        return _error(str(error))
    if (
        request.app.state.restart_callback is None
        or request.app.state.shutdown_event is None
    ):
        return _error("Application restart is unavailable", status=409)
    if regenerate:
        state = request.app.state
        sessions = state.adapter_sessions
        adapter_id = "primary" if regenerate is True else regenerate
        session = sessions.get(adapter_id)
        if session is None and adapter_id != "primary":
            return _error("Unknown adapter", status=404)
        service = session.bluetooth if session else state.bluetooth
        config = store.config
        transport = session.transport.casefold() if session else config.transport_spec.casefold()
        use_primary_address = adapter_id == "primary" and transport not in config.adapter_addresses
        used_addresses = {
            slot.local_address.upper()
            for slot in sessions.values()
            if slot.local_address
        }
        used_addresses.add(config.bt_address.upper())
        used_addresses.update(value.upper() for value in config.adapter_addresses.values())
        used_addresses.update(profile.address for profile in config.adapter_profiles)
        if current_address := getattr(service.device, "public_address", None):
            used_addresses.add(str(current_address).split("/")[0].upper())
        prefix = bytes([0x98, 0xB6, 0xE9]) if use_primary_address else bytes([2])
        while True:
            octets = prefix + secrets.token_bytes(6 - len(prefix))
            address = ":".join(f"{byte:02X}" for byte in octets)
            if address not in used_addresses:
                break
        try:
            await service.forget_all()
        except (OSError, RuntimeError, TimeoutError) as error:
            return _error(f"Could not clear saved Switch devices: {error}", status=503)
        if session is not None and session.profile_index is not None:
            store.update_adapter_profile(
                session.profile_index, address=new_profile_address(used_addresses), legacy_keystore=False
            )
        elif use_primary_address:
            changes["bt_address"] = address
            # Keep the secondary adapters' derived addresses stable.
            if not config.adapter_address_seed:
                changes["adapter_address_seed"] = config.bt_address
        else:
            changes["adapter_addresses"] = {
                **config.adapter_addresses,
                transport: address,
            }
        if len(sessions) <= 1 and adapter_id == "primary":
            changes["switch_device_names"] = {}
    store.update(changes)

    async def restart():
        request.app.state.restart_callback()
        request.app.state.shutdown_event.set()

    return JSONResponse({"restarting": True}, background=BackgroundTask(restart))


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
    try:
        validate_debug_changes(body)
    except ValueError as error:
        return _error(str(error))
    if any(
        key in body and body[key] != store.snapshot().get(key)
        for key in DEBUG_RESTART_KEYS
    ):
        return _error(
            "These settings require Save and restart in the Debug tab", status=409
        )
    for flag in ("vibration_enabled", "motion_enabled"):
        if flag in body and not isinstance(body[flag], bool):
            return _error(f"{flag} must be a boolean")
    for key, normalize in (
        ("controller_vibration", normalize_controller_vibration),
        ("controller_motion", normalize_controller_motion),
    ):
        if key in body:
            try:
                normalize(body[key])
            except ValueError as error:
                return _error(str(error))
    if "controller_colours" in body:
        try:
            normalize_controller_colours(body["controller_colours"])
        except (TypeError, ValueError) as e:
            return _error(str(e))
    if "switch_device_names" in body:
        try:
            normalize_device_names(body["switch_device_names"])
        except (TypeError, ValueError) as e:
            return _error(str(e))
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
    primary = request.app.state.adapter_sessions.get("primary")
    if primary is not None and primary.profile_index is not None:
        profile = store.config.adapter_profiles[primary.profile_index]
        profile_changes = {}
        if "controller_colours" in body:
            colours = normalize_controller_colours(body["controller_colours"], profile.colours)
            if colours != profile.colours:
                profile_changes["colours"] = colours
                changed["controller_colours"] = colours
        if requested_preset is not None:
            profile_changes["preset"] = requested_preset
        if profile_changes:
            store.update_adapter_profile(primary.profile_index, **profile_changes)
    bluetooth: BluetoothService = request.app.state.bluetooth
    return JSONResponse(
        {
            "changed": changed,
            "config": store.snapshot(),
            "colours_reconnect_required": bool(
                "controller_colours" in changed
                and (
                    bluetooth.connection
                    or bluetooth.connected
                    or bluetooth.reconnecting
                )
            ),
        }
    )


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
            response = await super().get_response(path, scope)
        except HTTPException as e:
            if e.status_code == 404:
                response = await super().get_response("index.html", scope)
            else:
                raise
        if (
            response.headers.get("content-type", "").startswith("text/html")
            or response.status_code == 304
        ):
            response.headers["Cache-Control"] = "no-cache"
        return response


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
    elif request.app.state.bluetooth_error:
        status = {
            "kind": "bluetooth_error",
            "message": request.app.state.bluetooth_error,
        }
    elif request.app.state.startup_phase is not None:
        status = {"kind": "checking", "phase": request.app.state.startup_phase}
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
    restart_callback=None,
    adapter_sessions: dict[str, AdapterSession] | None = None,
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
        Route("/api/debug", debug_status, methods=["GET"]),
        Route("/api/debug", debug_apply, methods=["POST"]),
        Route("/api/startup", startup_status, methods=["GET"]),
        Route("/api/application/close", close_application, methods=["POST"]),
        Route(
            "/api/bluetooth",
            bluetooth_control,
            methods=["GET", "PUT", "POST", "DELETE", "PATCH"],
        ),
        Route("/api/adapters", adapters_get, methods=["GET"]),
        Route("/api/adapters/{session_id}/controller", adapter_assign, methods=["PUT"]),
        Route("/api/adapters/{session_id}/colours", adapter_colours, methods=["GET", "PATCH"]),
        Route("/api/adapters/{session_id}/type", adapter_controller_type, methods=["PUT"]),
        Route("/api/adapters/{session_id}/preset/{name}", preset_activate, methods=["POST"]),
        Route(
            "/api/adapters/{session_id}/bluetooth",
            bluetooth_control,
            methods=["GET", "PUT", "POST", "DELETE", "PATCH"],
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
    app.state.adapter_sessions = adapter_sessions or {}
    app.state.config_store = config_store
    app.state.macro_store = macro_store
    app.state.missing_firmware = missing_firmware
    app.state.usb_driver_error = usb_driver_error
    app.state.bluetooth_error = None
    app.state.startup_phase = None
    app.state.restart_callback = restart_callback
    app.state.shutdown_event = shutdown_event
    app.state.ws_token = (
        (ws_token or secrets.token_urlsafe(32))
        if config_store.config.ws_auth_required
        else None
    )
    return app
