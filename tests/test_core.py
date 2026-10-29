"""Offline behavioral coverage using real Qiskit and isolated SDK doubles."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest
from pydantic import ValidationError
from qiskit import transpile
from qiskit.primitives import BitArray, DataBin, PrimitiveResult, PubResult, SamplerPubResult
from qiskit.providers.fake_provider import GenericBackendV2
from qiskit.quantum_info import Statevector
from qiskit_ibm_runtime.exceptions import RuntimeJobTimeoutError

from ibm_quantum_agent import core


@pytest.fixture(autouse=True)
def isolate_credentials_and_network(monkeypatch):
    """Never inherit credentials, cached services, or make a cloud request."""
    for name in (
        "IBM_QUANTUM_API_KEY", "IBM_QUANTUM_API_KEY_FILE", "IBM_QUANTUM_INSTANCE",
        "IBM_QUANTUM_MAX_SHOTS", "IBM_QUANTUM_MAX_EXECUTION_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)
    core.service.cache_clear()
    monkeypatch.setattr(core, "QiskitRuntimeService", Mock(side_effect=AssertionError("Unexpected SDK initialization")))
    yield
    core.service.cache_clear()


@pytest.fixture
def bell():
    return core.CircuitSpec.model_validate({
        "num_qubits": 2,
        "gates": [{"gate": "h", "qubits": [0]}, {"gate": "cx", "qubits": [0, 1]}],
    })


def test_bell_build_and_local_simulation(bell):
    circuit = core.build_circuit(bell, measured=False)
    assert circuit.num_clbits == 0
    assert np.allclose(Statevector.from_instruction(circuit).probabilities(), [.5, 0, 0, .5])
    measured = core.build_circuit(bell)
    assert measured.count_ops()["measure"] == 2
    result = core.simulate(bell, shots=1024, seed=7)
    assert result["simulation"] is True
    assert set(result["counts"]) == {"00", "11"}
    assert sum(result["counts"].values()) == 1024
    assert abs(result["counts"]["00"] - 512) < 90


@pytest.mark.parametrize("payload", [
    {"gate": "cx", "qubits": [0, 0]},
    {"gate": "cx", "qubits": [0]},
    {"gate": "h", "qubits": [0], "params": [1.0]},
    {"gate": "rx", "qubits": [0]},
    {"gate": "rx", "qubits": [0], "params": [float("nan")]},
    {"gate": "rx", "qubits": [0], "params": [float("inf")]},
    {"gate": "exec", "qubits": [0]},
    {"gate": "h", "qubits": [True]},
    {"gate": "h", "qubits": [-1]},
    {"gate": "h", "qubits": [0], "code": "arbitrary Python"},
])
def test_reject_invalid_gates(payload):
    with pytest.raises(ValidationError):
        core.Gate.model_validate(payload)


def test_reject_circuit_index_and_excessive_local_size():
    with pytest.raises(ValidationError, match="outside the circuit"):
        core.CircuitSpec(num_qubits=1, gates=[core.Gate(gate="h", qubits=[1])])
    with pytest.raises(core.QuantumToolError, match="20 qubits"):
        core.simulate(core.CircuitSpec(num_qubits=21), shots=1, seed=0)


@pytest.mark.parametrize("name,value", [
    ("IBM_QUANTUM_MAX_SHOTS", "abc"), ("IBM_QUANTUM_MAX_SHOTS", "0"),
    ("IBM_QUANTUM_MAX_SHOTS", "1000001"),
    ("IBM_QUANTUM_MAX_EXECUTION_SECONDS", "10801"),
])
def test_invalid_environment_budget(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(core.QuantumToolError, match=name):
        core.configuration()


@pytest.mark.parametrize("shots,seconds", [(0, 1), (8193, 1), (1, 61), (True, 1), (1, True)])
def test_budget_rejects_out_of_bounds_or_boolean(shots, seconds):
    with pytest.raises(core.QuantumToolError):
        core.validate_budget(shots, seconds)


def test_configuration_and_loading_do_not_initialize_sdk(monkeypatch, tmp_path):
    path = tmp_path / "synthetic-apikey.json"
    path.write_text(json.dumps({"apikey": "  synthetic-test-token  ", "description": "untrusted data"}))
    monkeypatch.setenv("IBM_QUANTUM_API_KEY_FILE", str(path))
    config = core.configuration()
    assert config["credential_configured"] is True
    assert "synthetic-test-token" not in json.dumps(config)
    assert str(path) not in json.dumps(config)
    assert core.load_api_key() == "synthetic-test-token"
    core.QiskitRuntimeService.assert_not_called()


def test_environment_key_precedes_file_without_reading_it(monkeypatch):
    monkeypatch.setenv("IBM_QUANTUM_API_KEY", " synthetic-env-token ")
    monkeypatch.setenv("IBM_QUANTUM_API_KEY_FILE", "/does/not/exist/synthetic.json")
    assert core.load_api_key() == "synthetic-env-token"


@pytest.mark.parametrize("contents", ["not JSON", "[]", '{"apikey":42}', '{"apikey":"  "}', '{"token":"synthetic-secret"}'])
def test_invalid_credential_file_is_safe(monkeypatch, tmp_path, contents):
    path = tmp_path / "synthetic-invalid.json"
    path.write_text(contents)
    monkeypatch.setenv("IBM_QUANTUM_API_KEY_FILE", str(path))
    with pytest.raises(core.QuantumToolError) as caught:
        core.load_api_key()
    assert str(path) not in str(caught.value)
    assert "synthetic-secret" not in str(caught.value)


def test_reject_blank_environment_key(monkeypatch):
    monkeypatch.setenv("IBM_QUANTUM_API_KEY", "   \n  ")
    with pytest.raises(core.QuantumToolError):
        core.load_api_key()


def test_reject_oversize_credential_file(monkeypatch, tmp_path):
    path = tmp_path / "synthetic-big.json"
    path.write_text(json.dumps({"apikey": "x" * 65536}))
    monkeypatch.setenv("IBM_QUANTUM_API_KEY_FILE", str(path))
    with pytest.raises(core.QuantumToolError, match="too large"):
        core.load_api_key()


def test_service_explicit_credentials_and_instance_isolation(monkeypatch):
    monkeypatch.setenv("IBM_QUANTUM_API_KEY", "synthetic-token")
    monkeypatch.setenv("IBM_QUANTUM_INSTANCE", "test-default-crn")
    factory = Mock(side_effect=lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(core, "QiskitRuntimeService", factory)
    first = core.service("test-crn-a")
    assert core.service("test-crn-a") is first
    second = core.service("test-crn-b")
    assert first is not second
    assert first.channel == "ibm_quantum_platform"
    assert first.token == "synthetic-token"
    assert first.instance == "test-crn-a"
    assert core.service().instance == "test-default-crn"
    assert factory.call_count == 3


def test_discovery_requires_unambiguous_instance_and_filters_fields(monkeypatch):
    discovered = Mock(return_value=[{"crn": "test-crn", "name": "Test", "plan": "open", "token": "must-not-return"}])
    monkeypatch.setattr(core, "service", Mock(return_value=SimpleNamespace(instances=discovered)))
    assert core.resolve_instance(None) == "test-crn"
    assert core.instances() == {"instances": [{"crn": "test-crn", "name": "Test", "plan": "open"}]}
    discovered.return_value = [{"crn": "a"}, {"crn": "b"}]
    with pytest.raises(core.QuantumToolError, match="Choose an instance"):
        core.resolve_instance(None)


@pytest.fixture
def runtime_backend(monkeypatch):
    """Real deterministic transpilation with an injected, nontrivial layout."""
    backend = GenericBackendV2(num_qubits=3, seed=1234)
    backend.status = Mock(return_value=SimpleNamespace(operational=True, status_msg="active", pending_jobs=0))
    backend_lookup = Mock(return_value=backend)
    monkeypatch.setattr(core, "service", Mock(return_value=SimpleNamespace(backend=backend_lookup)))
    circuits = []

    def compile_circuit(circuit):
        circuits.append(circuit)
        return transpile(circuit, backend=backend, initial_layout=[2, 0], optimization_level=0, seed_transpiler=1234)

    monkeypatch.setattr(core, "generate_preset_pass_manager", Mock(return_value=SimpleNamespace(run=compile_circuit)))
    return backend, circuits, backend_lookup


@pytest.mark.parametrize("primitive", ["sampler", "estimator"])
def test_dry_run_compiles_without_creating_or_submitting_primitive(monkeypatch, bell, runtime_backend, primitive):
    sampler = Mock(side_effect=AssertionError("Must not construct Sampler"))
    estimator = Mock(side_effect=AssertionError("Must not construct Estimator"))
    monkeypatch.setattr(core, "SamplerV2", sampler)
    monkeypatch.setattr(core, "EstimatorV2", estimator)
    args = dict(spec=bell, backend_name="test-backend", instance="test-crn", shots=128, max_execution_seconds=5, dry_run=True)
    if primitive == "sampler":
        result = core.sampler(**args)
    else:
        result = core.estimator(terms=[core.ObservableTerm(pauli="IZ")], **args)
    assert result["submitted"] is False
    assert result["dry_run"] is True
    assert result["physical_qubits"] == 3
    assert result["measured"] == (primitive == "sampler")
    sampler.assert_not_called()
    estimator.assert_not_called()


def test_sampler_sends_measurements_shots_and_execution_cap(monkeypatch, bell, runtime_backend):
    backend, circuits, lookup = runtime_backend
    submit = Mock(return_value=SimpleNamespace(job_id=lambda: "test-job-id"))
    factory = Mock(return_value=SimpleNamespace(run=submit))
    monkeypatch.setattr(core, "SamplerV2", factory)
    result = core.sampler(bell, "test-backend", "test-crn", 256, 7, False)
    assert result["submitted"] and result["job_id"] == "test-job-id"
    lookup.assert_called_once_with("test-backend")
    assert circuits[0].count_ops()["measure"] == 2
    options = factory.call_args.kwargs["options"]
    assert factory.call_args.kwargs["mode"] is backend
    assert options["max_execution_time"] == 7
    assert submit.call_args.kwargs == {"shots": 256}
    assert len(submit.call_args.args[0]) == 1


def test_estimator_maps_observable_and_keeps_circuit_unmeasured(monkeypatch, bell, runtime_backend):
    _, circuits, _ = runtime_backend
    submit = Mock(return_value=SimpleNamespace(job_id=lambda: "test-estimator-id"))
    factory = Mock(return_value=SimpleNamespace(run=submit))
    monkeypatch.setattr(core, "EstimatorV2", factory)
    result = core.estimator(bell, [core.ObservableTerm(pauli="IZ", coefficient=.5)], "test-backend", "test-crn", 512, 9, False)
    assert result["submitted"] is True
    assert circuits[0].num_clbits == 0
    assert "measure" not in circuits[0].count_ops()
    isa, mapped = submit.call_args.args[0][0]
    assert isa.num_qubits == mapped.num_qubits == 3
    # Logical qubit 0 is mapped to physical qubit 2, the leftmost Pauli bit.
    assert mapped.to_list() == [("ZII", .5 + 0j)]
    options = factory.call_args.kwargs["options"]
    assert options["default_shots"] == 512
    assert options["max_execution_time"] == 9
    assert options["resilience_level"] == 0


def test_invalid_estimator_observable_rejected_before_cloud(bell):
    with pytest.raises(core.QuantumToolError, match="one character per logical qubit"):
        core.estimator(bell, [core.ObservableTerm(pauli="Z")], "test-backend", "test-crn", 1, 1, False)
    with pytest.raises(core.QuantumToolError, match="1 to 100"):
        core.estimator(bell, [], "test-backend", "test-crn", 1, 1, False)
    with pytest.raises(ValidationError):
        core.ObservableTerm(pauli="ZZ", coefficient=float("nan"))
    core.QiskitRuntimeService.assert_not_called()


@pytest.mark.parametrize("primitive", ["sampler", "estimator"])
def test_offline_backend_cannot_submit(monkeypatch, bell, runtime_backend, primitive):
    backend, _, _ = runtime_backend
    backend.status.return_value.operational = False
    factory = Mock(side_effect=AssertionError("Should reject before primitive initialization"))
    monkeypatch.setattr(core, "SamplerV2", factory)
    monkeypatch.setattr(core, "EstimatorV2", factory)
    with pytest.raises(core.QuantumToolError, match="not operational"):
        if primitive == "sampler":
            core.sampler(bell, "test-backend", "test-crn", 1, 1, False)
        else:
            core.estimator(bell, [core.ObservableTerm(pauli="ZZ")], "test-backend", "test-crn", 1, 1, False)
    factory.assert_not_called()


def install_job(monkeypatch, status="QUEUED", result=None):
    job = SimpleNamespace(
        creation_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
        job_id=Mock(return_value="test-job"), status=Mock(return_value=status),
        primitive_id="sampler", instance="test-crn", result=Mock(return_value=result),
        cancel=Mock(), backend=Mock(side_effect=AssertionError("Job backend lookup can block")),
    )
    monkeypatch.setattr(core, "service", Mock(return_value=SimpleNamespace(job=Mock(return_value=job))))
    return job


def test_pending_poll_does_not_wait_or_fetch_backend(monkeypatch):
    job = install_job(monkeypatch)
    result = core.get_job("test-job", "test-crn", True, 0, 10)
    assert result["status"] == "QUEUED" and result["results_ready"] is False
    job.result.assert_not_called()
    job.backend.assert_not_called()


def test_wait_timeout_is_pending_and_bounded(monkeypatch):
    job = install_job(monkeypatch)
    job.result.side_effect = RuntimeJobTimeoutError("synthetic timeout")
    result = core.get_job("test-job", "test-crn", True, 3, 10)
    assert result["results_ready"] is False
    assert "without resubmitting" in result["message"]
    job.result.assert_called_once_with(timeout=3, poll_interval=1)
    job.cancel.assert_not_called()


@pytest.mark.parametrize("status", ["ERROR", "CANCELLED"])
def test_terminal_failure_does_not_try_result(monkeypatch, status):
    job = install_job(monkeypatch, status=status)
    result = core.get_job("test-job", "test-crn", True, 3, 10)
    assert result["status"] == status
    job.result.assert_not_called()


def test_results_use_register_names_and_account_for_truncated_counts(monkeypatch):
    pubs = PrimitiveResult([
        SamplerPubResult(DataBin(custom=BitArray.from_counts({"00": 6, "11": 3, "01": 1}))),
        PubResult(DataBin(evs=np.array([.5, -.25]), stds=np.array([.01, .02]))),
    ])
    job = install_job(monkeypatch, status="DONE", result=pubs)
    result = core.get_job("test-job", "test-crn", True, 0, 2)
    assert result["results_ready"] is True
    data = result["pubs"][0]["data"]["custom"]
    assert data == {"counts": {"00": 6, "11": 3}, "shots": 10, "num_bits": 2, "truncated": True, "omitted_shots": 1}
    assert result["pubs"][1]["data"] == {"evs": [.5, -.25], "stds": [.01, .02]}
    job.result.assert_called_once_with(timeout=1, poll_interval=1)
    json.dumps(result, allow_nan=False)


def test_parameter_sweep_is_not_silently_aggregated():
    bits = BitArray.from_counts([{"0": 10}, {"1": 10}])
    data = core.summarize_result([SamplerPubResult(DataBin(register=bits))], 10)[0]["data"]["register"]
    assert data["shape"] == [2]
    assert "counts" not in data
    assert "not aggregated" in data["message"]


@pytest.mark.parametrize("status,expected", [("DONE", False), ("ERROR", False), ("CANCELLED", False), ("QUEUED", True)])
def test_cancellation_only_for_unfinished_jobs(monkeypatch, status, expected):
    job = install_job(monkeypatch, status=status)
    result = core.cancel_job("test-job", "test-crn")
    assert result["cancellation_requested"] is expected
    assert job.cancel.call_count == int(expected)
