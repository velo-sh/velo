# Agent C (Security & Integrity) -> Review RFC-0009 Static Graph Design

> **Reviewer**: Agent C (Security Specialist)  
> **Review Target**: RFC-0009 Static Import Graph  
> **Date**: 2026-01-03  
> **Stance**: Adversarial audit of graph integrity and boundary safety.

---

## 🟢 Strengths (C-S-01)
- **H-8 Integrity**: Use of Keyed BLAKE3 binds the graph to the specific bundle version.
- **H-10 Protection**: Nesting and memory limits in Rkyv validation are robust against "logic bombs".

---

## 🛡️ Security Findings (C-P0)

### C-P0-001: Path Traversal via `search_locations`
**Problem**: An attacker can inject absolute paths or `..` into the `search_locations` hashmap.
**Action**: Implementation MUST enforce a strict "In-Bundle" sandbox. Any path resolution that escapes the bundle root (after normalization) MUST trigger `SecurityError`.

### C-P0-002: Arch-Pinning Bypass
**Observation**: Header contains `target_arch_id`.
**Risk**: If the loader only checks the header but not the graph section metadata, a "mix-and-match" attack could occur.
**Recommendation**: The `target_arch_id` MUST be embedded inside the signed Rkyv archive, not just the plain-text header.

---

## 🚨 Security Checklist (H-Audit)

- [x] **H-4**: Fingerprint binding (Machine ID)
- [x] **H-8**: Graph cryptographical integrity
- [x] **H-9**: 4KB Page alignment (prevents page-boundary cache timing attacks)
- [x] **H-10**: Rkyv nesting limit (100)

---

**Agent C Sign-off**: Verified from Adversarial Perspective.  
**Recommendation**: Approved for development.
