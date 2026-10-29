"""Ensure errors crossing the agent boundary do not expose SDK response secrets."""
import pytest
from mcp.server.fastmcp.exceptions import ToolError

from ibm_quantum_agent import core, server


def test_upstream_response_and_secret_are_not_exposed(monkeypatch):
    def fail():
        raise RuntimeError("Authorization: Bearer synthetic-private-token; raw private server body")
    monkeypatch.setattr(core, "instances", fail)
    with pytest.raises(ToolError) as caught:
        server.quantum_instances()
    message = str(caught.value)
    assert "RuntimeError" in message
    assert "synthetic-private-token" not in message
    assert "raw private server body" not in message
    assert "Bearer" not in message


def test_safe_configuration_errors_remain_actionable(monkeypatch):
    monkeypatch.delenv("IBM_QUANTUM_API_KEY", raising=False)
    monkeypatch.delenv("IBM_QUANTUM_API_KEY_FILE", raising=False)
    monkeypatch.setattr(core, "instances", lambda: core.load_api_key())
    with pytest.raises(ToolError, match="Set IBM_QUANTUM_API_KEY_FILE"):
        server.quantum_instances()
