"""Exercise a real stdio MCP process without credentials or quantum hardware."""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import CallToolResult


def _payload(result: CallToolResult) -> dict[str, Any]:
    assert not result.isError, result
    if result.structuredContent is not None:
        return result.structuredContent
    for block in result.content:
        if block.type == "text":
            value = json.loads(block.text)
            assert isinstance(value, dict)
            return value
    raise AssertionError("Expected a JSON tool result")


def test_stdio_mcp_discovery_configuration_and_simulation(tmp_path: Path) -> None:
    """Check discovery, JSON arguments/results, and errors across the wire."""

    async def exercise() -> None:
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "ibm_quantum_agent"],
            # Do not inherit the caller's IBM credentials or submit settings.
            # The explicit nonexistent file also prevents credential discovery.
            env={
                "IBM_QUANTUM_API_KEY_FILE": str(tmp_path / "no-credentials.json"),
            },
        )
        async with stdio_client(parameters) as (read_stream, write_stream):
            async with ClientSession(
                read_stream,
                write_stream,
                read_timeout_seconds=timedelta(seconds=30),
            ) as session:
                await session.initialize()
                discovered = await session.list_tools()
                by_name = {tool.name: tool for tool in discovered.tools}
                assert {"quantum_configuration", "quantum_simulate"} <= by_name.keys()
                simulation_schema = by_name["quantum_simulate"].inputSchema
                assert "circuit" in simulation_schema["properties"]
                assert by_name["quantum_simulate"].outputSchema is not None
                assert by_name["quantum_simulate"].annotations.readOnlyHint is True
                assert by_name["quantum_run_sampler"].annotations.readOnlyHint is False

                configuration = _payload(
                    await session.call_tool("quantum_configuration", arguments={})
                )
                assert configuration

                simulation = _payload(
                    await session.call_tool(
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
                )
                assert simulation["simulation"] is True
                assert simulation["num_qubits"] == 2
                assert simulation["shots"] == 1024
                assert set(simulation["counts"]) == {"00", "11"}
                assert sum(simulation["counts"].values()) == 1024

                # A missing required circuit must produce a protocol tool error,
                # without crashing the server or accepting an invalid request.
                invalid = await session.call_tool(
                    "quantum_simulate", arguments={"shots": 1024}
                )
                assert invalid.isError
                assert any(block.type == "text" for block in invalid.content)
                assert _payload(
                    await session.call_tool("quantum_configuration", arguments={})
                )

    asyncio.run(asyncio.wait_for(exercise(), timeout=45))
