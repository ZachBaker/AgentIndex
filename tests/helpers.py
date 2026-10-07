"""Shared fixtures: throwaway projects in temporary directories."""

from __future__ import annotations

import os
import shutil
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from unittest import mock

from agentindex import KnowledgeIndex, load_config


def make_project(files: dict[str, str], root: Path | None = None) -> Path:
    """Write ``{relative path: text}`` (dedented) under ``root`` or a new temp dir."""
    root = Path(tempfile.mkdtemp(prefix="agentindex-test-")) if root is None else root
    for rel, text in files.items():
        write_file(root / rel, text)
    return root.resolve()


def write_file(path: Path, text: str) -> None:
    """Write a file and make sure its mtime moves forward, so sync sees the change."""
    previous = path.stat().st_mtime_ns if path.exists() else 0
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text).lstrip("\n"), encoding="utf-8")
    stamp = max(time.time_ns(), previous + 1_000_000_000)
    os.utime(path, ns=(stamp, stamp))


class ProjectTestCase(unittest.TestCase):
    """A test with a temporary project at ``self.root`` built from ``files``."""

    files: dict[str, str] = {}

    def setUp(self) -> None:
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        for name in ("AGENTINDEX_ROOT", "AGENTINDEX_DB"):
            os.environ.pop(name, None)
        self.root = make_project(self.files)
        self.addCleanup(shutil.rmtree, self.root, True)

    def write(self, rel: str, text: str) -> Path:
        path = self.root / rel
        write_file(path, text)
        return path

    def open_index(self, **kwargs) -> KnowledgeIndex:
        index = KnowledgeIndex(load_config(self.root), **kwargs)
        self.addCleanup(index.close)
        return index
