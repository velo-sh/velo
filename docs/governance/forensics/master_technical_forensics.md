# Master Technical Forensics Standard (TITANIUM Grade)

> **Authority**: Architect / Security Lead
> **Status**: **IMMUTABLE**

## 1. Evidence Preservation

**Principle**: "The Crime Scene is Sacred."

*   **Logs**: Upon incident, logs MUST be snapshotted (`cp log.json log.json.evidence.TIMESTAMP`) before any restart.
*   **Core Dumps**: Enable core dumps for critical crashes. Do not delete them until analysis is complete.
*   **Git State**: Record the exact commit hash (`git rev-parse HEAD`) and diff (`git diff`) of the incident environment.

## 2. Incident Classification

**Principle**: "Severity Dictates Response."

| Level | Definition | Response Timeline |
|:---|:---|:---|
| **L1 (Critical)** | Data Loss, Security Breach, Global Outage | Immediate (24/7), War Room |
| **L2 (Major)** | Feature Broken, Performance Degraded > 50% | 4 Hours, Dedicated Team |
| **L3 (Minor)** | UI Glitch, Non-Blocking Bug | Sprint Planning |

## 3. Post-Mortem Protocol (The "5 Whys")

**Principle**: "Blame the Process, Not the Person."

1.  **Timeline**: Second-by-second reconstruction.
2.  **Root Cause**: Not just "Code Error", but "Why did the test pass?"
3.  **Corrective Action**: Must include a **Prevention Mechanism** (e.g., new lint rule, new test invariant), not just a fix.

## 4. Whitebox Audit Checklist

**Principle**: "Trust Code, Not Docs."

- [ ] Does the `Cargo.toml` version match the deployed binary?
- [ ] Are there uncommitted changes in the build environment?
- [ ] Is the environment variable configuration identical to production?

---

**Last Updated**: 2026-01-06
