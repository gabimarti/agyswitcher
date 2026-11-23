# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Gabriel Marti
"""Tests unitarios del módulo runner y sanitización."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agyswitcher.runner import (
    AGY_PATH_ENV,
    AGY_SOURCE_ENV,
    AGY_SOURCE_INSTALL,
    AGY_SOURCE_PATH,
    AgyNotFoundError,
    RunnerError,
    check_batch_args,
    find_agy_executable,
    find_running_agy_processes,
    kill_process_tree,
    locate_agy,
    run_agy_process,
    run_captured,
    sanitize_line,
    system_tool,
)


def _make_exe(folder: Path, name: str = "agy.exe") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    exe = folder / name
    exe.write_bytes(b"MZ")
    if os.name != "nt":
        exe.chmod(0o755)
    return exe


@pytest.fixture
def agy_name() -> str:
    return "agy.exe" if os.name == "nt" else "agy"


def test_find_agy_executable_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, agy_name: str
) -> None:
    """Devuelve la ruta si agy está en una carpeta absoluta del PATH."""
    exe = _make_exe(tmp_path / "bin", agy_name)
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))

    location = locate_agy()
    assert find_agy_executable() == exe.resolve()
    assert location.source == AGY_SOURCE_PATH
    assert location.warning is None


def test_find_agy_executable_not_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Lanza AgyNotFoundError si agy no se encuentra en el PATH."""
    monkeypatch.setenv("PATH", str(tmp_path / "vacio"))

    with pytest.raises(AgyNotFoundError) as exc_info:
        find_agy_executable()

    assert "No se encontró agy.exe en el PATH" in str(exc_info.value)
    assert AGY_PATH_ENV in str(exc_info.value)


def test_find_agy_ignores_current_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, agy_name: str
) -> None:
    """Un agy (o agy.cmd) en la carpeta actual nunca se usa, ni con '.' en el PATH (SEC3-01)."""
    project = tmp_path / "proyecto"
    _make_exe(project, agy_name)
    _make_exe(project, "agy.cmd")
    _make_exe(project, "agy.bat")
    monkeypatch.chdir(project)
    monkeypatch.setenv("PATH", os.pathsep.join([".", "", "bin", str(tmp_path / "vacio")]))

    with pytest.raises(AgyNotFoundError):
        find_agy_executable()


def test_find_agy_prefers_real_agy_over_project_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, agy_name: str
) -> None:
    """Con un agy plantado en el proyecto, se elige el del PATH."""
    project = tmp_path / "proyecto"
    _make_exe(project, agy_name)
    real = _make_exe(tmp_path / "agy" / "bin", agy_name)
    monkeypatch.chdir(project)
    monkeypatch.setenv("PATH", os.pathsep.join([".", str(tmp_path / "agy" / "bin")]))

    assert find_agy_executable() == real.resolve()


def test_find_agy_ignores_batch_scripts_in_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """En el PATH solo vale agy.exe: un agy.cmd o agy.bat no se elige."""
    _make_exe(tmp_path / "bin", "agy.cmd")
    _make_exe(tmp_path / "bin", "agy.bat")
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))

    with pytest.raises(AgyNotFoundError):
        find_agy_executable()


def test_find_agy_uses_env_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, agy_name: str
) -> None:
    """AGYSWITCHER_AGY con ruta absoluta existente tiene prioridad sobre el PATH."""
    custom = _make_exe(tmp_path / "otra", "agy.cmd")
    _make_exe(tmp_path / "bin", agy_name)
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))
    monkeypatch.setenv(AGY_PATH_ENV, str(custom))

    location = locate_agy()
    assert location.path == custom.resolve()
    assert location.source == AGY_SOURCE_ENV
    assert location.warning is None


@pytest.mark.parametrize("value", ["agy.exe", ".\\agy.exe", "no/existe/agy.exe"])
def test_find_agy_env_variable_invalid_falls_back_with_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, agy_name: str, value: str
) -> None:
    """Una AGYSWITCHER_AGY relativa o inexistente se ignora con aviso y se busca en el PATH."""
    monkeypatch.chdir(tmp_path)
    _make_exe(tmp_path, "agy.exe")  # Aunque exista en la carpeta actual, no se usa.
    real = _make_exe(tmp_path / "bin", agy_name)
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))
    monkeypatch.setenv(AGY_PATH_ENV, value)

    location = locate_agy()
    assert location.path == real.resolve()
    assert location.warning is not None
    assert AGY_PATH_ENV in location.warning


def test_find_agy_env_variable_missing_file_and_no_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Variable desfasada y sin agy en el PATH: no encontrado."""
    monkeypatch.setenv("PATH", str(tmp_path / "vacio"))
    monkeypatch.setenv(AGY_PATH_ENV, str(tmp_path / "borrado" / "agy.exe"))

    with pytest.raises(AgyNotFoundError):
        find_agy_executable()


@pytest.mark.skipif(os.name != "nt", reason="Ruta de instalación de agy en Windows")
def test_find_agy_falls_back_to_install_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sin agy en el PATH, se usa la ruta de instalación oficial de agy si existe."""
    local = tmp_path / "Local"
    installed = _make_exe(local / "agy" / "bin")
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("PATH", str(tmp_path / "vacio"))

    location = locate_agy()
    assert location.path == installed.resolve()
    assert location.source == AGY_SOURCE_INSTALL


@pytest.mark.parametrize("arg", ["a&calc", "x|y", "50%", 'say "hi"', "a^b", "a<b", "l1\nl2"])
def test_check_batch_args_rejects_cmd_metacharacters(arg: str) -> None:
    """Con un .cmd/.bat, los metacaracteres de cmd.exe se rechazan."""
    with pytest.raises(RunnerError):
        check_batch_args(Path("agy.cmd"), ["--prompt", arg])
    with pytest.raises(RunnerError):
        check_batch_args("C:/x/AGY.BAT", [arg])


def test_check_batch_args_allows_exe_and_safe_args() -> None:
    """Con un .exe no se comprueba nada; con un .cmd se aceptan argumentos normales."""
    check_batch_args(Path("agy.exe"), ["a&b", "50%"])
    check_batch_args(Path("agy.cmd"), ["--model", "gemini-3.8-flash-high", "-p", "/usage"])


def test_run_agy_process_rejects_unsafe_args_for_batch(tmp_path: Path) -> None:
    """run_agy_process no lanza un .cmd con argumentos peligrosos."""
    script = _make_exe(tmp_path, "agy.cmd")
    with pytest.raises(RunnerError):
        run_agy_process(["& calc"], executable_path=script, echo_output=False)


def test_run_captured_rejects_unsafe_args_for_batch(tmp_path: Path) -> None:
    """run_captured tampoco."""
    script = _make_exe(tmp_path, "agy.cmd")
    with pytest.raises(RunnerError):
        run_captured([str(script), "x|y"], timeout=5)


@pytest.mark.skipif(os.name != "nt", reason="Utilidades de System32")
def test_system_tool_uses_system32(monkeypatch: pytest.MonkeyPatch) -> None:
    """tasklist/taskkill se invocan por ruta absoluta en System32."""
    monkeypatch.setenv("SYSTEMROOT", "C:\\Windows")
    assert system_tool("tasklist.exe") == str(Path("C:\\Windows") / "System32" / "tasklist.exe")


def test_sanitize_bearer_token() -> None:
    """Redacta tokens que siguen al prefijo Bearer."""
    raw = "Request header: Authorization: Bearer ya29.FAKE_token_only_for_tests"
    sanitized = sanitize_line(raw)
    assert "ya29.FAKE_token_only_for_tests" not in sanitized
    assert "[REDACTED]" in sanitized


def test_sanitize_authorization_header() -> None:
    """Redacta cabeceras de autorización generales."""
    raw = "authorization: Basic dXNlcjpwYXNzd29yZA=="
    sanitized = sanitize_line(raw)
    assert "dXNlcjpwYXNzd29yZA==" not in sanitized
    assert "authorization: [REDACTED]" in sanitized


def test_sanitize_token_parameters() -> None:
    """Redacta access_token, refresh_token y token asignados con '=' o ':'."""
    samples = [
        ('refresh_token="1//04abc_secret_token"', 'refresh_token="[REDACTED]"'),
        ("access_token: secret_access_val", "access_token: [REDACTED]"),
        ("token=xyz987654321", "token=[REDACTED]"),
        ("api_key='my-super-secret-key'", "api_key='[REDACTED]'"),
    ]
    for raw, expected in samples:
        sanitized = sanitize_line(raw)
        assert sanitized == expected


def test_sanitize_cookie() -> None:
    """Redacta información de cookies."""
    raw = "Cookie: session_id=123456789; secure=true; user_id=test"
    sanitized = sanitize_line(raw)
    assert "123456789" not in sanitized
    assert "Cookie: [REDACTED]" in sanitized


def test_sanitize_url_query_tokens() -> None:
    """Redacta parámetros de tokens en URLs."""
    raw = "GET /api/v1?token=super_secret_param&query=python"
    sanitized = sanitize_line(raw)
    assert "super_secret_param" not in sanitized
    assert "token=[REDACTED]&query=python" in sanitized


def test_sanitize_preserves_benign_token_words() -> None:
    """Preserva texto normal que contiene la palabra 'token' sin asignación de secretos."""
    benign_sentences = [
        "Tokenizing the prompt with BPE tokenizer.",
        "Total prompt tokens consumed: 1250.",
        "The model generated 45 tokens per second.",
    ]
    for sentence in benign_sentences:
        assert sanitize_line(sentence) == sentence


def test_run_agy_process_success() -> None:
    """Ejecuta un subproceso con éxito, capturando y sanitizando las líneas."""
    lines: list[str] = []
    # Usamos el intérprete de Python para emular un subproceso real
    code = (
        "import sys\n"
        "print('Linea 1 de salida')\n"
        "print('Authorization: Bearer secret_12345')\n"
        "sys.stdout.flush()\n"
    )
    exit_code = run_agy_process(
        ["-c", code],
        executable_path=Path(sys.executable),
        on_line=lines.append,
        echo_output=False,
    )
    assert exit_code == 0
    joined = "".join(lines)
    assert "Linea 1 de salida" in joined
    assert "secret_12345" not in joined
    assert "[REDACTED]" in joined


def test_run_agy_process_non_zero_exit() -> None:
    """Retorna el código de error correspondiente si el subproceso falla."""
    code = "import sys; sys.exit(42)"
    exit_code = run_agy_process(
        ["-c", code],
        executable_path=Path(sys.executable),
        echo_output=False,
    )
    assert exit_code == 42


def test_run_agy_process_not_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Lanza AgyNotFoundError si no se proporciona ruta y agy no está en PATH."""
    monkeypatch.setenv("PATH", str(tmp_path / "vacio"))
    with pytest.raises(AgyNotFoundError):
        run_agy_process(["version"], echo_output=False)


def test_run_agy_process_os_error() -> None:
    """Lanza RunnerError si el ejecutable no es válido o no se puede iniciar."""
    with pytest.raises(RunnerError) as exc_info:
        run_agy_process(
            ["args"],
            executable_path=Path("archivo_inexistente_12345_xyz.exe"),
            echo_output=False,
        )
    assert "Error al iniciar el subproceso" in str(exc_info.value)


def test_run_agy_process_keyboard_interrupt(monkeypatch: pytest.MonkeyPatch) -> None:
    """Gestiona KeyboardInterrupt terminando el proceso y devolviendo código 130."""
    fake_proc = MagicMock()
    fake_proc.poll.return_value = None

    class InterruptingStdout:
        def __iter__(self) -> InterruptingStdout:
            return self

        def __next__(self) -> str:
            raise KeyboardInterrupt()

    fake_proc.stdout = InterruptingStdout()

    monkeypatch.setattr("subprocess.Popen", lambda *args, **kwargs: fake_proc)
    terminate_cleanly_mock = MagicMock()
    monkeypatch.setattr("agyswitcher.runner._terminate_cleanly", terminate_cleanly_mock)

    exit_code = run_agy_process(
        ["args"],
        executable_path=Path(sys.executable),
        echo_output=False,
    )
    assert exit_code == 130
    terminate_cleanly_mock.assert_called_once()


def test_kill_process_tree(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifica que kill_process_tree invoca taskkill en Windows."""
    run_mock = MagicMock()
    monkeypatch.setattr("subprocess.run", run_mock)
    monkeypatch.setattr("os.name", "nt")

    kill_process_tree(9999)
    run_mock.assert_called_once()
    called_cmd = run_mock.call_args[0][0]
    assert called_cmd == [system_tool("taskkill.exe"), "/T", "/F", "/PID", "9999"]
    assert Path(called_cmd[0]).is_absolute()


# ---------------------------------------------------------------------------
# Fase 5e-D: sin captura genérica; limpieza garantizada en finally
# ---------------------------------------------------------------------------


class _ErroringStdout:
    def __init__(self, exc: BaseException) -> None:
        self._exc = exc

    def __iter__(self) -> _ErroringStdout:
        return self

    def __next__(self) -> str:
        raise self._exc


def _fake_proc(monkeypatch: pytest.MonkeyPatch, exc: BaseException) -> MagicMock:
    fake_proc = MagicMock()
    fake_proc.poll.return_value = None
    fake_proc.stdout = _ErroringStdout(exc)
    monkeypatch.setattr("subprocess.Popen", lambda *args, **kwargs: fake_proc)
    terminate = MagicMock()
    monkeypatch.setattr("agyswitcher.runner._terminate_cleanly", terminate)
    return terminate


def test_run_agy_process_pipe_oserror_wrapped_and_cleaned(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un OSError de E/S se convierte en RunnerError y el hijo se termina."""
    terminate = _fake_proc(monkeypatch, OSError("pipe rota"))
    with pytest.raises(RunnerError, match="pipe rota"):
        run_agy_process(["x"], executable_path=Path(sys.executable), echo_output=False)
    terminate.assert_called_once()


def test_run_agy_process_callback_error_propagates_and_cleans() -> None:
    """Un error del callback on_line se propaga con su tipo original y el hijo real termina."""

    class CallbackError(Exception):
        pass

    def on_line(_line: str) -> None:
        raise CallbackError("fallo en callback")

    code = "import time\nprint('linea', flush=True)\ntime.sleep(30)\n"
    with pytest.raises(CallbackError):
        run_agy_process(
            ["-c", code],
            executable_path=Path(sys.executable),
            on_line=on_line,
            echo_output=False,
            grace_period=0.5,
        )


def test_run_agy_process_unexpected_error_not_wrapped(monkeypatch: pytest.MonkeyPatch) -> None:
    """Errores no previstos no se enmascaran como RunnerError, pero sí se limpia el proceso."""
    terminate = _fake_proc(monkeypatch, ValueError("inesperado"))
    with pytest.raises(ValueError):
        run_agy_process(["x"], executable_path=Path(sys.executable), echo_output=False)
    terminate.assert_called_once()


# ---------------------------------------------------------------------------
# Fase 5f-2d: detección de agy / IDE en ejecución
# ---------------------------------------------------------------------------


def test_find_running_agy_processes_parses_tasklist(monkeypatch: pytest.MonkeyPatch) -> None:
    """Devuelve los procesos de agy y del IDE encontrados en la salida CSV de tasklist."""
    output = (
        '"System Idle Process","0","Services","0","8 K"\n'
        '"agy.exe","100","Console","1","50.000 K"\n'
        '"Antigravity IDE.exe","200","Console","1","90.000 K"\n'
        '"agy.exe","101","Console","1","10.000 K"\n'
        '"notepad.exe","300","Console","1","5.000 K"\n'
    )
    run_mock = MagicMock(return_value=MagicMock(returncode=0, stdout=output))
    monkeypatch.setattr("agyswitcher.runner.subprocess.run", run_mock)
    monkeypatch.setattr("agyswitcher.runner.os.name", "nt")

    assert find_running_agy_processes() == ["Antigravity IDE.exe", "agy.exe"]
    assert run_mock.call_args.args[0][0] == system_tool("tasklist.exe")
    kwargs = run_mock.call_args.kwargs
    assert kwargs["timeout"] == 10.0
    assert kwargs["stdin"] is subprocess.DEVNULL


def test_find_running_agy_processes_unknown_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Si tasklist falla o expira, el resultado es None (no se puede asegurar nada)."""
    monkeypatch.setattr("agyswitcher.runner.os.name", "nt")
    monkeypatch.setattr(
        "agyswitcher.runner.subprocess.run",
        MagicMock(side_effect=subprocess.TimeoutExpired(cmd="tasklist", timeout=10)),
    )
    assert find_running_agy_processes() is None

    monkeypatch.setattr(
        "agyswitcher.runner.subprocess.run",
        MagicMock(return_value=MagicMock(returncode=1, stdout="")),
    )
    assert find_running_agy_processes() is None


# ---------------------------------------------------------------------------
# run_captured: ejecución no interactiva con tiempo máximo garantizado (5f-3)
# ---------------------------------------------------------------------------

# Script del hijo: lanza un nieto que hereda stdout/stderr, guarda su PID y espera.
_SPAWN_GRANDCHILD = (
    "import subprocess, sys, time\n"
    "g = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'],"
    " stdout=sys.stdout, stderr=sys.stderr)\n"
    "open(sys.argv[1], 'w').write(str(g.pid))\n"
    "if sys.argv[2] == 'wait':\n"
    "    time.sleep(60)\n"
)


def _pid_alive(pid: int) -> bool:
    # tasklist writes its "no tasks" notice in the console code page (e.g. cp850); with
    # errors="replace" decoding never fails, whatever Python's default encoding is.
    out = subprocess.run(
        ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
        capture_output=True,
        text=True,
        errors="replace",
        stdin=subprocess.DEVNULL,
        check=False,
        timeout=10,
    ).stdout
    return f'"{pid}"' in out


def test_run_captured_success_and_stdin_closed() -> None:
    """Captura la salida en UTF-8 y el hijo recibe stdin vacío (no se queda esperando teclado)."""
    code = "import sys; data = sys.stdin.read(); print('ok-ñ', len(data))"
    res = run_captured([sys.executable, "-X", "utf8", "-c", code], timeout=20)
    assert res.returncode == 0
    assert res.stdout.strip() == "ok-ñ 0"


def test_run_captured_nonzero_exit() -> None:
    code = "import sys; sys.stderr.write('fallo'); sys.exit(3)"
    res = run_captured([sys.executable, "-c", code], timeout=20)
    assert res.returncode == 3
    assert "fallo" in res.stderr


@pytest.mark.skipif(os.name != "nt", reason="Árbol de procesos con taskkill (Windows)")
def test_run_captured_timeout_kills_whole_tree(tmp_path: Path) -> None:
    """Al expirar el tiempo termina hijo y nieto y vuelve enseguida (antes se bloqueaba)."""
    pid_file = tmp_path / "grandchild.pid"
    cmd = [sys.executable, "-c", _SPAWN_GRANDCHILD, str(pid_file), "wait"]
    start = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        run_captured(cmd, timeout=3.0, kill_grace=3.0)
    assert time.monotonic() - start < 15
    grandchild = int(pid_file.read_text())
    assert not _pid_alive(grandchild)


@pytest.mark.skipif(os.name != "nt", reason="Herencia de tuberías en Windows")
def test_run_captured_bounded_when_orphan_holds_pipes(tmp_path: Path) -> None:
    """El hijo termina pero un nieto huérfano mantiene las tuberías: la espera sigue acotada."""
    pid_file = tmp_path / "grandchild.pid"
    cmd = [sys.executable, "-c", _SPAWN_GRANDCHILD, str(pid_file), "exit"]
    start = time.monotonic()
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            run_captured(cmd, timeout=3.0, kill_grace=1.0)
        assert time.monotonic() - start < 15
    finally:
        if pid_file.exists():
            kill_process_tree(int(pid_file.read_text()))
