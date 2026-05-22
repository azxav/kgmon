from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

from kgmon_runtime.setup import RuntimeSetup


def test_stdio_server_lists_tools_resources_and_prompts_without_banner() -> None:
    repo = _workspace("stdio")
    RuntimeSetup(repo).setup_local()

    responses = _run_stdio(
        repo,
        [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "resources/list"},
            {"jsonrpc": "2.0", "id": 4, "method": "prompts/list"},
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {
                    "name": "kgmon_doctor",
                    "arguments": {"workspace_root": str(repo)},
                },
            },
        ],
    )

    assert [response["id"] for response in responses] == [1, 2, 3, 4, 5]
    tools = responses[1]["result"]["tools"]
    resources = responses[2]["result"]["resources"]
    prompts = responses[3]["result"]["prompts"]
    doctor = responses[4]["result"]["content"][0]

    assert "kgmon_doctor" in {tool["name"] for tool in tools}
    assert "kgmon://state/current" in {resource["uri"] for resource in resources}
    assert "kgmon_validation_design" in {prompt["name"] for prompt in prompts}
    assert doctor["type"] == "text"
    payload = json.loads(doctor["text"])
    assert payload["ok"] is True
    assert payload["data"]["status"] == "ok"


def _run_stdio(
    repo: Path, messages: list[dict[str, object]]
) -> list[dict[str, object]]:
    payload = b"".join(_frame(message) for message in messages)
    process = subprocess.run(
        [sys.executable, "-m", "kgmon_mcp.stdio"],
        input=payload,
        cwd=repo,
        env={**os.environ, "PYTHONPATH": str(Path.cwd())},
        capture_output=True,
        check=True,
    )
    assert process.stderr == b""
    return _parse_frames(process.stdout)


def _frame(message: dict[str, object]) -> bytes:
    body = json.dumps(message).encode("utf-8")
    return f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body


def _parse_frames(stream: bytes) -> list[dict[str, object]]:
    frames: list[dict[str, object]] = []
    offset = 0
    while offset < len(stream):
        header_end = stream.index(b"\r\n\r\n", offset)
        headers = stream[offset:header_end].decode("ascii").split("\r\n")
        length = int(headers[0].split(":", 1)[1].strip())
        body_start = header_end + 4
        body_end = body_start + length
        frames.append(json.loads(stream[body_start:body_end].decode("utf-8")))
        offset = body_end
    return frames


def _workspace(name: str) -> Path:
    path = Path("test-output") / "m11-stdio" / f"{name}-{uuid.uuid4().hex}"
    path.mkdir(parents=True)
    return path
