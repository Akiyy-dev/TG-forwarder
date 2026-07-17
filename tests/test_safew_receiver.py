"""SafeW receiver process-health tests."""

from pathlib import Path

from app.entrypoints.safew_receiver import _safew_client_running


def _write_cmdline(proc_root: Path, pid: int, *argv: str) -> None:
    process_dir = proc_root / str(pid)
    process_dir.mkdir(parents=True)
    (process_dir / "cmdline").write_bytes(b"\0".join(item.encode() for item in argv) + b"\0")


def test_safew_process_probe_requires_real_binary_argv0(tmp_path: Path) -> None:
    _write_cmdline(tmp_path, 1, "python", "-m", "app.entrypoints.safew_receiver")
    _write_cmdline(tmp_path, 2, "sh", "-c", "echo /opt/safew/SafeW")
    assert _safew_client_running(tmp_path) is False

    _write_cmdline(tmp_path, 3, "/opt/safew/SafeW", "-workdir", "/data/safew-profile")
    assert _safew_client_running(tmp_path) is True
