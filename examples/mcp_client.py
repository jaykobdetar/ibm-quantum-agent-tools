"""Connect an agent to the local IBM Quantum MCP server and simulate Bell shots.

Run with the same Python environment in which this project is installed::

    python examples/mcp_client.py

This example uses the official MCP Python SDK's stdio transport. It does not
submit a cloud job; local simulation works without an IBM credential.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import timedelta
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import CallToolResult


def tool_payload(result: CallToolResult) -> dict[str, Any]:
    """Read typed tool output, retaining compatibility with text-only clients."""
    if result.isError:
        messages = [block.text for block in result.content if block.type == "text"]
        raise RuntimeError("; ".join(messages) or "MCP tool returned an error")
    if result.structuredContent is not None:
        return result.structuredContent
    for block in result.content:
        if block.type == "text":
            payload = json.loads(block.text)
            if isinstance(payload, dict):
                return payload
    raise RuntimeError("MCP tool returned no JSON object")


async def main() -> None:
    # The stdio SDK inherits only a small set of standard environment variables.
    # Forward this tool's configuration explicitly, including credential/config
    # file paths supplied by the caller. Never put a key in command arguments.
    server_environment = {
        name: value
        for name, value in os.environ.items()
        if name.startswith("IBM_QUANTUM_")
    }
    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "ibm_quantum_agent"],
        env=server_environment,
    )
    async with stdio_client(server) as (read_stream, write_stream):
        async with ClientSession(
            read_stream, write_stream, read_timeout_seconds=timedelta(seconds=30)
        ) as session:
            await session.initialize()
            available_tools = await session.list_tools()
            print("Available tools:", ", ".join(tool.name for tool in available_tools.tools))

            # An agent can choose a tool and construct arguments from list_tools'
            # inputSchema. Here the selection and Bell circuit are explicit.
            result = await session.call_tool(
                "quantum_simulate",
                arguments={
                    "circuit": {
                        "num_qubits": 2,
                        "gates": [
                            {"gate": "h", "qubits": [0]},
                            {"gate": "cx", "qubits": [0, 1]},
                        ],
                    },
                    "shots": 1024,
                    "seed": 1234,
                },
            )
            print(json.dumps(tool_payload(result), indent=2))


if __name__ == "__main__":
    asyncio.run(main())
