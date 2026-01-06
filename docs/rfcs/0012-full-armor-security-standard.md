# RFC-0012: The 'Full Armor' Security Standard (Surgical Shielding)

> **Status**: DRAFT  
> **Author**: Architect (ID-LOCK-001)  
> **Created**: 2026-01-06  
> **Target Version**: v0.6.2  
> **Branch**: `phase-6.2/security-hardening`  
> **Parent Documents**: RFC-0010, RFC-0011

---

## 1. Executive Summary

A previous "Full Armor" security update introduced by the development team implemented a "Brute Force Deny" strategy. While this achieved theoretical security, it resulted in a **100% regression rate** in functional tests due to "Environmental Suffocation" and "Path Over-restriction."

RFC-0012 establishes the **Surgical Shielding Standard**, transitioning from "Deny by Default (Brute)" to "Verified Isolation (Surgical)."

---

## 2. The "Three Sins" of Brute Force Security (Audit Findings)

| Sin | Mechanism | Failure Mode |
|-----|-----------|--------------|
| **Environment Suffocation** | `env_clear()` | Workers lack essential vars (PATH, VIRTUAL_ENV), leading to `ModuleNotFoundError`. |
| **Seatbelt Death Spiral** | Restrictive `/var` and `/tmp` blocking | Prevented internal Python shared memory and socket communication. |
| **Workspace Collision** | Fixed Zygote Socket paths | Multiple Velo instances in different projects conflict on the same socket file. |

---

## 3. Proposed Hardening Strategy

### 3.1 Surgical Environment Management
Replace `env_clear()` with a **Strict Whitelist + Target Blacklist** model.

**Whitelist (Mandatory for Worker Life):**
- `PATH`, `VIRTUAL_ENV`, `PYTHONDONTWRITEBYTECODE`, `PYTHONUNBUFFERED`, `LANG`, `LC_ALL`, `TERM`.
- Project-specific vars defined in `pyproject.toml`.

**Blacklist (Dangerous):**
- `LD_PRELOAD`, `DYLD_INSERT_LIBRARIES`, `PYTHONPATH` (if external to project).

### 3.2 Dynamic Path Isolation
Use **Canonical Workspace Scoping** instead of hardcoded filesystem blocks.
- Every read/write must be within `realpath(PROJECT_ROOT)`.
- Explicit permissions for `/tmp/velo-<workspace-hash>/`.

### 3.3 Unique Zygote Identity
Zygote sockets must be uniquely keyed to the project to prevent "Ghost Zygote" hijacking.
- **Path Hash**: `SOCKET_PATH = /tmp/velo-zygote-<SHA256(canonical_project_path)>.sock`
- **Ownership (SEC-Expert-001)**: Must use `O_EXCL` during bind and `chmod 600` immediately after creation to prevent multi-user hijacking.

### 3.4 Path Sanitization (SEC-Expert-002)
- **Canonicalization**: All path checks (whitelist/blacklist) MUST use `fs::canonicalize` before comparison to prevent symlink-based escape.
- **Root Enforcement**: Every subprocess read/write must remain within the canonical project root.

---

## 4. Verification Plan (The "Executioner" Suite)

We will implement `test_sec_shield.py` to target the specific failure modes:

| Test ID | Name | Focus |
|---------|------|-------|
| **SEC-SHIELD-001** | `test_env_oxygen_level` | Verify workers retain `VIRTUAL_ENV` and `PATH`. |
| **SEC-SHIELD-002** | `test_path_integrity` | Verify `../../etc/passwd` is blocked while `./local_module` is allowed. |
| **SEC-SHIELD-003** | `test_zygote_isolation` | Run two Velo instances in parallel; verify no socket collisions. |
