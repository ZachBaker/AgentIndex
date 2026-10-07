"""Locate the project root and load the optional ``.agentindex.json`` config."""

from __future__ import annotations

import json
import os
import posixpath
from dataclasses import dataclass, field
from pathlib import Path

from .errors import ConfigError

CONFIG_FILE = ".agentindex.json"
DEFAULT_SOURCES = ("knowledge",)
DEFAULT_DB = ".agentindex/index.db"
DOC_SUFFIXES = (".md", ".markdown", ".mdx")
_KEYS = ("sources", "db", "exclude")


@dataclass
class Config:
    root: Path
    sources: list[str] = field(default_factory=lambda: list(DEFAULT_SOURCES))
    db: str = DEFAULT_DB
    exclude: list[str] = field(default_factory=list)
    config_file: Path | None = None

    @property
    def db_path(self) -> str:
        """Absolute database path (or ``:memory:``)."""
        if self.db == ":memory:":
            return self.db
        path = Path(self.db).expanduser()
        return str(path if path.is_absolute() else self.root / path)


def find_root(start: Path) -> tuple[Path, Path | None]:
    """Nearest ancestor holding ``.agentindex.json``, else the git root, else ``start``."""
    start = start.resolve()
    chain = [start, *start.parents]
    for directory in chain:
        if (directory / CONFIG_FILE).is_file():
            return directory, directory / CONFIG_FILE
    for directory in chain:
        if (directory / ".git").exists():
            return directory, None
    return start, None


def load_config(root: str | os.PathLike | None = None, db: str | None = None) -> Config:
    """Build the config from (in order of precedence) arguments, env vars, the file, defaults."""
    root = root or os.environ.get("AGENTINDEX_ROOT")
    if root:
        root_path = Path(root).expanduser().resolve()
        if not root_path.is_dir():
            raise ConfigError(f"root is not a directory: {root_path}")
        config_file: Path | None = root_path / CONFIG_FILE
        if not config_file.is_file():
            config_file = None
    else:
        root_path, config_file = find_root(Path.cwd())
    config = Config(root=root_path, config_file=config_file)
    if config_file is not None:
        _apply_file(config, config_file)
    db = db or os.environ.get("AGENTINDEX_DB")
    if db:
        config.db = db
    return config


def _apply_file(config: Config, path: Path) -> None:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))  # tolerate a BOM
    except (OSError, ValueError) as exc:
        raise ConfigError(f"{path}: {exc}") from None
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: expected a JSON object")
    unknown = sorted(k for k in data if k not in _KEYS and not k.startswith("//"))
    if unknown:
        raise ConfigError(
            f"{path}: unknown key(s) {', '.join(unknown)} (valid keys: {', '.join(_KEYS)})"
        )
    if "sources" in data:
        config.sources = [
            posixpath.normpath(s.replace("\\", "/"))
            for s in _string_list(data["sources"], "sources", path)
        ]
        if not config.sources:
            raise ConfigError(f"{path}: 'sources' must list at least one directory")
        for source in config.sources:
            resolved = (config.root / source).resolve()
            if resolved != config.root and config.root not in resolved.parents:
                raise ConfigError(f"{path}: source {source!r} is outside the project root")
    if "exclude" in data:
        config.exclude = _string_list(data["exclude"], "exclude", path)
    if "db" in data:
        if not isinstance(data["db"], str) or not data["db"].strip():
            raise ConfigError(f"{path}: 'db' must be a non-empty string")
        config.db = data["db"]


def _string_list(value: object, key: str, path: Path) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
        raise ConfigError(f"{path}: '{key}' must be a list of non-empty strings")
    return [v.strip() for v in value]
