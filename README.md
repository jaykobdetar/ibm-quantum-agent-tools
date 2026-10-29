# IBM Quantum agent tools

A local MCP server that lets an AI agent use IBM Quantum through typed tools. It uses IBM's Qiskit Runtime SDK and the official MCP Python SDK. It can run from Codex or another MCP client that supports local stdio servers.

The API key stays in the original credential file. The server reads only its `apikey` field, keeps it in process memory, and sends it through IBM's authenticated SDK connection. Other JSON fields are ignored. No credential value is stored in source, tool arguments, tool responses, or the MCP configuration. Do not delete the credential file while this setup is in use.

## Quick start without IBM credentials

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install --no-deps -e .
.venv/bin/python examples/mcp_client.py
```

On Windows use `.venv\Scripts\python.exe` instead. Installation downloads dependencies; the example itself runs locally and submits no IBM job. For tests, install `.[test]` in the same environment and run `python -m pytest -q` with that environment's Python.

## Local installation for IBM access

Python 3.11+ is required. With this folder in a permanent location, run:

```bash
python3 setup_local.py --api-key-file /absolute/path/to/apikey.json --register-codex
```

The script creates `.venv`, installs the pinned dependencies, generates `.mcp.json` with absolute paths, and registers `ibm-quantum` through `codex mcp add`. It prefers `uv` if available and otherwise uses Python's `venv` and `pip`. Omit `--register-codex` to generate configuration for another MCP client. Optional `--instance CRN` fixes the instance to use. Run setup again if you move the folder or credential file.

Start a new Codex task after registration. Example request:

> Use the IBM Quantum tools to list my quantum computers, then simulate a Bell pair locally with 1024 shots.

For another MCP client, merge the generated `.mcp.json` entry into its MCP server configuration. Run `python examples/mcp_client.py` with this environment's Python for a working agent-side client example.

No Codex plugin manifest is included. The setup helper generates a local `.mcp.json`; rerun setup on a new machine. Direct MCP registration does not require a plugin marketplace entry. The server communicates over stdio and is not a public HTTP service.

## Tools

| Tool | Purpose |
| --- | --- |
| `quantum_configuration` | Inspect credential configuration presence and configured limits without authentication. |
| `quantum_instances` | Authenticate and discover accessible IBM instances. |
| `quantum_backends` | List QPUs, availability, qubit counts, and queue lengths. |
| `quantum_simulate` | Run a circuit locally, up to 20 qubits, without an IBM call. |
| `quantum_preview` | Transpile a circuit for a selected QPU and inspect depth/gates. |
| `quantum_run_sampler` | Preview or submit a circuit and measure all qubits. |
| `quantum_run_estimator` | Preview or submit one weighted Pauli-sum expectation value. |
| `quantum_jobs` | List recent jobs, with pagination and pending-state filtering. |
| `quantum_job` | Read status and retrieve counts or expectation values. |
| `quantum_cancel_job` | Request cancellation of one unfinished job. |

When exactly one instance is accessible it is selected automatically. With multiple instances, pass an instance CRN returned by `quantum_instances`, or configure `IBM_QUANTUM_INSTANCE`. Backend names must come from discovery; available systems can change.

## Circuit format

Pass JSON, not Python code. Indices start at zero and gate angles are numeric radians. Circuits contain up to 256 logical qubits and 10,000 gates. Supported gates are:

```
id x y z h s sdg t tdg sx sxdg
rx ry rz p u
cx cy cz ch swap ccx cswap
cp crx cry crz rxx ryy rzz barrier
```

Control qubits precede target qubits. `u` takes three parameters, rotation/phase gates take one, and the other gates take none. Distinct gate qubits and argument counts are validated. `barrier` accepts one or more qubits. This initial version supports fully bound, unitary circuits with final measurements. It does not accept arbitrary Python, QASM files, dynamic control flow, reset, custom classical-register layouts, or parameter sweeps.

Call `quantum_simulate` with:

```json
{
  "circuit": {
    "num_qubits": 2,
    "gates": [
      {"gate": "h", "qubits": [0]},
      {"gate": "cx", "qubits": [0, 1]}
    ]
  },
  "shots": 1024,
  "seed": 1234
}
```

Counts use bitstrings with qubit 0 at the right. Sampler automatically measures every qubit into a register named `meas`. For `quantum_run_estimator`, supply `observable`, for example `[{"pauli":"ZZ","coefficient":1.0}]` for a two-qubit circuit. Pauli labels also place qubit 0 at the right. The tool maps observables to the transpiled physical-qubit layout.

## Hardware workflow

1. Discover the instance and backend.
2. Simulate a small circuit locally.
3. Call `quantum_run_sampler` or `quantum_run_estimator` with the circuit, backend, and default `dry_run: true` to preview.
4. When hardware execution is requested, repeat with `dry_run: false`. This consumes IBM quantum usage and can incur charges under the selected plan.
5. Keep the returned `job_id`. Use `quantum_job` to poll it and obtain results. Do not submit again while waiting. On an ambiguous submission error, inspect `quantum_jobs` and IBM's dashboard before retrying; there is no submission idempotency guarantee.

Default job limits are 8,192 sampler shots and 60 QPU execution seconds. The default requested shot count is 1,024. Estimator `shots` is the default per measurement configuration, so total estimator shots can be larger. The runtime limit caps quantum execution time; it is not a dollar budget, monthly budget, or queue timeout. These per-job limits do not restrict the number of jobs an agent may submit. The tool exposes mutation annotations to the client and defaults submission tools to preview, but client/user authorization remains the agent host's responsibility.

| Server environment variable | Meaning |
| --- | --- |
| `IBM_QUANTUM_API_KEY_FILE` | Path to an IBM JSON export containing `apikey`. Recommended credential source. |
| `IBM_QUANTUM_API_KEY` | Alternative raw credential supplied by the process environment; takes precedence. |
| `IBM_QUANTUM_INSTANCE` | Optional default instance CRN. |
| `IBM_QUANTUM_MAX_SHOTS` | Per-call shot setting ceiling; default 8192, maximum 1000000. |
| `IBM_QUANTUM_MAX_EXECUTION_SECONDS` | Per-job QPU execution ceiling; default 60, maximum 10800. |

If you lower the runtime ceiling below 60, also pass a corresponding `max_execution_seconds` to submission calls. Restart the server after changing credentials or environment configuration. Backend `operational` does not always mean a system is currently processing jobs; consult its status message.

`quantum_job` defaults to no queue wait. `wait_seconds` permits up to 30 seconds of SDK polling, separate from HTTP request/download timeouts. Results include at most 20 PUBs, the requested number of highest-count bitstrings (default 256), and at most 2,000 values in array fields. Truncation is reported. Parameter-sweep register shapes from jobs created elsewhere are reported without aggregating counts. For full results from large or externally created jobs, use the Qiskit Python API.

## Validation

```bash
.venv/bin/python -m pip install 'pytest>=8,<9'
.venv/bin/python -m pytest tests -q
.venv/bin/python examples/mcp_client.py
```

Tests use local simulation, fake IBM services, and a real MCP stdio subprocess. They do not use your API key or submit hardware jobs. No live IBM verification report is included, and this release review did not authenticate with IBM. See [RELEASE_READINESS.md](RELEASE_READINESS.md) for the checks actually performed and remaining blockers.

## References

- [IBM account initialization](https://quantum.cloud.ibm.com/docs/en/guides/initialize-account)
- [IBM Qiskit Runtime service](https://quantum.cloud.ibm.com/docs/en/api/qiskit-ibm-runtime/qiskit-runtime-service)
- [SamplerV2](https://quantum.cloud.ibm.com/docs/en/api/qiskit-ibm-runtime/sampler-v2) and [EstimatorV2](https://quantum.cloud.ibm.com/docs/en/api/qiskit-ibm-runtime/estimator-v2)
- [IBM execution limits](https://quantum.cloud.ibm.com/docs/en/guides/max-execution-time)
- [Official MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk/tree/v1.x)
- [Codex MCP setup](https://developers.openai.com/codex/mcp/)

Pinned to the maintained MCP 1.x API to keep `FastMCP`/`ClientSession` compatibility explicit. This is a local integration, not an IBM-endorsed product.

## Status, provenance, and license

Experimental local integration, version 0.1.0. This repository began as a source-only preservation snapshot on 2026-10-29 of an AI-assisted local project. Original development history and live-service evidence were not imported. The retained snapshot is not evidence of independent authorship, scientific validation, or hardware performance. There are no bundled datasets, model weights, or credentials.

This project is distributed under the [MIT License](LICENSE), added with owner authorization on 2026-10-29. The owner stated that all project code was created by AI and authorized MIT licensing. This records the owner’s assertion and permission, not an independent determination of copyright ownership or third-party provenance. Dependencies retain their own licenses; dependency pins do not establish ownership of this project. IBM and Qiskit names identify the service and SDKs used; this project is not endorsed by IBM.

Preview/transpilation still needs IBM access to retrieve backend information. Only configuration inspection and local simulation work without credentials. Per-job execution and shot ceilings are **not a global spend cap**: repeated submissions can accumulate usage and charges. Keep authorization controls in the MCP host. Review tool output before sharing it, since discovered instance names, CRNs, and job metadata can identify account resources.

See the [release checklist](RELEASE_READINESS.md) before changing repository visibility.
