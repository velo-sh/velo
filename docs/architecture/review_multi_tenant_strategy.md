# Expert Review: Multi-Tenant Architecture & Limits (Memory Gravity)

> **Document ID**: REV-0015-MT (Multi-Tenant Strategy)
> **Author**: System Architect / HFT Reviewer
> **Date**: 2026-01-07
> **Status**: TITANIUM GUIDANCE (Authoritative / Hostile Hardened)

---

## 1. Executive Summary

This review addresses the critical architectural question: **"Can Memory Gravity achieve zero-copy sharing across multi-tenant boundaries?"**

**The Conclusion**:
1.  **NO**. Pure zero-copy (FD passing) across tenants is **STRUCTURALLY IMPOSSIBLE** on Linux without violating capability isolation.
    - *Any scheme that relies on shared kernel address space (including containers, namespaces, or SELinux-constrained processes) cannot provide cross-tenant zero-copy without collapsing capability isolation. This is a structural property of Linux, not an implementation choice.*
2.  **BUT**, a highly efficient **"Layered Broker Model"** (v1.x) exists, which is the theoretical optimum for secure multi-tenancy.
3.  **Velo v0.7.0** MUST remain strictly **Tenant-Scoped** (Mode 1), rebranding Memory Gravity from "sharing tech" to "**Trust-Domain-Local Execution Fabric**".

---

## 2. The Impossibility Theorem (Why FD Passing Fails)

It is impossible to satisfy these three conditions simultaneously on standard Linux:
1.  **Cross-Tenant Sharing**: Multiple untrusted tenants access the same physical pages.
2.  **Zero-Copy**: No memory duplication.
3.  **Capability Isolation**: FD access does not leak privileges.

**Why FD Passing is a Dead End**:
FD is an unforgeable reference to a kernel object whose lifetime and reachability are **not namespace-contained**.
- **The Axiom**: Linux does not support revocable or attenuable capabilities. Therefore, any FD passed into an untrusted security domain must be treated as a **permanent privilege grant** to that domain.

**Result**: You cannot use an FD as a secure isolation boundary within a shared kernel.

---

## 3. The Only Valid Solutions (Architecture Tiering)

### Mode 1: Tenant-Scoped Gravity (Velo v0.7.0)
*The only configuration for v0.7.0 release.*

- **Model**: One Tenant = One Host + One SHM.
- **Definition**: Memory Gravity is NOT a global pooling tech. It is a **Trust-Domain-Local Execution Fabric**.
- **Analogy**: Like JVM Heap or GPU Context Memory, but for Python processes in the same trust domain.
- **Security**: Relies on standard Linux user/container isolation.

### Mode 2: The Broker Model (Velo v1.x Target)
*The theoretical optimum for secure multi-tenancy.*

**Architecture**:
```
[ Weight Broker (Privileged Materializer) ]
      |
      | (One-time Copy on Admission)
      v
[ Tenant A Host + SHM ] <=== Zero-Copy ===> [ Tenant A Workers ]
```

**Key Mechanics**:
1.  **Layer 0 (Global)**: Broker acts as a **One-Way Materializer**, not a shared memory provider. The canonical weights are never mapped or shared.
2.  **Layer 1 (Admission)**: When Tenant A requests a model, Broker performs a **Single `memcpy`** into Tenant A's private SHM.
3.  **Layer 2 (Inference)**: Tenant A's workers attach to Tenant A's SHM (Memory Gravity).

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
- **Red Line**: Any attempt to reintroduce cross-tenant shared mappings (including COW tricks, KSM, or page deduplication) is considered a violation of the security model and out of scope for Velo.

---

## 5. Final Verdict

> "This RFC correctly identifies the point at which system design must yield to operating system reality. Any design that claims otherwise is either insecure or dishonest."

**Approved Strategy**:
1. Lock v0.7.0 to **Tenant-Scoped Mode**.
2. Design v1.x around **Broker / Copy-on-Admission**.

*"We are TITANIUM."*
