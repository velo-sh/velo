# QA Handoff: Phase 7 Architectural Verification (Prosecutor Suite)

**Role**: QA Lead / Security Auditor
**Task**: Design-First Verification for RFC-0018 & RFC-0019
**Context**: The Architecture for Phase 7 is LOCKED. This document defines the "Prosecutor Suite" requirements that MUST be implemented as automated tests before production code is written.

## 1. Core Verification Scenarios

### 1.1 [RSGI-001] Handshake & Lifecycle
*   **Goal**: Verify the RSGI-Velo MessagePack handshake.
*   **Test Logic**:
    1.  Spawn a mock RSGI worker that sends a malformed `READY` message.
    2.  **Assert**: Velo Master MUST SIGKILL the worker and log a `ProtocolError`.
    3.  Spawn a mock RSGI worker that sends a valid `READY` -> Receive `AUTH_OK`.
    4.  **Assert**: Worker ID and Capabilities match the Host's expectations.

### 1.2 [SEC-07-001] IPC Atomic Isolation (Linux/macOS)
*   **Goal**: Verify the remediation of the socket race condition.
*   **Test Logic**:
    1.  On Linux: Verify that the Zygote/RSGI socket is an **Abstract Namespace Socket** (no file on disk).
    2.  On macOS: Verify that the socket directory is created with `0o700` via `mkdtemp`.
    3.  **Attack**: Pre-create a conflicting directory in `/tmp`.
    4.  **Assert**: Velo MUST detect the collision and either use an alternative name or Abort with a Security Warning.

### 1.3 [TAINT-001] Entropy Re-randomization (RFC-0013)
*   **Goal**: Ensure zero-entropy inheritance between Zygote and Worker.
*   **Test Logic**:
    1.  Spawn two workers from the same Zygote.
    2.  Capture `secrets.token_hex(32)` from both.
    3.  **Assert**: Tokens MUST NOT match.
    4.  **Assert**: `os.urandom(1)` triggers a fresh kernel entropy pull.

### 1.4 [CUSTODY-001] Toolchain Integrity (RFC-0018)
*   **Goal**: Verify embedded `uv` forensic verification.
*   **Test Logic**:
    1.  Modify the temporary extracted `uv` binary (simulate bit-rot or tampering).
    2.  Trigger a Velo operation that requires `uv`.
    3.  **Assert**: Velo MUST perform a BLAKE3 check and re-extract the fresh binary from its own resources.

---

## 2. Success Criteria
*   **Security**: Zero "Inherited FD" leaks to workers (verify via `test_sec_shield.py:SEC-SHIELD-004` logic).
*   **Performance**: RSGI handshake latency < 5ms.
*   **Hygiene**: No stale sockets left in `@velo-*` (Linux) or `mkdtemp` dirs (macOS) after clean exit.

## 3. Artifacts for Reference
*   [RFC-0018: Integrated Custody](../rfcs/0018-integrated-custody.md)
*   [RFC-0019: Native Sovereignty](../rfcs/0019-native-sovereignty.md)
*   [Velo-uv Architecture Overview](./velo_uv_architecture_overview.md)
