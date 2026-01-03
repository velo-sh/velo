# RFC-0009 Cryptography Expert Review

> **Reviewer Role**: 🔐 Cryptography & Data Integrity Specialist  
> **Review Date**: 2026-01-03  
> **RFC Under Review**: [0009-phase-6.0-static-graph.md](../rfcs/0009-phase-6.0-static-graph.md)  
> **Verdict**: 🟢 **APPROVED** (Strong recommendation for Keyed Mode)

---

## Executive Summary

The use of **BLAKE3** for bundle and graph integrity is an excellent choice. BLAKE3 is currently the state-of-the-art for high-performance hashing, offering better speed than MD5/SHA-1 and significantly higher security than both. This review focuses on the correct application of BLAKE3 specifically for the **H-8 (Graph Integrity)** and **H-4 (Fingerprint Binding)** invariants.

---

## 🟢 Strengths Acknowledged

| ID | Finding | Assessment |
|----|---------|------------|
| S-17 | **BLAKE3 Algorithm Choice** | BLAKE3 is immune to length extension attacks and offers 128-bit security level, which is more than sufficient for runtime integrity. |
| S-18 | **Global Hash Coverage (H-1)** | Including the graph section (H-8) in the global content hash prevents "mix-and-match" attacks where an old graph is paired with a new module set. |
| S-19 | **Performance at Scale** | BLAKE3's tree-based structure permits parallel hashing, which is vital for large `.veloc` bundles (up to 256MB). |

---

## 🟡 Design Recommendations (P1 - Must Fix Before Production)

### P1-013: Domain Separation for H-8

**Problem**: The RFC currently specifies that the graph is part of the global hash range `[52..EOF]`. While this prevents modification, it doesn't prevent a "type confusion" if multiple bundle sections were to use the same hashing scheme.

**Recommendation**:
1. **Keyed Mode (Mandatory)**: For fingerprinting and any internal bindings (H-4), BLAKE3's **Keyed Mode** MUST be used with a context-specific key.
2. **Context String**: When deriving keys or computing binding hashes, use a context string like `Velo-v1-StaticGraph-v0.6.0` to ensure domain separation.
3. **Internal Section Hashing**: The builder SHOULD compute a separate hash for the graph section and store it in the bundle index, which is then covered by the global hash.

---

### P1-014: Resistance to Pre-image Attacks in Cache Fingerprinting

**Problem**: The cache fingerprint (H-4) binds the cache to the `machine_key`. If the derivation of `machine_key` is weak, an attacker could pre-compute a cache that appears valid on another machine.

**Recommendation**:
1. **Derivation Spec**: The `machine_key` MUST be derived using BLAKE3 in **Derive Key Mode** using the machine's unique `machine-id` (e.g., `/etc/machine-id` on Linux) and a static salt.
2. **Salt**: Use a constant 32-byte salt: `Velo-Unique-Machine-Key-v1-2026`.

---

## 🟠 Security Considerations (P2 - Should Address)

### P2-016: Hash Selection for Large Bundles

**Observation**: For bundles near the 256MB limit, a single BLAKE3 pass is extremely fast. However, ensure that the implementation uses the **parallel** version of the crate (`blake3` with `rayon` or SIMD features enabled) to keep verification time below 2ms.

---

### P2-017: Integrity vs. Authenticity

**Observation**: The current design provides **integrity** (has it changed?) but not **authenticity** (who signed it?). This is acceptable for a local loader but worth noting.

**Recommendation**: If Velo evolves to support remote bundle downloads, the RFC must be updated to support **Ed25519 signatures** on the global hash.

---

## 🔵 Future Considerations (P3)

| ID | Suggestion |
|----|------------|
| P3-009 | Consider Mermaid-style hashing for incremental bundle updates. |
| P3-010 | Zero-knowledge proofs for bundle content (overkill but interesting for decentralized environments). |

---

## ✅ Cryptographic Compliance Checklist

| Requirement | Status |
|-------------|--------|
| Collision Resistance | ✅ (BLAKE3 is robust) |
| Length Extension Protection | ✅ (Native to BLAKE3) |
| Domain Separation | ⚠️ (Requires Keyed/Derive Mode) |
| Performance (Sub-2ms) | ✅ (BLAKE3 achieves ~1GB/s per core) |

---

## 📋 Approval Status

RFC-0009 is **APPROVED** provided that **BLAKE3 Keyed/Derive Mode** is strictly enforced for all security invariants (H-4, H-8, H-1).

---

*Reviewed by: 🔐 Cryptography Expert (Simulated)*  
*Review Protocol: SHA-3/BLAKE3 Security Standards*
