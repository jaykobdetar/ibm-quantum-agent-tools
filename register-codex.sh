#!/usr/bin/env bash
set -euo pipefail
codex mcp add ibm-quantum --env IBM_QUANTUM_API_KEY_FILE=/home/jaykob/Downloads/apikey.json -- /home/jaykob/Documents/Codex/2026-09-07/thi/outputs/ibm-quantum/.venv/bin/python -m ibm_quantum_agent
