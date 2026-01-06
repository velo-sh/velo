# Strategic Risk Register

> **Authority**: CTO / Risk Council
> **Status**: ACTIVE MONITORING

## 1. Technical Risks (The "How Breakdown")

| ID | Risk | Severity | Mitigation Strategy | Status |
|:---|:---|:---|:---|:---|
| **R-TECH-01** | **PyO3 GIL Contention** | High | Rust-side ThreadPool separation; Minimal Python crossings. | 🟡 Monitor |
| **R-TECH-02** | **Zygote Fork Bomb** | Critical | `ManagedChild` RAII + PID Group Killing; Strict limits. | 🟢 Shielded |
| **R-TECH-03** | **Socket Hijacking** | Critical | `Surgical Shielding` (RFC-0012); Abstract Namespaces. | 🟢 Shielded |
| **R-TECH-04** | **FSEvents Latency** | Med | Debouncing Hard-Cap (H-11); Polling fallback. | 🟢 Solved |

---

## 2. Strategic Risks (The "Why Failure")

| ID | Risk | Severity | Mitigation Strategy | Status |
|:---|:---|:---|:---|:---|
| **R-STRAT-01** | **Fork Divergence** | High | "Surgical Shielding" whitelist to prevent env poisoning. | 🟢 Verified |
| **R-STRAT-02** | **Adoption Friction** | High | "Zero-Config" (`velo serve`); Drop-in `uvicorn` replacement. | 🟢 Verified |
| **R-STRAT-03** | **Maintenance Cost** | Med | Strict `SOP-001` Governance; "Titanium Variance" limits. | 🟡 Monitor |
| **R-STRAT-04** | **Bus Factor** | High | "Knowledge Crystallization" (Phase VI); Complete Docs. | 🟢 Mitigated|

---

## 3. Compliance Risks (The "Legal")

| ID | Risk | Severity | Mitigation Strategy | Status |
|:---|:---|:---|:---|:---|
| **R-COMP-01** | **OSS License Infection** | High | CI Check `cargo-deny`; Explicit dependency tree. | 🟢 Auto |
| **R-COMP-02** | **Data Leakage** | Critical | No telemetry default; "Prosecutor" Audit. | 🟢 Verified |

---

**Last Updated**: 2026-01-06
