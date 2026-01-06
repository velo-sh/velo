# SOP-001: Master Architecture Lifecycle Standard

**Ownership**: Architect Force (ID-LOCK-001)
**Version**: 2.0 (2026-01-06)
**Scope**: End-to-End Architectural Governance (Zero to Release)
**Status**: ACTIVE

---

## 1. Philosophy: "The Velo Way"
Velo architecture is not just about code; it is about **Governance, Security, and verifiable Performance**.
1.  **Governance is Code**: Roles (AGENTS.md) and Tasks (task.md) are immutable contracts.
2.  **Security is Surgical**: We do not "remove features" for security; we **shield** them (`EnvironmentShield`).
3.  **Verification is Hostile**: The QA process ("The Prosecutor") assumes the code is broken, insecure, and slow until proven otherwise via **Zero-Mock** binary testing.

---

## 2. Phase I: Inception (The Contract)

### 2.1 RFC Process (Design)
*   **Mandatory**: Every major feature (>1 week) requires an RFC.
*   **Expert Review**: Must include explicit "Security" and "Performance" sections.
*   **P0 Identification**: The Architect MUST extract "P0 Requirements" (Blockers) before coding begins.
    *   *Example*: "Socket paths must include User ID."

### 2.2 Task Breakdown
*   **Artifact**: `task.md` must be created immediately.
*   **Granularity**: 1 Task = 1 PR or 1 Verifiable Unit.
*   **Traceability**: Every Task ID must map back to an RFC requirement.

---

## 3. Phase II: Implementation (The Build)

### 3.1 Security Standard: "Surgical Shielding" (RFC-0012)
*   **Whitelist Only**: Never use blacklists (e.g., `env_remove`). Use `EnvironmentShield::new().apply()`.
*   **Hygiene**:
    *   **FDs**: Close all FDs > 2 in child processes (`close_range`).
    *   **Signals**: Reset signal masks before `exec`.
*   **Isolation**:
    *   **Sockets**: Must utilize `project_hash` + `uid` to prevent cross-workspace collisions.
    *   **Paths**: Use `O_PATH` and `fstat` (Inode verification) to prevent TOCTOU attacks.

### 3.2 Performance Standard (RFC-0010)
*   **Latency as a Bug**: Any regression >5% in Hot Restart or Scan Speed is a P0 defect.
*   **Telemetry**: Logs must output `STARTED_<timestamp>` for automated auditing.
*   **Debouncing**: Use state machines (Debounce + Hard Cap) to prevent reload storms.

---

## 4. Phase III: Verification ("The Prosecutor Method")

### 4.1 Zero-Mock Philosophy
*   **Rule**: "If it uses `MagicMock` for OS interactions, it is invalid."
*   **Requirement**: Tests must execute the **compiled binary** (`target/release/velo`).
*   **Probes**: Use `psutil`, `lsof`, and `/proc` to verify internal state from the outside.

### 4.2 CI/CD Hardening
*   **Port Hygiene**: Tests must use unique ports (e.g., `8011`, `8012`) to allow parallel execution.
*   **Process Safety**: NEVER use `pkill -f`. Track PIDs and use `proc.terminate()`.
*   **Dependencies**: Explicitly define `dev` dependencies in `pyproject.toml`.

---

## 5. Phase IV: Closure (The Verdict)

### 5.1 The Audit Report
*   **Artifact**: `audit_report.md` generated at phase end.
*   **Content**:
    *   **Security**: Verification of P0s (Green/Red).
    *   **Performance**: KPI measurements vs Targets.
    *   **Remediation**: Links to specific commits fixing audit findings.

### 5.2 Final Sign-off
*   **Gatekeeper**: Only the Architect (ID-LOCK-001) can sign off.
*   **Conditions**:
    1.  All P0s Verified.
    2.  Performance Baseline Established (Pass or Waiver).
    3.  CI Workflow Green.

---

## 6. Glossary & Assets
*   **AGENTS.md**: Role definitions.
*   **RFC-0012**: Full Armor Security Standard.
*   **RFC-0010**: Performance Requirements.
*   **The Executioner**: The hardened integration test suite.
