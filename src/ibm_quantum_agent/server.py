"""Typed MCP interface. stdout is reserved for the MCP protocol."""
from __future__ import annotations

import functools
import logging
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from . import core
from .core import CircuitSpec, ObservableTerm


mcp = FastMCP(
    "IBM Quantum",
    instructions=("IBM Quantum circuit and job tools. Credentials stay in the local server. "
        "Use quantum_configuration, quantum_instances and quantum_backends for discovery. "
        "Circuits are JSON gate lists with numeric angles in radians and zero-based qubit indices. "
        "Use quantum_simulate for a local check, then preview with dry_run=true. "
        "Only set dry_run=false when the user has requested hardware execution. "
        "Hardware jobs consume IBM quota and may incur charges under the selected instance plan. "
        "After submission save the job_id and poll quantum_job. If submission has an ambiguous "
        "network failure, check quantum_jobs and IBM's dashboard before retrying. "
        "Runtime seconds limit QPU usage, not queue time or total monetary spending."),
)
READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True)
LOCAL = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True)
CANCEL = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=True)
BackendName = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")]
Instance = Annotated[str | None, Field(max_length=1024)]
Shots = Annotated[int, Field(strict=True, ge=1, le=1000000)]
Seconds = Annotated[int, Field(strict=True, ge=1, le=10800)]
JobId = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")]


def safe_errors(fn):
    """Upstream error text/tracebacks may include secrets; only allow safe errors."""
    @functools.wraps(fn)
    def wrapped(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except core.QuantumToolError as exc:
            raise ToolError(str(exc)) from None
        except Exception as exc:
            name = type(exc).__name__
            hints = {
                "IBMNotAuthorizedError": "Check the API key and Quantum access permissions.",
                "InvalidAccountError": "Check the API key and configured instance CRN.",
                "IBMInputValueError": "Check the backend, instance, circuit, and job arguments.",
                "IBMBackendNotFoundError": "Use quantum_backends to select an accessible backend.",
                "RuntimeJobNotFound": "Check the job ID and its instance.",
                "RuntimeJobMaxTimeoutError": "The job exceeded its QPU execution limit.",
            }
            hint = hints.get(name, "Check IBM connectivity, credentials, instance access, and input. If submitting, check quantum_jobs before retrying.")
            raise ToolError(f"IBM Quantum operation failed ({name}). {hint}") from None
    return wrapped


@mcp.tool(annotations=LOCAL)
@safe_errors
def quantum_configuration() -> dict[str, Any]:
    """Show credential presence and configured limits without reading or returning the API key."""
    return core.configuration()


@mcp.tool(annotations=READ)
@safe_errors
def quantum_instances() -> dict[str, Any]:
    """Authenticate with IBM and list accessible instance CRNs, names, and plans; no compute is submitted."""
    return core.instances()


@mcp.tool(annotations=READ)
@safe_errors
def quantum_backends(instance: Instance = None,
                     min_num_qubits: Annotated[int, Field(strict=True, ge=1, le=256)] = 1) -> dict[str, Any]:
    """List accessible QPUs, availability, queue lengths, qubits, and supported gates for an instance."""
    return core.backends(instance, min_num_qubits)


@mcp.tool(annotations=LOCAL)
@safe_errors
def quantum_simulate(circuit: CircuitSpec, shots: Shots = 1024,
                     seed: Annotated[int, Field(strict=True, ge=0, le=4294967295)] = 1234) -> dict[str, Any]:
    """Simulate up to 20 qubits locally without IBM authentication or charges. Measure every qubit at end."""
    return core.simulate(circuit, shots, seed)


@mcp.tool(annotations=READ)
@safe_errors
def quantum_preview(circuit: CircuitSpec, backend_name: BackendName,
                    instance: Instance = None, measured: bool = True) -> dict[str, Any]:
    """Transpile for a specific IBM backend and report depth/gate counts without submitting a job."""
    return core.prepare(circuit, backend_name, instance, measured)[2]


@mcp.tool(annotations=WRITE)
@safe_errors
def quantum_run_sampler(circuit: CircuitSpec, backend_name: BackendName,
                        instance: Instance = None, shots: Shots = 1024,
                        max_execution_seconds: Seconds = 60, dry_run: bool = True) -> dict[str, Any]:
    """Sample a circuit, measuring all qubits. Default dry_run previews only. False submits one quota-consuming job and returns its ID immediately."""
    return core.sampler(circuit, backend_name, instance, shots, max_execution_seconds, dry_run)


@mcp.tool(annotations=WRITE)
@safe_errors
def quantum_run_estimator(circuit: CircuitSpec,
                          observable: Annotated[list[ObservableTerm], Field(min_length=1, max_length=100)],
                          backend_name: BackendName, instance: Instance = None,
                          shots: Shots = 1024, max_execution_seconds: Seconds = 60,
                          dry_run: bool = True) -> dict[str, Any]:
    """Estimate one weighted Pauli-sum observable. Pauli rightmost character is qubit 0. Shots is per measurement configuration, not total shots. False submits hardware work; default previews only."""
    return core.estimator(circuit, observable, backend_name, instance, shots, max_execution_seconds, dry_run)


@mcp.tool(annotations=READ)
@safe_errors
def quantum_jobs(instance: Instance = None,
                 limit: Annotated[int, Field(strict=True, ge=1, le=50)] = 10,
                 skip: Annotated[int, Field(strict=True, ge=0, le=1000000)] = 0,
                 pending: bool | None = None) -> dict[str, Any]:
    """List recent jobs for an instance. Page with skip. Use after ambiguous submission errors to avoid duplicates."""
    return core.jobs(instance, limit, skip, pending)


@mcp.tool(annotations=READ)
@safe_errors
def quantum_job(job_id: JobId, instance: Instance = None, include_results: bool = True,
                wait_seconds: Annotated[int, Field(strict=True, ge=0, le=30)] = 0,
                max_counts: Annotated[int, Field(strict=True, ge=1, le=4096)] = 256) -> dict[str, Any]:
    """Read job status and results. Default does not wait for queued work. Results include up to 20 PUBs, register counts or expectation values; large results are explicitly marked truncated."""
    return core.get_job(job_id, instance, include_results, wait_seconds, max_counts)


@mcp.tool(annotations=CANCEL)
@safe_errors
def quantum_cancel_job(job_id: JobId, instance: Instance = None) -> dict[str, Any]:
    """Request cancellation of the specified unfinished IBM job. Already consumed QPU time remains consumed."""
    return core.cancel_job(job_id, instance)


def main():
    # SDK debug logging is inappropriate in a credential-carrying MCP process.
    logging.disable(logging.CRITICAL)
    for name in ("qiskit_ibm_runtime", "ibm_cloud_sdk_core", "urllib3", "httpx", "httpcore"):
        logger = logging.getLogger(name)
        logger.addHandler(logging.NullHandler())
        logger.disabled = True
        logger.propagate = False
    mcp.run(transport="stdio")
