# SOP-002: Mission Protocol (The Velo Methodology)

> **Level**: TITANIUM
> **Scope**: All L3+ Complex Missions handled by the Architecture Department
> **Core Philosophy**: "We don't just deliver results; we deliver the path to the result."

---

## 1. Phase I: Forensic Immersion

**Principle**: "Don't trust memory; verify code."

Before starting any complex mission, a "Whitebox Audit" must be performed:
1.  **Chronological Deep Dive**:
    *   Read `git log` and file history.
    *   **Action**: Uncover "forgotten" committers and review records (e.g., the 15 experts in `RFC-0011`).
2.  **Scene Reconstruction**:
    *   Don't just read the code; *run* it.
    *   **Action**: Create a `Whitebox Audit` document recording the gap between reality and expectation.
3.  **Asset Inventory**:
    *   Check existing `docs/` against actual code.
    *   **Action**: Identify "Invisible Assets" (e.g., encryption audits that exist but aren't documented).

---

## 2. Phase II: The Council Assembly

**Principle**: "Individual intelligence is fragile; collective perspective is antifragile."

Do not solve complex problems alone. Assemble the (simulated) Expert Council:
1.  **Persona Excavation**:
    *   Select required experts from the [Personas Catalog](./expert_review_personas_catalog.md) based on mission attributes.
    *   *Case Study*: A performance task requires not just HPC experts, but also Accessibility experts (NO_COLOR).
2.  **Adversarial Review**:
    *   **Security**: "How do I break this?"
    *   **Ops**: "What happens when this explodes at 3 AM?"
    *   **Legal**: "Is this compliant?"
3.  **Unanimous Consent**:
    *   Complex decisions require "Conditional Approval" from ALL relevant experts.

---

## 3. Phase III: The Prosecutor's Trial

**Principle**: "Presumed Guilty (Buggy) until Proven Innocent via Zero-Mock."

Verification must be hostile:
1.  **Zero-Mock Rule**:
    *   No mocks allowed in the critical path. Must run on the real binary (`target/release`) and real kernel.
2.  **Titanium Variance**:
    *   If the standard isn't strict enough (e.g., 500ms restart), raise the bar immediately (<50ms). Never lower it.
3.  **Audit Report**:
    *   A tamper-proof Audit Report must be generated as the only valid proof of completion.

---

## 4. Phase IV: Titanium Crystallization

**Principle**: "If it's not in the SOP, it didn't happen."

The mission doesn't end with a Merge; it ends with Crystalization:
1.  **Standard Elevation**:
    *   Promote "Best Practices" discovered during the mission directly into `SOP-001` or `AGENTS.md`.
    *   *Case Study*: Elevating "Council of 5" to "Grand Council of 20".
2.  **Physical Materialization**:
    *   Documentation cannot be oral or ephemeral. It must physically exist in `docs/`.
    *   *Case Study*: Creating `expert_review_personas_catalog.md`.
3.  **Knowledge Base Sync (KI Sync)**:
    *   Update Agent Long-Term Memory (Knowledge Items) to ensure the next mission starts on the shoulders of giants.

---

**Last Updated**: 2026-01-06 (Created via The Grand Carpet Search)
