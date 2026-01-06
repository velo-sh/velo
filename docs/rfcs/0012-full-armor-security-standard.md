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
Workers MUST NOT be starved of essentials, but dangerous vectors MUST be severed.
- **Mandatory Whitelist**: `PATH`, `VIRTUAL_ENV`, `PYTHONDONTWRITEBYTECODE`, `PYTHONUNBUFFERED`, `LANG`, `LC_ALL`, `TERM`, `TZ` (Verified Timezone).
- **Conditional Whitelist**: `RUST_BACKTRACE` (Dev mode only).
- **Dangerous Blacklist (Critical)**: 
    - `LD_PRELOAD`, `DYLD_INSERT_LIBRARIES` (Injection).
    - `LD_LIBRARY_PATH`, `DYLD_LIBRARY_PATH` (Search path hijacking).
    - `PYTHONPATH` (Override), `PYTHONHOME` (Runtime hijacking).

### 3.2 Dynamic Path Isolation
Use **Canonical Workspace Scoping** instead of hardcoded filesystem blocks.
- Every read/write must be within `realpath(PROJECT_ROOT)`.
- Explicit permissions for `/tmp/velo-<workspace-hash>/`.

### 3.3 Unique Zygote Identity (Anti-Hijack)
- **Linux**: Mandatory use of **Abstract Namespace Sockets** (`@velo-zygote-<hash>`).
- **macOS (Atomic Permissions)**:
    - Use `umask(077)` **before** calling `mkdtemp` and `bind`.
    - Ensure the randomized temporary directory and the socket itself are created with atomic restricted permissions (700/600).
- **Windows**: Use **Named Pipes** with strict Security Descriptors.

### 3.4 Path Sanitization (TOCTOU Resistance)
To prevent Time-of-Check to Time-of-Use attacks:
- **Capability-Based I/O**: Use FD-based operations (`openat`, `fstat`) provided by crates like `cap-std`.
- **Verification Logic**: 
    1. Open the file/directory.
    2. Call `fstat` on the resulting FD.
    3. Verify `st_dev` and `st_ino` (Device/Inode) are descendants of the cached, verified `PROJECT_ROOT`.
- **Performance & Cache**: 
    - Cache the `PROJECT_ROOT` canonical path and device ID at startup.
    - **Proactive Validation**: Canonicalize and validate `PATH`/`PYTHONPATH` entries **once** at startup.
    - **Fail-Fast**: If `fs::canonicalize` fails (e.g., cyclic symlink or permission error) during startup validation, Velo MUST **Abort Startup** immediately, not ignore the entry.

### 3.5 Environment Provenance Guard (SEC-ENV-001)
- **Value Origin Validation**: It is not enough to whitelist `PATH`. The contents must be audited.
- **Rules**:
    - Every entry in `PATH` or `PYTHONPATH` must be canonicalized.
    - Entries are only allowed if they reside within `realpath(PROJECT_ROOT)`, the active `VIRTUAL_ENV`, or a set of hardcoded trusted system prefixes (e.g., `/usr/bin`, `/bin`).
- **Fail-Closed**: Any out-of-bounds entry will trigger an immediate startup block.

### 3.6 File Descriptor (FD) & Signal Hygiene (SEC-FS-002)
- **FD Purge (Performance Optimized)**:
    - **Linux (5.9+)**: Mandatory use of `close_range(3, ~0, CloseRange::CLOEXEC)`.
    - **Fallback**: Read `RLIMIT_NOFILE` to determine the actual upper bound; loop and close 3..MAX. **Never** use a hardcoded 4096 limit.
- **Escape Blocking**:
    - Explicitly block lookups for `/proc/self/fd/` and similar pseudo-filesystems.
- **Signal Mask Reset**:
    - In `pre_exec`, the global signal mask MUST be reset (unblocked) to ensure Workers respond correctly to `SIGTERM`/`SIGKILL`.

### 3.7 Zygote Peer Authentication (Kernel-Enforced)
Prefer OS-level verification over application-layer HMAC where available.
- **Linux**: Use `SO_PEERCRED` to verify UID/GID matches the Zygote owner.
- **macOS/BSD**: Use `getpeereid` or `LOCAL_PEERCRED`.
- **Windows**: Use Named Pipe Security Descriptors + `GetNamedPipeClientProcessId`.
- **Fallback**: Challenge-Response HMAC(Nonce, Secret) if kernel-level peer IDs are unavailable.

---

## 4. Failure Policy: Fail-Closed
Velo adopts the **"Fail-Fast, Fail-Closed"** iron rule for security:
- **Detection -> Termination**: Any sandbox violation or validation failure results in immediate process termination (`SIGKILL`).
- **No Silents**: All security events must be logged with high severity (CRITICAL) for forensic audit.

---

## 5. Cross-Platform Security Invariants

The "Surgical Shielding" model is designed for universal enforcement while leveraging platform-specific features:

### 5.1 Linux (The Hardened Standard)
- **Abstract Sockets**: For Linux, we will evaluate moving Zygote sockets from `/tmp` to **Abstract Namespace Sockets** (`@velo-zygote-<hash>`). These do not leave files on disk and are automatically cleaned up.
- **Procfs Protection**: The sandbox must specifically allow read access to `/proc/self/` for Python's own introspection while blocking access to `/proc/` root to prevent process-tree discovery.

### 5.2 macOS (FSEvents & Lifecycle)
- **FSEvents Scoping**: File watching (`notify`) must be restricted to the canonicalized workspace to avoid over-privileged system-wide monitoring.
- **Sandbox Compliance**: Design must be compatible with future macOS App Sandbox requirements if Velo is distributed via official channels.

### 5.3 Windows (UNC & Path Extremes)
- **UNC Path Handling**: On Windows, `canonicalize()` often adds the `\\?\` prefix. The `PathShield` must handle these prefixes correctly to prevent comparison failures.
- **Path Length**: Windows MAX_PATH limits must be handled; the shield must ensure that long-path support is active so attackers cannot hide files in deep, un-shielded subdirectories.

---

## 6. Verification Plan (The "Executioner" Suite)

We will implement `test_sec_shield.py` to target the specific failure modes:

| Test ID | Title | Purpose |
|:---|:---|:---|
| **SEC-SHIELD-001** | Env Oxygen Level | Verify workers retain essential environment variables. |
| **SEC-SHIELD-002** | Path Integrity | Verify path blocking and allowance within project scope. |
| **SEC-SHIELD-003** | Zygote Isolation | Verify no socket collisions between parallel Velo instances. |
| **SEC-SHIELD-004** | FD Escape Attack | Attempt to use `openat` with inherited FDs to bypass shield. |
| **SEC-SHIELD-005** | Env Provenance | Attempt to inject out-of-bounds paths into `PATH` whitelist. |
| **SEC-SHIELD-006** | Peer Hijack | Attempt connection to Zygote socket from unauthorized PID. |
