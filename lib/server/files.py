"""Validate document names and safely read, atomically write, or delete JSON macro and preset files."""

from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path

NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _-]{0,63}$")
MAX_NAME_LEN = 64


class UnsafeNameError(ValueError):
    """A document name failed validation."""


class DocError(ValueError):
    """A document could not be read / written."""


def validate_name(name: str) -> str:
    """Validate and normalise a document name (file stem)."""
    name = (name or "").strip()
    if not name:
        raise UnsafeNameError("name must not be empty")
    if len(name) > MAX_NAME_LEN:
        raise UnsafeNameError(f"name must be at most {MAX_NAME_LEN} characters")
    if not NAME_PATTERN.match(name):
        raise UnsafeNameError(
            "name may only contain letters, digits, spaces, '_' and '-', "
            "and must start with a letter or digit"
        )
    return name


def doc_path(directory: Path, name: str) -> Path:
    """Resolve ``name`` to a path inside ``directory`` or raise.

    The regex guarantees no separators, so no containment check is needed
    beyond it; the double check below is defence in depth.
    """
    name = validate_name(name)
    path = (directory / f"{name}.json").resolve()
    if path.parent != directory.resolve():
        raise UnsafeNameError(f"name resolves outside {directory}")
    return path


class JsonDocStore:
    """Thread-safe reader/writer for JSON documents in one directory."""

    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self._lock = threading.Lock()

    def list_names(self) -> list[str]:
        """Sorted document names (file stems) in the directory."""
        if not self.directory.exists():
            return []
        return sorted(
            p.stem for p in self.directory.glob("*.json") if p.is_file()
        )

    def read_text(self, name: str) -> str:
        """Return the raw file text (formatting preserved for the editor)."""
        path = doc_path(self.directory, name)
        with self._lock:
            if not path.is_file():
                raise DocError(f"'{name}' does not exist")
            return path.read_text(encoding="utf-8")

    def write_text(self, name: str, contents: str) -> None:
        """Atomically write raw text. Contents must already be validated."""
        validate_name(name)
        with self._lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            path = self.directory / f"{name}.json"
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(contents, encoding="utf-8")
            os.replace(tmp, path)

    def delete(self, name: str) -> None:
        path = doc_path(self.directory, name)
        with self._lock:
            if not path.is_file():
                raise DocError(f"'{name}' does not exist")
            path.unlink()

    def rename(self, name: str, new_name: str) -> str:
        source = doc_path(self.directory, name)
        new_name = validate_name(new_name)
        doc_path(self.directory, new_name)
        target = self.directory / f"{new_name}.json"
        with self._lock:
            if not source.is_file():
                raise DocError(f"'{name}' does not exist")
            if name != new_name:
                os.replace(source, target)
            return new_name

    def exists(self, name: str) -> bool:
        try:
            return doc_path(self.directory, name).is_file()
        except UnsafeNameError:
            return False


def parse_json_text(text: str, label: str = "document") -> tuple[dict | None, dict | None]:
    """Parse JSON text into ``(value, None)`` or ``(None, error_info)``.

    ``error_info`` carries a human ``detail`` plus 1-based ``line``/``col``
    (when available) so the editor can place a marker.
    """
    try:
        value = json.loads(text)
    except json.JSONDecodeError as e:
        info = {
            "detail": e.msg,
            "line": e.lineno,
            "col": e.colno,
        }
        return None, info
    if not isinstance(value, dict):
        return None, {"detail": f"{label} must be a JSON object"}
    return value, None
