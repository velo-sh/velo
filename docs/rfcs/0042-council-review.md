# Council Review: RFC-0042 Velo Virtual Environment (VVE)

> **Authority**: [SOP-001 Master Lifecycle](../architecture/SOP-001-master-lifecycle.md)  
> **Target Artifact**: [RFC-0042 Velo Virtual Environment](./0042-velo-virtual-environment.md)  
> **Date**: 2026-01-25  
> **Verdict**: 🛑 **REQUEST CHANGES**

---

## 1. 📜 Phase I: The Summons

Based on the changes in **RFC-0042** (Kernel Namespaces, Filesystem Isolation, Zygote Integration), the following **Grand Council** members were summoned:

| Persona | Role | Justification |
| :--- | :--- | :--- |
| **Rust Core Dev** | System Safety | Reviewing `unshare`, `pivot_root`, and SHM handling logic in the Rust Supervisor. |
| **Security Engineer** | Attack Surface | Assessing the efficacy of Landlock/Seccomp tiers and the "Nitro Switch". |
| **Linux Specialist** | Kernel/Syscalls | Validating OverlayFS, VFS interactions, and namespace lifecycle. |
| **Cloud Native** | K8s/Containers | Verifying compatibility with Managed Kubernetes (EKS/GKE) and UserNS restrictions. |

---

## 2. 🗣️ Phase II: The Critique (Simulation)

### 2.1 Rust Core Dev (System Safety)
> *"Is the `mount --bind` of SHM handles before `pivot_root` safe against race conditions?"*

**Critique**:  
Section 5.1 mandates: `The Rust Supervisor MUST mount --bind ... BEFORE executing pivot_root.`  
This creates a critical race. Once `CLONE_NEWNS` is called, the process has a private mount namespace. Binding a host file descriptor (Zero-Copy SHM) into this new namespace acts as a bridge. However, `pivot_root` moves the root of the mount namespace.  
**Risk**: If the `mount --bind` happens *after* `unshare` but the path resolution changes during `pivot_root`, we lose the handle.
**Requirement**: Provide a sequence diagram or rigorous proof-of-concept showing how file descriptors are preserved and mapped correctly across the `unshare` -> `mount` -> `pivot_root` transition.

### 2.2 Security Engineer (Attack Surface)
> *"Who controls the 'Nitro Switch'? Can an Agent self-nominate for L(-1)?"*

**Critique**:  
Section 4.1 describes an **Opt-Out Policy ("Nitro Switch")** to disable `ImportShield` or `PathSanitization`.  
**Risk**: The RFC implies this is a configuration option. If a compromised Agent can simply request `tier: "L-1"` in its declarative config, isolation is effectively nullified.  
**Requirement**: The "Nitro Switch" MUST be gated by a **Cluster-Level Policy** or **Admin Signature**. It cannot be a discretionary user setting.

### 2.3 Cloud Native (K8s Compatibility)
> *"Does falling back to L3 break agents that expect L4 network isolation?"*

**Critique**:  
Section 5.3 states: `If UserNS is unavailable, VVE will degrade to L3`.  
**Risk**: Silent degradation is dangerous. An Agent written to expect a private `localhost` or private `/tmp` (L4 features) might unknowingly collide with other agents or leak data if silently downgraded to L3 (Shared OS, filtered syscalls).  
**Requirement**: The default behavior for L4 unavailability MUST be **Fail-Closed** (Crash/Error). Downgrade should only occur if explicitly authorized via a `allow_downgrade: true` flag in the Agent spec.

---

## 3. 📝 Phase III: The Verdict

**Outcome**: **REQUEST CHANGES**

The Grand Council cannot approve this RFC until the following **P0 Blocking Issues** are addressed:

1.  **[Security]** Define an explicit **Authorization Model** for the "Nitro Switch" (L-1/L0 opt-out). It must be privileged-only.
2.  **[Reliability]** Change L4->L3 fallback behavior to **Fail-Closed** by default. Prevent silent loss of isolation.
3.  **[Architecture]** Detail the SHM fd persistence mechanism. Confirm `pivot_root` interaction with bound mounts from the host namespace.

### Recommended Next Steps
*   Update RFC-0042 to address the critiques.
*   Simulate the SHM `pivot_root` flow in a standalone `main.rs` PoC.
*   Resubmit for Council Review.
