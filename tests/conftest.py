from pathlib import Path

import pytest

import lib.config as config_module

REPO_CONFIG_PATH = (Path(__file__).resolve().parent.parent / "config" / "config.json").resolve()


@pytest.fixture(autouse=True)
def _forbid_writing_repo_config(monkeypatch):
    """Prevent any test from accidentally overwriting the repository's config/config.json."""
    original_save = config_module.Config.save

    def guarded_save(self):
        target = (getattr(self, "_path", None) or config_module.config_path()).resolve()
        if target == REPO_CONFIG_PATH:
            raise AssertionError(
                f"Test attempted to overwrite repository config at {target}; "
                "monkeypatch lib.config.config_path to a tmp_path instead."
            )
        return original_save(self)

    monkeypatch.setattr(config_module.Config, "save", guarded_save)
