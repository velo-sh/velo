# Council Review: RFC-0036 LifeCode™ Model

> **Date**: 2026-01-20
> **Subject**: RFC-0036 LifeCode™ Model & Brand Family
> **Facilitator**: Antigravity (Arch)
> **Status**: **APPROVED WITH ADVISORIES**

---

## 1. Council Attendance

| Persona | Representative | Focus |
|:---|:---|:---|
| **Architect** | 0xMaster Protocol | Vision Alignment |
| **Security Engineer** | Section 9 | Threat Modeling |
| **Cryptographer** | Cipher One | Hashing & Privacy |
| **Rust Core Dev** | Ferriss | Implementation Viability |
| **Cloud Native** | K8s Keeper | Deployment Strategy |
| **Tech Writer** | DocuSent | Branding Consistency |

---

## 2. Findings & Critique

### 2.1 Strategic Alignment (Architect)
> *"The Biological Metaphor is a powerful unification of our separate initiatives (Bundle, Isolation, Distribution). The rebranding to `.lcpkg` correctly signals this shift from 'package' to 'organism'. The 'Gene Spark' concept aligns perfectly with our 'Instant' philosophy."*

**Verdict**: **STRONG SUPPORT**. The taxonomy (Gene, Organ, Organism) provides a distinct vocabulary that separates Velo from Docker/Nix.

### 2.2 Security & Privacy (Cryptographer & Security)
> *"BLAKE3 and Ed25519 are the correct primitives. However, Section 6.1 (Global Deduplication) introduces a Privacy Oracle Side-Channel."*

*   **Risk**: **Privacy Leak via Existence Confirmation**.
    *   *Scenario*: Attacker generates the hash for a known proprietary file (e.g., `proprietary_algo.py` from a leak).
    *   *Attack*: Attacker queries GenePool: `exists(hash)`.
    *   *Result*: If true, Attacker knows Victim has uploaded this file.
*   **Advisory**: Global deduplication should be **opt-in** or **encrypted-at-rest** (convergent encryption) for private repositories. Public GenePool can remain open.
*   **Refinement**: Update RFC to distinguish between "Public Pool" (Global Dedup) and "Private Pool" (Scoped Dedup).

### 2.3 Implementation Details (Rust Core)
> *"The `ObjectStore` trait in Section 9.1 is solid, but `fn list() -> Box<dyn Iterator...>` is synchronous and allocation-heavy."*

*   **Recommendation**:
    ```rust
    // Change to async stream for scalability
    fn list(&self) -> impl Stream<Item = Hash>;
    ```
*   **Note**: The "Virtual Materialization" (mmap) strategy (2.4) is critical for "Instant Genesis". We must ensure `mmap` safety on non-POSIX filesystems if Windows support is planned (Phase 15+).

### 2.4 Cloud Native Integration (Cloud Native)
> *"Gene as Deploy (GaD) is a game changer for K8s. However, 'Gene Spark' needs a precise definition in a container context. Is the container the 'server'? Or is the 'server' a node agent spawning containers?"*

*   **Clarification**: RFC implies a Velo Runtime (Daemon) that accepts sparks. In K8s, this would likely be a CRD + Operator or a Sidecar.
*   **Action**: Add a "Kubernetes Integration" section to the implementation plan.

---

## 3. Verdict

**DECISION: APPROVED WITH ADVISORIES**

The Council approves RFC-0036 as the **Authoritative Specification** for the LifeCode™ Phase.

### Required Actions (Non-Blocking for RFC Merge, Blocking for V2.0):
1.  **[Security]** Define "Private Pool" semantics to mitigate Privacy Oracle via Deduplication.
2.  **[Rust]** Modernize `ObjectStore` traits to usage of `Async` / `Stream` before final implementation.
3.  **[Docs]** Explicitly state that "Gene Spark" on K8s implies a Supervisor/Operator model.


### Signed By:
*   *0xMaster (Architect)*
*   *Section 9 (Security)*
*   *Cipher One (Crypto)*

---

### 4. Post-Approval Directives (0xMaster)

**Addendum Added**: 2026-01-20

The Architect provided the following **Mandatory Enhancements** to ensure Global Consistency:

1.  **Global Consistency**: Explicitly defined `Root Hash = Species` as the immutable identity of an organism.
2.  **Deterministic Identity**: Added **Section 3.4** ensuring Canonical Encoding for reproducible builds.
3.  **Merkle Proofs**: Added **Section 8.5** allowing partial verification for Edge/IoT scenarios.
4.  **Future Architecture**: Added **Section 10** outlining the P2P Data Plane.

**Status**: All directives have been fully integrated into `RFC-0036`.
