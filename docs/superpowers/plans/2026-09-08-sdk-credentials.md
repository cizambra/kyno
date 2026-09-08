# Kyno SDK Credentials Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the SDK use the CLI's profile and credential model without importing Elastic/Core code.

**Architecture:** Shared wire contracts live in `src/kyno/wire/`; profile and credential resolution moves to MIT-owned `src/kyno/config/`. Core may import both MIT subtrees, while SDK and adapters import only MIT code. The SDK resolves a connection once, rejects conflicting sources, and requires reconnect after credential rotation.

**Tech Stack:** Python 3.11+, pytest, dataclasses, `configparser`, existing MCP session runner.

---

### Task 1: Extract the MIT wire contract

**Files:**
- Create: `src/kyno/wire/LICENSE`
- Create: `src/kyno/wire/__init__.py`
- Create: `src/kyno/wire/errors.py`
- Create: `src/kyno/wire/models.py`
- Modify: `src/kyno/models.py`
- Modify: `src/kyno/errors.py`
- Modify: SDK and Core import sites that use moved names
- Modify: `tests/checks/test_licensing.py`
- Create: `tests/checks/test_import_boundaries.py`
- Modify: affected unit and integration tests

- [x] Write tests proving MIT subtrees can import only MIT code and that the wire symbols preserve current behavior.
- [x] Run the focused checks and confirm they fail because `wire/` does not exist and SDK imports Elastic modules.
- [x] Move portable models and domain errors into `wire/` and update all imports without changing behavior.
- [x] Run the focused checks and the affected model/SDK tests.
- [x] Inspect the diff for accidental public-surface or license changes.

### Task 2: Extract profile resolution into MIT config

**Files:**
- Create: `src/kyno/config/__init__.py`
- Create: `src/kyno/config/profiles.py`
- Create: `src/kyno/config/LICENSE`
- Modify: `src/kyno/profiles.py` callers and CLI imports
- Modify: `tests/core/unit/test_profiles.py`
- Create: `tests/surface/unit/test_profile_config.py`
- Modify: `tests/checks/test_licensing.py`

- [x] Move the read-only resolver and its value objects into `kyno.config` while preserving CLI file formats.
- [x] Keep filesystem and environment lookup out of `wire/`.
- [x] Prove the SDK can import config without loading Elastic/Core modules.

### Task 3: Replace SDK environment discovery

**Files:**
- Modify: `src/kyno/sdk/__init__.py`
- Modify: `src/kyno/sdk/client.py`
- Modify: `tests/surface/unit/test_sdk.py`
- Modify: `tests/surface/unit/test_client.py`

- [x] Add failing tests for default/named profiles, explicit URL/token pairs, invalid combinations, and fail-fast errors.
- [x] Remove `KynoBinding.from_env()` and the SDK-owned `KYNO_URL`/`KYNO_TOKEN` behavior.
- [x] Resolve profile endpoints once at `connect()` and require reconnect after rotation.
- [x] Keep tokens out of representations and errors.

### Task 4: Centralize endpoint normalization and update documentation

**Files:**
- Modify: `src/kyno/config/profiles.py`
- Modify: `src/kyno/remote.py`
- Modify: `README.md`
- Modify: `docs/adapters.md`
- Modify: `tests/test_remote_cli.py`
- Modify: `tests/surface/e2e/test_adapter_server_roundtrip.py`

- [x] Add one normalization helper for profile base URLs and explicit MCP endpoints.
- [x] Reject `profile=` combined with `url=` and require `token=` with explicit `url=`.
- [x] Update examples to use profiles or application-owned values.
- [ ] Verify SDK-to-server-to-adapter round trips.

### Task 5: Validate the complete boundary

**Files:**
- Modify: `tests/checks/test_import_boundaries.py`
- Modify: `tests/surface/e2e/test_adapter_server_roundtrip.py`
- Modify: `tests/surface/unit/test_client.py`

- [ ] Cover missing/default/named profiles, malformed files, blank/unset `${VAR}`, endpoint normalization, token redaction, and reconnect behavior.
- [ ] Run `python -m pytest -q` and the repository's formatting checks.
- [ ] Review the final diff and record validation evidence in the PR description.
