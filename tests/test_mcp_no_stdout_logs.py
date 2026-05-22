from __future__ import annotations

import subprocess
import sys


def test_stdio_entrypoint_emits_no_stdout_when_started_without_messages() -> None:
    process = subprocess.run(
        [sys.executable, "-m", "kgmon_mcp.stdio"],
        input=b"",
        capture_output=True,
        check=True,
    )

    assert process.stdout == b""
