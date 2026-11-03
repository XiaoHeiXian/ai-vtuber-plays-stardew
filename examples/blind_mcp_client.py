"""Minimal BlindWhaleFarmer MCP client.

The mod exposes a stateless Streamable-HTTP MCP endpoint at
http://127.0.0.1:18080/mcp. It may answer with plain JSON or with an SSE
frame (``data: {...}``), so the body parser accepts both.

Usage:
    pip install aiohttp
    python blind_mcp_client.py 18080 get_state
    python blind_mcp_client.py 18080 tools/list
    python blind_mcp_client.py 18080 fish '{"location":"Farm"}'

This is a deliberately small excerpt from a working integration. It is
read-only by default; tools that change the game are up to you.
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

import aiohttp

PROTOCOL_VERSION = "2024-11-05"


def parse_body(text: str) -> dict[str, Any]:
    """Accept both application/json and text/event-stream bodies."""
    text = (text or "").strip()
    if not text:
        return {}
    if text.startswith("{"):
        return json.loads(text)
    payload: dict[str, Any] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if not data:
            continue
        try:
            item = json.loads(data)
        except ValueError:
            continue
        if isinstance(item, dict) and ("result" in item or "error" in item):
            payload = item
    return payload


def text_of(result: dict[str, Any]) -> str:
    parts = []
    for item in (result or {}).get("content") or []:
        if isinstance(item, dict) and item.get("type") == "text":
            parts.append(str(item.get("text") or ""))
    return "\n".join(parts)


class BlindMcpClient:
    def __init__(self, port: int = 18080, timeout: float = 30.0) -> None:
        self.url = f"http://127.0.0.1:{int(port)}/mcp"
        self.timeout = float(timeout)
        self.session: aiohttp.ClientSession | None = None
        self._id = 0

    async def __aenter__(self) -> "BlindMcpClient":
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.timeout)
        )
        await self.rpc(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "blind-mcp-example", "version": "1"},
            },
        )
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self.session is not None:
            await self.session.close()
            self.session = None

    async def rpc(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if self.session is None:
            raise RuntimeError("client is not open; use 'async with'")
        self._id += 1
        frame: dict[str, Any] = {"jsonrpc": "2.0", "id": self._id, "method": method}
        if params is not None:
            frame["params"] = params
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        async with self.session.post(self.url, json=frame, headers=headers) as resp:
            body = await resp.text()
            if resp.status != 200:
                raise RuntimeError(f"MCP HTTP {resp.status}: {body[:200]}")
        data = parse_body(body)
        if data.get("error"):
            err = data["error"]
            raise RuntimeError(str(err.get("message") or err)[:300])
        return data.get("result") or {}

    async def call_tool(self, name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        result = await self.rpc("tools/call", {"name": name, "arguments": args or {}})
        if result.get("isError"):
            raise RuntimeError(f"{name} failed: {text_of(result)[:300]}")
        return result

    async def get_state(self) -> str:
        return text_of(await self.call_tool("get_state"))


async def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 18080
    tool = sys.argv[2] if len(sys.argv) > 2 else "get_state"
    args = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}

    async with BlindMcpClient(port) as client:
        if tool == "tools/list":
            result = await client.rpc("tools/list", {})
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(text_of(await client.call_tool(tool, args)))


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
