# Expert Review: Multi-Tenant Architecture & Limits (Memory Gravity)

> **Document ID**: REV-0015-MT (Multi-Tenant Strategy)
> **Author**: System Architect / HFT Reviewer
> **Date**: 2026-01-07
> **Status**: TITANIUM GUIDANCE (Authoritative)

---

## 1. Executive Summary

This review addresses the critical architectural question: **"Can Memory Gravity achieve zero-copy sharing across multi-tenant boundaries?"**

**The Conclusion**:
1.  **NO**. Pure zero-copy (FD passing) across tenants is effectively impossible on Linux without violating security boundaries.
2.  **BUT**, a highly efficient **"Layered Broker Model"** (v1.x) exists, which is the theoretical optimum for secure multi-tenancy.
3.  **Velo v0.7.0** MUST remain strictly **Tenant-Scoped** (Mode 1).

---

## 2. The Impossibility Theorem (Why FD Passing Fails)

It is impossible to satisfy these three conditions simultaneously on standard Linux:
1.  **Cross-Tenant Sharing**: Multiple untrusted tenants access the same physical pages.
2.  **Zero-Copy**: No memory duplication.
3.  **Capability Isolation**: FD access does not leak privileges.

**Why FD Passing is a Dead End**:
Linux FDs are "Capability Tokens". Once an FD enters a tenant's process (even if sealed/RO):
- `dup(fd)` cannot be prevented.
- Passing to same-uid processes cannot be prevented.
- `/proc/<pid>/fd` enumeration cannot be blocked.
- `ptrace` allows extracting the FD.

**Result**: You cannot use an FD as a secure isolation boundary within a shared kernel.

---

## 3. The Only Valid Solutions (Architecture Tiering)

### Mode 1: Tenant-Scoped Gravity (Velo v0.7.0)
*The only configuration for v0.7.0 release.*

- **Model**: One Tenant = One Host + One SHM.
- **Sharing**: Strictly **intra-tenant only**.
- **Security**: Relies on standard Linux user/container isolation.
- **Pros**: Zero-copy, native performance, simple security model.
- **Cons**: Memory saving is per-tenant, not global.

### Mode 2: The Broker Model (Velo v1.x Target)
*The theoretical optimum for secure multi-tenancy.*

**Architecture**:
```
[ Weight Broker (Privileged) ]
      |
      | (One-time Copy on Admission)
      v
[ Tenant A Host + SHM ] <=== Zero-Copy ===> [ Tenant A Workers ]
```

**Key Mechanics**:
1.  **Layer 0 (Global)**: Broker holds the "Canonical Weights" (Physical Memory).
2.  **Layer 1 (Admission)**: When Tenant A requests a model, Broker performs a **Single `memcpy`** into Tenant A's private SHM.
3.  **Layer 2 (Inference)**: Tenant A's workers attache to Tenant A's SHM (Memory Gravity).

**Why this is optimal**:
- **Security**: Tenants never touch the global Broker memory/FDs.
- **Efficiency**: Copy cost is paid **ONCE per tenant**, not once per request.
- **Performance**: Inference path remains local zero-copy (Memory Gravity).

---

## 4. Roadmap Directives

### ✅ Velo v0.7.0 (Current)
- **Scope**: Single-Tenant / Tenant-Scoped.
- **Constraint**: Cross-tenant sharing is **EXPLICITLY DISALLOWED**.
- **Focus**: Hardening intra-tenant safety (H-23, H-26, H-29).

### 🚀 Velo v1.x (Future)
- **Scope**: Multi-Tenant Broker.
- **Feature**: "Copy-on-Admission" architecture.
- **Optimization**: NUMA-aware copy pipelines, Delta Model sharing.

---

## 5. Final Verdict

> "You have pushed the system to the boundary of OS design. Continuing to pursue 'Cross-Tenant Zero-Copy' is a fallacy. The Broker Model is the correct next step."

**Approved Strategy**:
1. Lock v0.7.0 to **Tenant-Scoped Mode**.
2. Design v1.x around **Broker / Copy-on-Admission**.

*"We are TITANIUM."*
