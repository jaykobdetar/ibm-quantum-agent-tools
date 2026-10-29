# IBM Quantum agent tools

Local MCP tools for IBM Quantum through the official Qiskit Runtime SDK.

## What is preserved

Contains the tool server, setup/registration helpers, typed requests, examples and tests.

This is a private, source-only preservation snapshot of the user-selected local project **P0698**, prepared on 2026-10-29. The user described these projects as arising from AI-assisted work. This note records archival provenance, not a claim about authorship or scientific validity. The original Git history was not imported.

## Setup and dependencies

Python 3.11+; pinned requirements.lock and pyproject.toml are included. Use an isolated environment. IBM account access is an external prerequisite.

## Entry points

src/ibm_quantum_agent/__main__.py and the ibm-quantum-agent entrypoint run the server. setup_local.py and register-codex.sh are optional machine-configuration helpers; inspect before using.

## Status and limitations

Credential files and generated local registration/configuration are intentionally excluded. This backup does not authorize paid quantum jobs or claim successful service access.

No project code, installation steps or tests were executed during preservation. Existing README/source claims have not been independently revalidated. For the original project documentation, see [README.source.md](README.source.md).

## Backup scope

Only the reviewed text source, tests, selected manifests/configurations and technical documentation are included. Credentials, .env/auth configuration, raw conversations, personal documents, live state, model weights, dependencies, generated datasets and bulky outputs were excluded. Local originals remain in place until separately approved and safe to remove. A successful source backup alone is not proof that all runtime data or experiment evidence has been preserved.
