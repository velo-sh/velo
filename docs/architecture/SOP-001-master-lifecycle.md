# SOP-001: Master Architecture Lifecycle Standard

**Ownership**: Architect Force (ID-LOCK-001)
**Version**: 2.0 (2026-01-06)
**Scope**: End-to-End Architectural Governance (Zero to Release)
**Status**: ACTIVE

---

## 1. Philosophy: "The Velo Way" (TITANIUM Standard)
Velo is **Industrial Infrastructure**. We operate at the **TITANIUM Grade** of reliability and security.

1.  **Governance is Law**: Roles (AGENTS.md) and SOPs are immutable contracts, not suggestions.
2.  **Security is Structural**: We do not "patch" security; we **architect** it (Surgical Shielding).
3.  **Verification is Hostile**: The "Prosecutor Method" assumes failure until proven succesful by **Zero-Mock** binary execution.
4.  **Invariants are Absolute**: Performance and Security thresholds are **P0 Blockers**. No "Tactical" waivers.
6.  **Identity Immutability (Iron Rule)**: The AI Agent's role is **LOCKED** upon mission start.
    *   ❌ **NO HANDOVERS**: Switching roles (e.g., Architect -> Developer) is strictly **PROHIBITED**.
    *   ❌ **NO AUTO-TRANSITION**: Self-authorized role changes are a critical governance breach.
    *   🏛️ **STAY IN LANE**: The Architect stays the Architect. If the code cannot be written by the Architect, the Architect must stop at the design gate.

---

## 2. Phase I: Inception (The Contract)

### 2.0 Whitebox Pre-Audit (Discovery)
*   **Goal**: inspect existing code/infrastructure *before* designing new features.
*   **Artifact**: `whitebox_audit.md`.
*   **Action**: Identify existing vulnerabilities or performance bottlenecks that must be fixed.

### 2.1 RFC Process (Design)
*   **Mandatory**: Every major feature (>1 week) requires an RFC.
*   **The Grand Council (15-Persona Review)**:
    *   **Tier 1 (Strategic)**: CTO (Risk), Senior PM (Reqs), Legal (Compliance), Architect (Lead).
    *   **Tier 2 (Domain)**:
        1.  **Security**: Attack Surface (Injection, Isolation).
        2.  **Rust Core**: Systems safety (RAII, Threads).
        3.  **Python Core**: Runtime internals (GIL, Signals, Imports).
        4.  **HPC/SciPy**: Performance limits (<50ms).
        5.  **Frameworks**: Django/FastAPI compatibility.
    *   **Tier 3 (Platform & Ops)**:
        1.  **macOS**: FSEvents, App Sandbox.
        2.  **Linux**: inotify, cgroups, Abstract Sockets.
        3.  **Network SRE**: Protocols (TCP/UDS), Headers.
        4.  **Cloud Native**: K8s probes, Container signals.
        5.  **Observability**: Logging standards, Tracing.
    *   **Tier 4 (Specialized Audits)**:
        1.  **Cryptography**: Hashing (BLAKE3), Key Derivation, Signatures.
        2.  **Data Structures**: Big-O analysis, Graph algorithms.
        3.  **Accessibility (A11y)**: Color blindness (NO_COLOR), Screen readers.
        4.  **Open Source (OSS)**: License compliance, Community standards.
        5.  **Documentation**: Learning curves, Voice & Tone.
*   **P0 Identification**: The Architect MUST extract "P0 Requirements" from these reviews.
    *   *Example*: "Socket paths must include User ID."
*   **Voting Mechanism (Iron Rule)**:
    *   **Quorum**: All experts relevant to the domain MUST be summoned.
    *   **Unanimity**: RFC approval requires **Unanimous Consent** (Approved or Conditional Approval) from ALL summoned experts.
    *   **Veto**: A single "Request Changes" from ANY summoned expert blocks the RFC.

### 2.2 Task Breakdown
*   **Artifact**: `task.md` must be created immediately.
*   **Granularity**: 1 Task = 1 PR or 1 Verifiable Unit.
*   **Traceability**: Every Task ID must map back to an RFC requirement.

---

## 3. Phase II: Implementation (The Build)

### 3.0 The Titanium Variance Protocol (No Compromise)
*   **Immutable Basis**: Security and Performance invariants (RFC-0010/0012) are **IMMUTABLE**.
*   **The Variance Path**: If an invariant physically prevents core functionality, a **Titanium Variance** may be requested.
*   **Scrutiny Level**: Variances require **UNANIMOUS** sign-off from the Grand Council (Tier 1 & Tier 2).
*   **Record**: Every variance must be permanently recorded as an ADR (Architecture Decision Record).

### 3.1 Security Standard: "Surgical Shielding" (RFC-0012, TITANIUM)
*   **Whitelist Only**: The `EnvironmentShield` is the only allowed sanitation mechanism.
*   **Hygiene**:
    *   **FDs**: `close_range` is mandatory on Linux. 
    *   **Signals**: Signal masks must be religiously reset.
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

## 5. Phase IV: The Independent Review Board (The Jury)
*   **Mandate**: A "Multi-Discipline Final Technical Assessment" must occur before release.
*   **Composition**: 
    1.  **Python Runtime**: CPython internals, GIL, Signals.
    2.  **OS / Kernel**: Linux/macOS process model, FDs.
    3.  **High-Perf Networking**: L7 Proxy, Request Smuggling.
    4.  **ASGI / Frameworks**: Protocol Compliance.
    5.  **Security Architect**: Permission Boundaries.
    6.  **Infra / SRE**: Rolling restarts, Observability.
*   **Verdict**: Unanimous "Conditional Approval" or "Rejection".

---

## 6. Phase V: Closure (The Verdict)

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

## 7. Phase VI: Knowledge Crystallization (The Legacy)
*   **KI Updates**: Update system knowledge items (KIs) with new patterns or architectural decisions.
*   **Assets**: Standardize success templates (like this SOP).
*   **Anti-Patterns**: Document what *failed* to prevent recurrence (`docs/guides/*`).

---

## 8. Glossary & Assets
*   **AGENTS.md**: Role definitions.
*   **RFC-0012**: Full Armor Security Standard.
*   **RFC-0010**: Performance Requirements.
*   **The Executioner**: The hardened integration test suite.
