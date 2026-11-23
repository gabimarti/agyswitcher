# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Gabriel Marti
"""Tests de continuidad del proyecto entre cuentas y agentes (project.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agyswitcher.models import AccountQuotaInfo
from agyswitcher.project import (
    DEFAULT_RESUME_PROMPT,
    DEFAULT_SAVE_PROMPT,
    MEMORY_MARK,
    POINTER_MARK,
    PROJECT_CONFIG_NAME,
    ProjectError,
    load_handoff_prompts,
    low_quota_percent,
    parse_agents,
    resolve_low_quota_threshold,
    scaffold_project,
)


def test_scaffold_creates_common_files_and_selected_agents(tmp_path: Path) -> None:
    result = scaffold_project(
        tmp_path, ("gemini", "claude", "copilot", "cursor"), project_name="Demo"
    )

    expected = {
        "AGENTS.md",
        "dev_mem/ESTADO.md",
        "dev_mem/TODO.md",
        PROJECT_CONFIG_NAME,
        "GEMINI.md",
        "CLAUDE.md",
        ".github/copilot-instructions.md",
        ".cursor/rules/agents.mdc",
    }
    assert {p.relative_to(tmp_path).as_posix() for p in result.created} == expected
    assert result.skipped == []
    agents_md = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert "# AGENTS.md — Demo" in agents_md
    assert "dev_mem/ESTADO.md" in agents_md
    assert "@AGENTS.md" in (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert "alwaysApply: true" in (tmp_path / ".cursor/rules/agents.mdc").read_text(
        encoding="utf-8"
    )
    # Saltos de línea LF también en Windows.
    assert b"\r\n" not in (tmp_path / "AGENTS.md").read_bytes()


def test_scaffold_never_overwrites(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("mis reglas", encoding="utf-8")

    result = scaffold_project(tmp_path, ("gemini",))

    assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8") == "mis reglas"
    assert tmp_path / "AGENTS.md" in result.skipped
    assert (tmp_path / "GEMINI.md").exists()


def test_scaffold_dry_run_writes_nothing(tmp_path: Path) -> None:
    result = scaffold_project(tmp_path, ("claude",), dry_run=True)

    assert len(result.created) == 5
    assert list(tmp_path.iterdir()) == []


def test_scaffold_rejects_missing_dir(tmp_path: Path) -> None:
    with pytest.raises(ProjectError, match="no existe"):
        scaffold_project(tmp_path / "nada")


def test_parse_agents() -> None:
    assert parse_agents("Gemini, claude,gemini") == ("gemini", "claude")
    with pytest.raises(ProjectError, match="chatgpt"):
        parse_agents("gemini,chatgpt")


def test_handoff_prompts_default_without_config(tmp_path: Path) -> None:
    prompts = load_handoff_prompts(tmp_path)
    assert prompts.save == DEFAULT_SAVE_PROMPT
    assert prompts.resume == DEFAULT_RESUME_PROMPT
    assert prompts.source is None


def test_handoff_prompts_from_scaffolded_config_found_upwards(tmp_path: Path) -> None:
    scaffold_project(tmp_path, ())
    sub = tmp_path / "src" / "paquete"
    sub.mkdir(parents=True)

    prompts = load_handoff_prompts(sub)

    assert prompts.source == (tmp_path / PROJECT_CONFIG_NAME).resolve()
    assert prompts.save == DEFAULT_SAVE_PROMPT
    assert prompts.resume == DEFAULT_RESUME_PROMPT


def test_handoff_prompts_custom_and_partial(tmp_path: Path) -> None:
    (tmp_path / PROJECT_CONFIG_NAME).write_text(
        '[handoff]\nsave_prompt = "Guarda en NOTAS.md"\n', encoding="utf-8"
    )
    prompts = load_handoff_prompts(tmp_path)
    assert prompts.save == "Guarda en NOTAS.md"
    assert prompts.resume == DEFAULT_RESUME_PROMPT


def test_handoff_prompts_invalid_toml_falls_back(tmp_path: Path) -> None:
    (tmp_path / PROJECT_CONFIG_NAME).write_text("[handoff\nroto", encoding="utf-8")
    prompts = load_handoff_prompts(tmp_path)
    assert prompts.save == DEFAULT_SAVE_PROMPT
    assert prompts.error


def test_low_quota_percent_thresholds() -> None:
    info = AccountQuotaInfo(gemini_percent=12, external_percent=40)
    assert low_quota_percent(info, "gemini") == 12
    assert low_quota_percent(info, "external") is None
    assert low_quota_percent(AccountQuotaInfo(gemini_percent=0), "gemini") is None
    assert low_quota_percent(AccountQuotaInfo(gemini_percent=15), "gemini") == 15
    assert low_quota_percent(AccountQuotaInfo(gemini_percent=20), "gemini") == 20
    assert low_quota_percent(AccountQuotaInfo(gemini_percent=21), "gemini") is None
    assert low_quota_percent(None, "gemini") is None
    assert low_quota_percent(AccountQuotaInfo(), "gemini") is None


# ---------------------------------------------------------------------------
# init --merge: proyectos que ya tienen sus propios ficheros
# ---------------------------------------------------------------------------


def test_merge_appends_memory_section_to_existing_agents_md(tmp_path: Path) -> None:
    original = "# Mis reglas\r\n\r\n- Usa tabs.\r\n"
    (tmp_path / "AGENTS.md").write_bytes(original.encode("utf-8"))

    result = scaffold_project(tmp_path, ("gemini",), merge=True)

    assert tmp_path / "AGENTS.md" in result.merged
    data = (tmp_path / "AGENTS.md").read_bytes().decode("utf-8")
    assert data.startswith(original)  # lo existente no se toca
    assert MEMORY_MARK in data
    assert "dev_mem/ESTADO.md" in data
    assert "\n" not in data.replace("\r\n", "")  # se respetan los CRLF
    assert "\r\n\r\n" + MEMORY_MARK in data  # una línea en blanco de separación

    again = scaffold_project(tmp_path, ("gemini",), merge=True)
    assert tmp_path / "AGENTS.md" in again.skipped
    assert (tmp_path / "AGENTS.md").read_bytes().decode("utf-8").count(MEMORY_MARK) == 1


def test_merge_recognizes_section_from_previous_init(tmp_path: Path) -> None:
    """Un AGENTS.md creado por una versión anterior (sin marca) no recibe la sección dos veces."""
    (tmp_path / "AGENTS.md").write_text(
        "# AGENTS.md\n\n## Memoria del proyecto (`dev_mem/`)\n\n- lee ESTADO\n", encoding="utf-8"
    )
    result = scaffold_project(tmp_path, (), merge=True)
    assert tmp_path / "AGENTS.md" in result.skipped
    assert MEMORY_MARK not in (tmp_path / "AGENTS.md").read_text(encoding="utf-8")


def test_merge_adds_pointer_to_agent_files_without_it(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").write_text("# Reglas propias de Claude", encoding="utf-8")
    (tmp_path / "GEMINI.md").write_text("Sigue AGENTS.md siempre.\n", encoding="utf-8")
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "copilot-instructions.md").write_text("Copilot\n", encoding="utf-8")

    result = scaffold_project(tmp_path, ("gemini", "claude", "copilot"), merge=True)

    claude = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert claude.startswith("# Reglas propias de Claude\n\n" + POINTER_MARK)
    assert "\n@AGENTS.md\n" in claude  # importación que carga AGENTS.md en Claude Code
    assert tmp_path / "CLAUDE.md" in result.merged
    assert tmp_path / "GEMINI.md" in result.skipped  # ya remitía a AGENTS.md
    copilot = (tmp_path / ".github" / "copilot-instructions.md").read_text(encoding="utf-8")
    assert "(../AGENTS.md)" in copilot


def test_merge_dry_run_writes_nothing(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("# Reglas\n", encoding="utf-8")
    result = scaffold_project(tmp_path, ("claude",), merge=True, dry_run=True)
    assert tmp_path / "AGENTS.md" in result.merged
    assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8") == "# Reglas\n"
    assert not (tmp_path / "CLAUDE.md").exists()


def test_merge_without_flag_never_modifies(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("# Reglas\n", encoding="utf-8")
    result = scaffold_project(tmp_path, ())
    assert tmp_path / "AGENTS.md" in result.skipped
    assert result.merged == []


def test_merge_refuses_non_utf8(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_bytes("# Reglas año\n".encode("cp1252"))
    with pytest.raises(ProjectError, match="UTF-8"):
        scaffold_project(tmp_path, (), merge=True)


def test_low_quota_threshold_default_global_and_project(tmp_path: Path) -> None:
    """Prioridad: proyecto > global > por defecto (20)."""
    sub = tmp_path / "src"
    sub.mkdir()
    default = resolve_low_quota_threshold(sub, None)
    assert (default.percent, default.source) == (20, "por defecto")
    assert resolve_low_quota_threshold(sub, 30).percent == 30

    (tmp_path / ".agyswitcher.toml").write_text("[quota]\nlow_percent = 8\n", encoding="utf-8")
    project = resolve_low_quota_threshold(sub, 30)
    assert (project.percent, project.source) == (8, "proyecto")
    assert project.project_file == tmp_path / ".agyswitcher.toml"


def test_low_quota_threshold_project_without_quota_uses_global(tmp_path: Path) -> None:
    (tmp_path / ".agyswitcher.toml").write_text("[handoff]\n", encoding="utf-8")
    threshold = resolve_low_quota_threshold(tmp_path, 25)
    assert (threshold.percent, threshold.source, threshold.error) == (25, "global", None)


def test_low_quota_threshold_invalid_project_value_is_reported(tmp_path: Path) -> None:
    (tmp_path / ".agyswitcher.toml").write_text("[quota]\nlow_percent = 0\n", encoding="utf-8")
    threshold = resolve_low_quota_threshold(tmp_path, None)
    assert threshold.percent == 20
    assert threshold.error is not None and "low_percent" in threshold.error


def test_low_quota_threshold_unreadable_project_file(tmp_path: Path) -> None:
    (tmp_path / ".agyswitcher.toml").write_text("[quota\n", encoding="utf-8")
    threshold = resolve_low_quota_threshold(tmp_path, 40)
    assert threshold.percent == 40
    assert threshold.error


def test_project_toml_template_documents_quota(tmp_path: Path) -> None:
    import tomllib

    from agyswitcher.project import _project_toml

    text = _project_toml()
    assert "# [quota]" in text
    assert "# low_percent = 20" in text
    assert "quota" not in tomllib.loads(text)  # comentado: no cambia nada por defecto


def test_handoff_file_path_location(tmp_path: Path) -> None:
    from agyswitcher.project import handoff_file_path

    # Sin dev_mem/ -> en la raíz
    assert handoff_file_path(tmp_path) == tmp_path / "HANDOFF.md"

    # Con dev_mem/ -> dentro de dev_mem/
    dev_mem = tmp_path / "dev_mem"
    dev_mem.mkdir()
    assert handoff_file_path(tmp_path) == dev_mem / "HANDOFF.md"


def test_write_handoff_file_creates_and_overwrites(tmp_path: Path) -> None:
    from agyswitcher.project import write_handoff_file

    dev_mem = tmp_path / "dev_mem"
    dev_mem.mkdir()

    path = write_handoff_file(
        tmp_path,
        account="mi-cuenta",
        pool="gemini",
        notes="Avanzado paso 1",
    )
    assert path == dev_mem / "HANDOFF.md"
    assert path.is_file()

    content = path.read_text(encoding="utf-8")
    assert "# HANDOFF — Traspaso de Sesión" in content
    assert "mi-cuenta" in content
    assert "gemini" in content
    assert "Avanzado paso 1" in content
    assert "Continuamos el trabajo en una nueva sesión" in content
