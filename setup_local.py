"""Install this MCP server locally; optionally register it with Codex.

No credential contents are read or copied by this script.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-key-file", required=True, type=Path)
    parser.add_argument("--instance", help="Optional IBM Quantum instance CRN")
    parser.add_argument("--register-codex", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    credential = args.api_key_file.expanduser().resolve(strict=True)
    environment = root / ".venv"
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    uv = shutil.which("uv")
    if not python.exists():
        if uv:
            subprocess.run([uv, "venv", "--python", sys.executable, str(environment)], check=True)
        else:
            subprocess.run([sys.executable, "-m", "venv", str(environment)], check=True)
    installer = ([uv, "pip", "install", "--python", str(python)] if uv else
                 [str(python), "-m", "pip", "install"])
    subprocess.run([*installer, "-r", str(root / "requirements.lock")], check=True)
    subprocess.run([*installer, "--no-deps", "--editable", str(root)], check=True)
    variables = {"IBM_QUANTUM_API_KEY_FILE": str(credential)}
    if args.instance:
        variables["IBM_QUANTUM_INSTANCE"] = args.instance
    entry = {"command": str(python), "args": ["-m", "ibm_quantum_agent"], "env": variables}
    (root / ".mcp.json").write_text(json.dumps({"mcpServers": {"ibm-quantum": entry}}, indent=2) + "\n")
    print("Installed IBM Quantum agent tools. Local MCP config: " + str(root / ".mcp.json"))
    if args.register_codex:
        codex = shutil.which("codex")
        if not codex:
            raise SystemExit("Codex CLI is not on PATH; use .mcp.json in your MCP client.")
        command = [codex, "mcp", "add", "ibm-quantum"]
        for name, value in variables.items():
            command.extend(["--env", f"{name}={value}"])
        subprocess.run([*command, "--", str(python), "-m", "ibm_quantum_agent"], check=True)
        print("Registered ibm-quantum with Codex. Start a new task to load its tools.")


if __name__ == "__main__":
    main()
