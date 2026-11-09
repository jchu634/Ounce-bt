"""Test document safety, JSON parsing, macro and preset validation, and WebSocket message parsing."""

import json

import pytest

from lib.input.macros import MacroValidationError, validate_macro
from lib.input.presets import PresetValidationError, validate_preset
from lib.server.files import (
    JsonDocStore,
    UnsafeNameError,
    doc_path,
    parse_json_text,
    validate_name,
)
from lib.server.protocol import (
    EventMessage,
    MacroStartByName,
    MacroStartInline,
    ProtocolError,
    StateMessage,
    parse_message,
)


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "  ",
        "../etc/passwd",
        "foo/bar",
        "a\\b",
        ".hidden",
        "..",
        "a:b",
        "x" * 65,
    ],
)
def test_validate_name_rejects(bad):
    with pytest.raises(UnsafeNameError):
        validate_name(bad)


@pytest.mark.parametrize("good", ["a", "My Macro 2", "press-a", "x_9", "A" * 64])
def test_validate_name_accepts(good):
    assert validate_name(good) == good.strip()


def test_doc_path_stays_inside_dir(tmp_path):
    path = doc_path(tmp_path, "ok")
    assert path.parent == tmp_path.resolve()
    assert path.name == "ok.json"


def test_doc_path_rejects_traversal(tmp_path):
    with pytest.raises(UnsafeNameError):
        doc_path(tmp_path, "..")



def test_parse_json_text_error_position():
    bad = '{\n  "actions": ['
    value, err = parse_json_text(bad)
    assert value is None
    assert err is not None
    assert err["line"] == 2
    assert err["col"] >= 1


def test_parse_json_text_non_object():
    value, err = parse_json_text("[1, 2]")
    assert value is None
    assert err is not None



def _ok_macro():
    return {
        "version": 1,
        "name": "t",
        "repeat": 2,
        "actions": [
            {"do": "press", "button": "A"},
            {"do": "wait", "ms": 10},
            {
                "do": "loop",
                "count": 2,
                "actions": [
                    {"do": "stick", "side": "right", "x": -1, "y": 0.5},
                    {"do": "release", "button": "a"},
                ],
            },
        ],
    }


def test_validate_macro_ok():
    validate_macro(_ok_macro())


@pytest.mark.parametrize("unit", ["ms", "seconds"])
def test_validate_macro_preserves_duration_presentation(unit):
    macro = {"version": 1, "actions": [{"do": "wait", "ms": 1500, "unit": unit}]}
    assert validate_macro(macro) == macro


@pytest.mark.parametrize("unit", ["minutes", None, 1000, True])
def test_validate_macro_rejects_invalid_duration_unit(unit):
    macro = {"version": 1, "actions": [{"do": "wait", "ms": 1500, "unit": unit}]}
    with pytest.raises(MacroValidationError) as exc:
        validate_macro(macro)
    assert exc.value.path == ["actions", 0, "unit"]


@pytest.mark.parametrize(
    ("mutate", "path"),
    [
        (lambda m: m.pop("version"), ["version"]),
        (lambda m: m.update(version=2), ["version"]),
        (lambda m: m.pop("actions"), []),
        (lambda m: m.update(actions={}), ["actions"]),
        (lambda m: m.update(repeat=-1), ["repeat"]),
        (lambda m: m.update(repeat="2"), ["repeat"]),
        (lambda m: m["actions"].__setitem__(0, {"do": "press"}), ["actions", 0]),
        (
            lambda m: m["actions"][0].update(button="Q"),
            ["actions", 0, "button"],
        ),
        (lambda m: m["actions"].__setitem__(1, {"do": "wait", "ms": -5}), ["actions", 1, "ms"]),
        (lambda m: m["actions"].__setitem__(2, {"do": "explode"}), ["actions", 2]),
    ],
)
def test_validate_macro_failures(mutate, path):
    macro = _ok_macro()
    mutate(macro)
    with pytest.raises(MacroValidationError) as exc:
        validate_macro(macro)
    assert exc.value.path == path


def test_validate_macro_deep_nesting():
    macro = {"version": 1, "actions": [{"do": "loop", "count": 1, "actions": []}]}
    # Nest 20 loops deep; validator must stop at 16.
    inner = macro["actions"][0]
    for _ in range(20):
        child = {"do": "loop", "count": 1, "actions": []}
        inner["actions"] = [child]
        inner = child
    with pytest.raises(MacroValidationError):
        validate_macro(macro)



def _ok_preset():
    return {
        "name": "T",
        "rumble_enabled": False,
        "buttons": {"0": "B", "1": "A"},
        "triggers": {"4": "ZL"},
        "left_stick": {"x_axis": 0, "y_axis": 1},
        "right_stick": {"x_axis": 3, "y_axis": 4},
        "dpad": {"hat": 0},
    }


def test_validate_preset_ok():
    preset = validate_preset(_ok_preset())
    assert preset.rumble_enabled is False
    assert preset.button_map[0].name == "B"


@pytest.mark.parametrize(
    ("mutate", "path"),
    [
        (lambda p: p["buttons"].update({"2": "QQ"}), ["buttons", "2"]),
        (lambda p: p["buttons"].update({"x": "A"}), ["buttons", "x"]),
        (lambda p: p["triggers"].update({"9": 5}), ["triggers", "9"]),
        (lambda p: p["left_stick"].update(x_axis=-1), ["left_stick", "x_axis"]),
        (lambda p: p["dpad"].update(hat="zero"), ["dpad", "hat"]),
        (lambda p: p.update(rumble_enabled="yes"), ["rumble_enabled"]),
    ],
)
def test_validate_preset_failures(mutate, path):
    preset = _ok_preset()
    mutate(preset)
    with pytest.raises(PresetValidationError) as exc:
        validate_preset(preset)
    assert exc.value.path == path



def test_parse_message_roundtrip():
    msg = parse_message('{"type": "state", "buttons": ["A","B"], "left": [0,1], "right": [0,0]}')
    assert isinstance(msg, StateMessage)
    state = msg.to_state()
    assert int(state.buttons) == (1 << 3) | (1 << 2)  # A | B

    msg = parse_message('{"type": "event", "action": {"do": "press", "button": "A"}}')
    assert isinstance(msg, EventMessage)

    msg = parse_message('{"type": "macro", "op": "start", "name": "x"}')
    assert isinstance(msg, MacroStartByName)

    inline = {"version": 1, "name": "x", "actions": []}
    msg = parse_message(json.dumps({"type": "macro", "op": "start", "macro": inline}))
    assert isinstance(msg, MacroStartInline)


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        "[]",
        '{"type": "nope"}',
        '{"type": "event"}',
        '{"type": "macro", "op": "start"}',
        '{"type": "macro", "op": "wat"}',
        '{"type": "state", "left": [1, 2, 3]}',
    ],
)
def test_parse_message_rejects(raw):
    with pytest.raises(ProtocolError):
        parse_message(raw)



def test_doc_store_write_read_delete(tmp_path):
    store = JsonDocStore(tmp_path)
    assert store.list_names() == []
    store.write_text("alpha", "{}")
    assert store.list_names() == ["alpha"]
    assert json.loads(store.read_text("alpha")) == {}
    store.delete("alpha")
    assert store.list_names() == []
    assert not store.exists("alpha")


def test_doc_store_missing(tmp_path):
    from lib.server.files import DocError

    store = JsonDocStore(tmp_path)
    with pytest.raises(DocError):
        store.read_text("ghost")
    with pytest.raises(DocError):
        store.delete("ghost")
