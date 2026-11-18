# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Gabriel Marti
"""Tests de versión (version.py) y carpeta de datos configurable (AGYSWITCHER_HOME)."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from agyswitcher import __version__
from agyswitcher.config import APP_HOME_ENV, app_home_dir, default_config_path
from agyswitcher.state import default_state_path
from agyswitcher.version import full_version, semver_parts, windows_file_version


def test_semver_parts() -> None:
    assert semver_parts("1.2.3") == (1, 2, 3)
    assert semver_parts("0.9.0rc1") == (0, 9, 0)
    with pytest.raises(ValueError):
        semver_parts("uno.dos")


def test_current_version_is_semver() -> None:
    assert len(semver_parts(__version__)) == 3


def test_full_version_with_and_without_build() -> None:
    assert full_version("0.9.0", None) == "0.9.0"
    assert full_version("0.9.0", 45) == "0.9.0 (compilación 45)"


def test_windows_file_version() -> None:
    assert windows_file_version("1.2.3", 45) == (1, 2, 3, 45)
    assert windows_file_version("1.2.3", None) == (1, 2, 3, 0)


def test_pyproject_reads_version_from_package() -> None:
    """La versión tiene una única fuente: __init__.py (pyproject la declara dinámica)."""
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    assert "version" not in data["project"]
    assert "version" in data["project"]["dynamic"]
    assert data["tool"]["hatch"]["version"]["path"] == "src/agyswitcher/__init__.py"


def test_license_is_gpl3_or_later_everywhere() -> None:
    """La licencia acordada (GPL-3.0-or-later) figura en pyproject, LICENSE y README."""
    root = Path(__file__).resolve().parents[1]
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["license"] == "GPL-3.0-or-later"
    assert data["project"]["license-files"] == ["LICENSE"]
    license_text = (root / "LICENSE").read_text(encoding="utf-8")
    assert "GNU GENERAL PUBLIC LICENSE" in license_text
    assert "Version 3, 29 June 2007" in license_text
    readme = (root / "README.md").read_text(encoding="utf-8")
    assert "GPL-3.0-or-later" in readme
    assert "licencia MIT" not in readme


def test_app_home_defaults_to_user_folder() -> None:
    assert app_home_dir() == Path.home() / ".agyswitcher"
    assert default_config_path() == Path.home() / ".agyswitcher" / "config.json"


def test_app_home_env_overrides_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(APP_HOME_ENV, str(tmp_path / "demo"))
    assert app_home_dir() == (tmp_path / "demo").resolve()
    assert default_config_path() == (tmp_path / "demo" / "config.json").resolve()
    assert default_state_path() == (tmp_path / "demo" / "state.json").resolve()


def test_app_home_env_blank_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(APP_HOME_ENV, "   ")
    assert app_home_dir() == Path.home() / ".agyswitcher"
