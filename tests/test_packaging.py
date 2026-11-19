# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Gabriel Marti
"""Tests de los ficheros de empaquetado (packaging/)."""

from __future__ import annotations

import importlib.util
import re
import tomllib
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


def _requirement_name(spec: str) -> str:
    return re.split(r"[<>=!~ ;\[]", spec.strip(), maxsplit=1)[0].lower().replace("_", "-")


def _release_in() -> dict[str, str]:
    """Requisitos directos de la release (nombre -> especificación) de requirements-release.in."""
    result: dict[str, str] = {}
    for line in (ROOT / "packaging" / "requirements-release.in").read_text("utf-8").splitlines():
        spec = line.split("#", 1)[0].strip()
        if spec:
            result[_requirement_name(spec)] = spec.replace(" ", "")
    return result


def test_release_requirements_match_pyproject_ranges() -> None:
    """requirements-release.in recoge las dependencias, dev y build de pyproject con sus rangos."""
    data = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))
    project = data["project"]
    declared = [
        *project["dependencies"],
        *project["optional-dependencies"]["dev"],
        *project["optional-dependencies"]["build"],
    ]
    release = _release_in()
    for spec in declared:
        clean = spec.split("#", 1)[0].strip().replace(" ", "")
        assert release.get(_requirement_name(clean)) == clean, clean


def test_release_requirements_are_pinned_with_hashes() -> None:
    """Cada paquete del fichero compilado tiene versión exacta y al menos un hash SHA-256."""
    text = (ROOT / "packaging" / "requirements-release.txt").read_text("utf-8")
    blocks = re.findall(
        r"^([A-Za-z0-9_.\-]+)==([^\s\\]+)((?:\s*\\\s*--hash=sha256:[0-9a-f]{64})+)", text, re.M
    )
    pinned = {name.lower().replace("_", "-") for name, _version, _hashes in blocks}
    requirement_lines = [line for line in text.splitlines() if re.match(r"^[A-Za-z0-9]", line)]
    assert len(requirement_lines) == len(blocks), "hay requisitos sin versión exacta o sin hash"
    assert set(_release_in()) <= pinned


def test_release_workflow_uses_pinned_requirements_and_inno_hash() -> None:
    text = (ROOT / ".github" / "workflows" / "release.yml").read_text("utf-8")
    assert "--require-hashes" in text
    assert "packaging/requirements-release.txt" in text
    assert 'pip install -e ".[' not in text
    assert "choco install" not in text
    assert re.search(r"INNO_SHA256: [0-9a-f]{64}\n", text)
    assert "Get-FileHash" in text
