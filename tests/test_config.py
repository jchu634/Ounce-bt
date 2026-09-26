from lib.config import Config, ConfigStore


def test_controller_preset_guids_are_normalized():
    config = Config(controller_presets={"ABCDEF": "playstation"})

    assert config.controller_presets == {"abcdef": "playstation"}


def test_invalid_controller_preset_update_is_ignored():
    store = ConfigStore(Config(controller_presets={"guid": "xbox"}))

    changed = store.update({"controller_presets": ["not", "a", "mapping"]})

    assert changed == {}
    assert store.config.controller_presets == {"guid": "xbox"}


def test_config_search_and_save_stays_with_loaded_file(tmp_path, monkeypatch):
    import json

    import lib.config as module

    app = tmp_path / "app"
    user = tmp_path / "user"
    (app / "config").mkdir(parents=True)
    user.mkdir()
    monkeypatch.setattr(module, "application_dir", lambda: app)
    monkeypatch.setattr(module, "_config_dir", lambda: user)
    (user / "config.json").write_text('{"transport_spec": "usb:1"}')
    config = Config.load()
    assert config.transport_spec == "usb:1"
    local = app / "config" / "config.json"
    local.write_text('{"transport_spec": "usb:2"}')
    config.save()
    assert json.loads(local.read_text())["transport_spec"] == "usb:2"
    assert Config.load().transport_spec == "usb:2"
    assert (
        module.resolve_config_file("pro_controller.json")
        == user / "pro_controller.json"
    )
    device = app / "config" / "pro_controller.json"
    device.write_text("{}")
    assert module.resolve_config_file("pro_controller.json") == device


def test_defaults_and_explicit_headless_config(tmp_path, monkeypatch):
    import lib.config as module

    path = tmp_path / "config.json"
    monkeypatch.setattr(module, "config_path", lambda: path)
    config = Config.load()
    assert config.transport_spec == "usb:0"
    assert config.input_specs == ["controller"]
    assert (config.web_host, config.web_port) == ("127.0.0.1", 9127)
    assert config.web_enabled
    path.write_text('{"web_host": null, "web_port": null, "nolog": true}')
    config = Config.load()
    assert not config.web_enabled
    assert config.nolog
    config.save()
    assert Config.load().web_host is None


def test_compiled_application_dir_uses_executable(tmp_path, monkeypatch):
    import lib.config as module

    monkeypatch.setattr(module, "__compiled__", object(), raising=False)
    monkeypatch.setattr(module.sys, "argv", [str(tmp_path / "ounce.exe")])
    assert module.application_dir() == tmp_path


def test_alternative_presets_support_builtins_and_custom_writes(tmp_path, monkeypatch):
    from lib.input import presets

    monkeypatch.setattr(presets, "PRESETS_DIR", tmp_path / "custom")
    assert presets.load_preset("xbox").name
    contents = presets.read_preset_text("xbox")
    presets.save_preset_text("my-pad", contents)
    assert presets.load_preset("my-pad").name
