# Release readiness review

Review date: 2026-10-29. Keep the repository private pending owner review.

## Completed

- [x] Reviewed all tracked source, manifests, examples, tests and documentation, plus the single imported commit (`1e22ff6`). Original pre-import history is unavailable.
- [x] Replaced machine-specific registration paths with a portable wrapper accepting `--api-key-file`; no actual credentials were read.
- [x] Removed unsupported claims that a plugin manifest and live verification report are included.
- [x] Documented credential-free local setup, typed circuit limits, dry-run semantics, per-job limits versus aggregate spending, status and provenance.
- [x] Added README package metadata and source-distribution inclusion of helpers, lockfile, examples and release notes.
- [x] Expanded ignores for build artifacts, test caches and common credential filenames. Ignore rules cannot guarantee that secrets are never committed.
- [x] Preserved typed JSON circuits, default dry runs, bounded result output and sanitized upstream errors; no runtime behavior changes were needed for this review.

## Validation

Isolated Linux CPython 3.13.13 environment, official PyPI dependencies from `requirements.lock`, pytest 8.4.2, build 1.6.1 and setuptools 84.2.1. No IBM credentials, authenticated IBM checks, paid services or hardware submissions were used.

- `python -m pytest -q`: **52 passed** (4.45 seconds), covering validation, local simulation, fake SDK interactions, dry-run behavior, execution caps, sanitized errors and a real stdio MCP subprocess.
- `python examples/mcp_client.py`: discovered all 10 tools and returned 1,024 local Bell shots (`00`: 510, `11`: 514).
- `python -m build --no-isolation`: source distribution and wheel built successfully; archive inspection confirmed the helpers, lockfile, example and release notes are included and wheel metadata contains the README.
- Installed the built wheel with `uv pip install --offline --no-deps --reinstall dist/ibm_quantum_agent-0.1.0-py3-none-any.whl`; reran all tests: **52 passed** (2.31 seconds). Repeated the MCP example successfully from the wheel installation.
- `uv pip check`: all 61 installed packages compatible.
- Two restricted-sandbox runs each returned 51 passed and one MCP stdio initialization timeout (30-second request timeout). The complete suite passed outside that sandbox with the same environment and wheel; no source workaround was made. The initial default uv cache was read-only in the sandbox; a task-specific `/tmp` cache allowed offline wheel installation.
- `bash -n register-codex.sh` and `bash register-codex.sh --help`: passed without installation or registration.

Dependency installation requires network access. Tests and the example exercise local behavior; they are not evidence of IBM account access or live API compatibility. Only Python 3.13 on Linux was tested, despite the declared Python 3.11+ support. Dependency pins are version pins, not cryptographic hashes or a vulnerability audit.

## Privacy and provenance findings

Manual review of tracked text plus a history pattern scan for private-key headers, GitHub token formats, AWS access-key IDs and personal filesystem paths found no actual credential values. Synthetic tokens in tests are intentionally fake. This is a bounded review, not a guarantee of absence of secrets.

The initial commit contains a personal home-directory path and credential-file location in `register-codex.sh`. The new file removes these paths, but ordinary commits do not remove history. No history was rewritten. Commit attribution uses a GitHub noreply address. The repository itself is a source snapshot, with no upstream development history or verified ownership record imported.

## Owner decisions before public release

- [ ] Confirm source ownership and any third-party provenance; choose and add a license with accurate notices. No license was invented during cleanup.
- [ ] Review the historical personal path and explicitly accept its disclosure, or arrange a separately authorized history cleanup before publication. Do not publish on the assumption that the new commit removes it from history.
- [ ] Review and merge the draft changes, then separately authorize a visibility change. This task does not change visibility.
- [ ] Optionally validate supported Python/OS combinations and a live read-only IBM connection. Hardware validation would require separate explicit authorization and is not needed for local smoke tests.
