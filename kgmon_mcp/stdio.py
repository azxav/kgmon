from __future__ import annotations

import json
import logging
import sys
from typing import Any, BinaryIO, cast

from kgmon_mcp.server import (
    create_mcp_server,
    list_mcp_prompts,
    list_mcp_resources,
    public_tool_definitions,
    read_mcp_resource,
    run_public_tool,
)


def main() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO)
    create_mcp_server()
    _serve(sys.stdin.buffer, sys.stdout.buffer)


def _serve(stdin: BinaryIO, stdout: BinaryIO) -> None:
    while True:
        message = _read_message(stdin)
        if message is None:
            return
        if "id" not in message:
            continue
        response = _handle_request(message)
        _write_message(stdout, response)


def _handle_request(message: dict[str, Any]) -> dict[str, Any]:
    request_id = message.get("id")
    method = str(message.get("method", ""))
    params = message.get("params")
    if not isinstance(params, dict):
        params = {}

    try:
        if method == "initialize":
            result: dict[str, Any] = {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "kgmon", "version": "0.1.0"},
                "capabilities": {
                    "tools": {},
                    "resources": {},
                    "prompts": {},
                },
            }
        elif method == "tools/list":
            result = {"tools": public_tool_definitions()}
        elif method == "resources/list":
            result = {"resources": list_mcp_resources()}
        elif method == "prompts/list":
            result = {"prompts": list_mcp_prompts()}
        elif method == "tools/call":
            name = str(params.get("name", ""))
            arguments = params.get("arguments")
            if not isinstance(arguments, dict):
                arguments = {}
            payload = run_public_tool(name, arguments)
            result = {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(payload, sort_keys=True),
                    }
                ],
                "isError": not bool(payload.get("ok", False)),
            }
        elif method == "resources/read":
            uri = str(params.get("uri", ""))
            payload = read_mcp_resource(uri)
            result = {
                "contents": [
                    {
                        "uri": uri,
                        "mimeType": "application/json",
                        "text": json.dumps(payload, sort_keys=True),
                    }
                ]
            }
        elif method == "prompts/get":
            name = str(params.get("name", ""))
            payload = run_public_tool("kgmon_prompt_run", {"prompt_id": name})
            result = {
                "messages": [
                    {
                        "role": "user",
                        "content": {
                            "type": "text",
                            "text": json.dumps(payload, sort_keys=True),
                        },
                    }
                ]
            }
        else:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32601, "message": f"unknown method: {method}"},
            }
    except Exception as exc:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32000, "message": str(exc)},
        }
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _read_message(stdin: BinaryIO) -> dict[str, Any] | None:
    headers: dict[str, str] = {}
    while True:
        line = stdin.readline()
        if line == b"":
            return None
        if line in {b"\r\n", b"\n"}:
            break
        key, _, value = line.decode("ascii").partition(":")
        headers[key.lower()] = value.strip()

    length = int(headers.get("content-length", "0"))
    if length <= 0:
        return None
    body = stdin.read(length)
    return cast(dict[str, Any], json.loads(body.decode("utf-8")))


def _write_message(stdout: BinaryIO, message: dict[str, Any]) -> None:
    body = json.dumps(message, separators=(",", ":")).encode("utf-8")
    stdout.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii"))
    stdout.write(body)
    stdout.flush()


if __name__ == "__main__":
    main()
