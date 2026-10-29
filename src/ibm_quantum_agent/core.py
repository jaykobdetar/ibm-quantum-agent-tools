"""Circuit validation and IBM Runtime adapter; no arbitrary Python execution."""
from __future__ import annotations

import json
import math
import os
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from qiskit import QuantumCircuit, transpile
from qiskit.providers.basic_provider import BasicSimulator
from qiskit.quantum_info import SparsePauliOp
from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager
from qiskit_ibm_runtime import EstimatorV2, QiskitRuntimeService, SamplerV2
from qiskit_ibm_runtime.exceptions import RuntimeJobTimeoutError


class QuantumToolError(Exception):
    """A safe, actionable error that contains no upstream response or credentials."""


GateName = Literal[
    "id", "x", "y", "z", "h", "s", "sdg", "t", "tdg", "sx", "sxdg",
    "rx", "ry", "rz", "p", "u", "cx", "cy", "cz", "ch", "swap",
    "ccx", "cswap", "cp", "crx", "cry", "crz", "rxx", "ryy", "rzz", "barrier",
]
Qubit = Annotated[int, Field(strict=True, ge=0, le=255)]
ARITY = {
    **{g: (1, 0) for g in ("id", "x", "y", "z", "h", "s", "sdg", "t", "tdg", "sx", "sxdg")},
    **{g: (1, 1) for g in ("rx", "ry", "rz", "p")},
    "u": (1, 3),
    **{g: (2, 0) for g in ("cx", "cy", "cz", "ch", "swap")},
    **{g: (2, 1) for g in ("cp", "crx", "cry", "crz", "rxx", "ryy", "rzz")},
    "ccx": (3, 0), "cswap": (3, 0),
}


class Gate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    gate: GateName
    qubits: list[Qubit] = Field(min_length=1, max_length=256)
    params: list[float] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def valid_gate(self):
        if len(set(self.qubits)) != len(self.qubits):
            raise ValueError("A gate must use distinct qubits.")
        expected = (len(self.qubits), 0) if self.gate == "barrier" else ARITY[self.gate]
        if (len(self.qubits), len(self.params)) != expected:
            raise ValueError(f"{self.gate} needs {expected[0]} qubits and {expected[1]} parameters.")
        if any(not math.isfinite(p) for p in self.params):
            raise ValueError("Gate parameters must be finite radians.")
        return self


class CircuitSpec(BaseModel):
    """Bound unitary circuit. Sampler/simulation measures all qubits at the end."""
    model_config = ConfigDict(extra="forbid")
    num_qubits: int = Field(strict=True, ge=1, le=256)
    gates: list[Gate] = Field(default_factory=list, max_length=10000)

    @model_validator(mode="after")
    def qubits_in_range(self):
        if any(q >= self.num_qubits for g in self.gates for q in g.qubits):
            raise ValueError("Gate qubit index is outside the circuit.")
        return self


class ObservableTerm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pauli: str = Field(min_length=1, max_length=256, pattern="^[IXYZ]+$")
    coefficient: float = 1.0

    @field_validator("coefficient")
    @classmethod
    def finite(cls, value):
        if not math.isfinite(value):
            raise ValueError("Observable coefficients must be finite real numbers.")
        return value


def integer_setting(name: str, default: int, ceiling: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        raise QuantumToolError(f"{name} must be an integer.") from None
    if not 1 <= value <= ceiling:
        raise QuantumToolError(f"{name} must be between 1 and {ceiling}.")
    return value


def configuration() -> dict:
    return {
        "credential_configured": bool(os.environ.get("IBM_QUANTUM_API_KEY") or
                                      os.environ.get("IBM_QUANTUM_API_KEY_FILE")),
        "instance_configured": bool(os.environ.get("IBM_QUANTUM_INSTANCE")),
        "max_shots": integer_setting("IBM_QUANTUM_MAX_SHOTS", 8192, 1000000),
        "max_execution_seconds": integer_setting("IBM_QUANTUM_MAX_EXECUTION_SECONDS", 60, 10800),
        "max_local_qubits": 20,
        "max_circuit_qubits": 256,
        "channel": "ibm_quantum_platform",
        "transport": "stdio",
    }


def load_api_key() -> str:
    """Only trusted process configuration selects the credential source."""
    token = os.environ.get("IBM_QUANTUM_API_KEY")
    if token:
        if not token.strip():
            raise QuantumToolError("IBM_QUANTUM_API_KEY must not be blank.")
        return token.strip()
    filename = os.environ.get("IBM_QUANTUM_API_KEY_FILE")
    if not filename:
        raise QuantumToolError("Set IBM_QUANTUM_API_KEY_FILE to the IBM JSON credential file, or set IBM_QUANTUM_API_KEY.")
    try:
        path = Path(filename).expanduser()
        if path.stat().st_size > 65536:
            raise QuantumToolError("The configured credential file is too large.")
        data = json.loads(path.read_text(encoding="utf-8"))
        token = data.get("apikey") if isinstance(data, dict) else None
        if not isinstance(token, str) or not token.strip():
            raise QuantumToolError("The credential JSON must contain a nonempty apikey string.")
        return token.strip()
    except (OSError, ValueError, UnicodeError):
        raise QuantumToolError("Cannot read the configured IBM credential JSON file.") from None


@lru_cache(maxsize=8)
def service(instance: str | None = None):
    return QiskitRuntimeService(
        channel="ibm_quantum_platform", token=load_api_key(),
        instance=instance or os.environ.get("IBM_QUANTUM_INSTANCE") or None,
    )


def resolve_instance(instance: str | None) -> str:
    chosen = instance or os.environ.get("IBM_QUANTUM_INSTANCE")
    if chosen:
        return chosen
    instances = service().instances()
    if len(instances) != 1:
        raise QuantumToolError("Choose an instance CRN from quantum_instances and pass it as instance, or configure IBM_QUANTUM_INSTANCE.")
    return instances[0]["crn"]


def instances() -> dict:
    return {"instances": [{k: item.get(k) for k in ("crn", "name", "plan")}
                          for item in service().instances()]}


def backends(instance: str | None, min_num_qubits: int) -> dict:
    chosen = resolve_instance(instance)
    items = []
    for backend in service(chosen).backends(min_num_qubits=min_num_qubits):
        status = backend.status()
        items.append({"name": backend.name, "num_qubits": backend.num_qubits,
                      "operational": status.operational, "pending_jobs": status.pending_jobs,
                      "status": status.status_msg, "basis_gates": sorted(backend.operation_names)})
    return {"instance": chosen, "backends": sorted(items, key=lambda x: (not x["operational"], x["pending_jobs"]))}


def build_circuit(spec: CircuitSpec, measured: bool = True) -> QuantumCircuit:
    circuit = QuantumCircuit(spec.num_qubits)
    for operation in spec.gates:
        getattr(circuit, operation.gate)(*operation.params, *operation.qubits)
    if measured:
        circuit.measure_all()
    return circuit


def validate_budget(shots: int, max_execution_seconds: int):
    cfg = configuration()
    if type(shots) is not int or not 1 <= shots <= cfg["max_shots"]:
        raise QuantumToolError(f"shots must be between 1 and {cfg['max_shots']}.")
    if type(max_execution_seconds) is not int or not 1 <= max_execution_seconds <= cfg["max_execution_seconds"]:
        raise QuantumToolError(f"max_execution_seconds must be between 1 and {cfg['max_execution_seconds']}.")


def simulate(spec: CircuitSpec, shots: int, seed: int) -> dict:
    validate_budget(shots, 1)
    if spec.num_qubits > 20:
        raise QuantumToolError("Local simulation supports at most 20 qubits.")
    circuit = build_circuit(spec)
    simulator = BasicSimulator()
    compiled = transpile(circuit, backend=simulator, seed_transpiler=seed)
    counts = simulator.run(compiled, shots=shots, seed_simulator=seed).result().get_counts()
    return {"simulation": True, "num_qubits": spec.num_qubits, "shots": shots,
            "counts": counts, "bit_order": "Leftmost bit is qubit n-1; rightmost is qubit 0."}


def prepare(spec: CircuitSpec, backend_name: str, instance: str | None, measured: bool):
    chosen = resolve_instance(instance)
    backend = service(chosen).backend(backend_name)
    if spec.num_qubits > backend.num_qubits:
        raise QuantumToolError("Circuit has more qubits than the selected backend.")
    circuit = build_circuit(spec, measured)
    isa = generate_preset_pass_manager(backend=backend, optimization_level=1, seed_transpiler=1234).run(circuit)
    summary = {"backend": backend.name, "instance": chosen, "logical_qubits": spec.num_qubits,
               "physical_qubits": isa.num_qubits, "depth": isa.depth(),
               "operations": dict(isa.count_ops()), "measured": measured}
    return backend, isa, summary


def sampler(spec: CircuitSpec, backend_name: str, instance: str | None, shots: int,
            max_execution_seconds: int, dry_run: bool) -> dict:
    validate_budget(shots, max_execution_seconds)
    backend, isa, summary = prepare(spec, backend_name, instance, True)
    summary.update({"primitive": "sampler", "shots": shots, "max_execution_seconds": max_execution_seconds,
                    "dry_run": dry_run, "submitted": False})
    if dry_run:
        return summary
    status = backend.status()
    if not status.operational:
        raise QuantumToolError("The selected backend is not operational.")
    job = SamplerV2(mode=backend, options={"max_execution_time": max_execution_seconds,
                                         "environment": {"job_tags": ["ibm-quantum-agent"]}}).run([isa], shots=shots)
    summary.update({"submitted": True, "job_id": job.job_id(),
                    "next_step": "Poll quantum_job with this job_id. Do not submit this work again."})
    return summary


def estimator(spec: CircuitSpec, terms: list[ObservableTerm], backend_name: str,
              instance: str | None, shots: int, max_execution_seconds: int, dry_run: bool) -> dict:
    validate_budget(shots, max_execution_seconds)
    if not 1 <= len(terms) <= 100:
        raise QuantumToolError("Supply 1 to 100 terms for one observable.")
    if any(len(term.pauli) != spec.num_qubits for term in terms):
        raise QuantumToolError("Every Pauli label must have one character per logical qubit.")
    observable = SparsePauliOp.from_list([(term.pauli, term.coefficient) for term in terms])
    backend, isa, summary = prepare(spec, backend_name, instance, False)
    mapped = observable.apply_layout(isa.layout)
    summary.update({"primitive": "estimator", "default_shots": shots,
                    "max_execution_seconds": max_execution_seconds, "dry_run": dry_run,
                    "submitted": False, "observable_terms": [term.model_dump() for term in terms]})
    if dry_run:
        return summary
    if not backend.status().operational:
        raise QuantumToolError("The selected backend is not operational.")
    job = EstimatorV2(mode=backend, options={"max_execution_time": max_execution_seconds,
        "default_shots": shots, "resilience_level": 0,
        "environment": {"job_tags": ["ibm-quantum-agent"]}}).run([(isa, mapped)])
    summary.update({"submitted": True, "job_id": job.job_id(),
                    "next_step": "Poll quantum_job with this job_id. Do not submit this work again."})
    return summary


def job_summary(job) -> dict:
    created = job.creation_date
    return {"job_id": job.job_id(), "status": str(job.status()), "primitive": job.primitive_id,
            "created_at": created.isoformat() if created else None,
            "instance": job.instance}


def jobs(instance: str | None, limit: int, skip: int, pending: bool | None) -> dict:
    chosen = resolve_instance(instance)
    return {"instance": chosen, "jobs": [job_summary(job) for job in
            service(chosen).jobs(limit=limit, skip=skip, pending=pending, instance=chosen)],
            "limit": limit, "skip": skip}


def summarize_result(result, max_counts: int) -> list[dict]:
    pubs = []
    for index, pub in enumerate(result):
        if index >= 20:
            break
        values = {}
        for name, value in pub.data.items():
            if hasattr(value, "get_counts"):
                if value.shape:
                    values[name] = {"shape": list(value.shape), "message": "Parameter-sweep results require the Qiskit Python API; counts were not aggregated."}
                    continue
                counts = value.get_counts()
                ordered = sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
                kept = dict(ordered[:max_counts])
                values[name] = {"counts": kept, "shots": int(value.num_shots), "num_bits": int(value.num_bits),
                                "truncated": len(counts) > max_counts,
                                "omitted_shots": sum(counts.values()) - sum(kept.values())}
            elif hasattr(value, "tolist"):
                if getattr(value, "size", 0) > 2000:
                    values[name] = {"shape": list(value.shape), "truncated": True}
                else:
                    values[name] = value.tolist()
        pubs.append({"pub_index": index, "data": values})
    return pubs


def get_job(job_id: str, instance: str | None, include_results: bool, wait_seconds: int, max_counts: int) -> dict:
    chosen = resolve_instance(instance)
    job = service(chosen).job(job_id)
    summary = job_summary(job)
    if not include_results:
        return summary
    if summary["status"] in ("ERROR", "CANCELLED"):
        summary["message"] = "Job did not complete successfully. Inspect IBM Quantum Platform for details."
        return summary
    if summary["status"] != "DONE" and wait_seconds == 0:
        summary["results_ready"] = False
        return summary
    try:
        result = job.result(timeout=max(wait_seconds, 1), poll_interval=1)
    except RuntimeJobTimeoutError:
        summary.update({"results_ready": False, "message": "Still pending; poll this job_id again without resubmitting."})
        return summary
    summary.update({"status": "DONE", "results_ready": True, "pubs": summarize_result(result, max_counts),
                    "pubs_truncated": len(result) > 20})
    return summary


def cancel_job(job_id: str, instance: str | None) -> dict:
    chosen = resolve_instance(instance)
    job = service(chosen).job(job_id)
    status = str(job.status())
    if status in ("DONE", "ERROR", "CANCELLED"):
        return {"job_id": job_id, "status": status, "cancellation_requested": False}
    job.cancel()
    return {"job_id": job_id, "cancellation_requested": True}
