# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Gabriel Marti
"""Tests de los ficheros de empaquetado (packaging/)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from agyswitcher import __version__

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str) -> ModuleType:
    path = ROOT / "packaging" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"packaging_{name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_version_info_contains_four_part_version_and_license() -> None:
    text = _load("make_version_info").render(45)
    major, minor, patch = (int(p) for p in __version__.split(".")[:3])
    assert f"filevers=({major}, {minor}, {patch}, 45)" in text
    assert f"StringStruct('FileVersion', '{major}.{minor}.{patch}.45')" in text
    assert "(compilación 45)" in text
    assert "GPL-3.0-or-later" in text
    assert "StringStruct('OriginalFilename', 'agyswitcher.exe')" in text


def test_installer_script_is_per_user_and_manages_path() -> None:
    iss = (ROOT / "packaging" / "agyswitcher.iss").read_text(encoding="utf-8-sig")
    assert "PrivilegesRequired=lowest" in iss
    assert "ChangesEnvironment=yes" in iss
    assert "LicenseFile={#RepoRoot}\\LICENSE" in iss
    assert "RemoveFromPath" in iss
    assert "compiler:Languages\\Spanish.isl" in iss


def test_build_script_restores_build_number_and_checks_utf8() -> None:
    ps1 = (ROOT / "packaging" / "build.ps1").read_text(encoding="utf-8")
    assert "finally" in ps1 and "$OriginalBuild" in ps1
    assert '"X utf8"' in ps1
    assert "SHA256SUMS.txt" in ps1


def test_all_code_files_have_spdx_header() -> None:
    """Todo fichero de código del repositorio declara la licencia GPL-3.0-or-later."""
    skip = {".venv", "build", "dist", ".git", ".mypy_cache", ".ruff_cache", ".pytest_cache"}
    missing = []
    for path in ROOT.rglob("*"):
        if path.suffix not in {".py", ".ps1", ".iss"} or skip & set(path.relative_to(ROOT).parts):
            continue
        head = path.read_bytes().decode("utf-8-sig")[:300]
        if "SPDX-License-Identifier: GPL-3.0-or-later" not in head:
            missing.append(path.relative_to(ROOT).as_posix())
    assert missing == []


def test_source_build_number_is_none() -> None:
    """En el código fuente nunca debe quedar un número de compilación fijado."""
    from agyswitcher._build import BUILD_NUMBER

    assert BUILD_NUMBER is None
