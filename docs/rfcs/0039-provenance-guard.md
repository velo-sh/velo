# RFC-0039: Supply Chain Provenance Guard

**Status**: DEFERRED
**Author**: Velo Architect
**Date**: 2026-01-24
**Phase**: Future (Post v1.0)
**Scope**: Security, Supply Chain

---

## 1. Executive Summary

This RFC proposes **Provenance Guard**, a supply chain security layer that verifies the origin and authenticity of preloaded native libraries beyond path integrity and hash verification.

> [!IMPORTANT]
> **Status: DEFERRED** — Python ecosystem infrastructure (PEP 740 attestations, Sigstore adoption) is not mature enough for practical implementation. This RFC is preserved for future reference.

---

## 2. Motivation

### Current Security Stack (RFC-0035)

| Layer | Feature | Defends Against |
|:---|:---|:---|
| L1 | Path Integrity | Local path injection (/tmp sideloading) |
| L2 | BLAKE3 Fingerprint | File tampering |
| **L3** | **Provenance Guard** | **Supply chain attacks** |

### The Gap

Path Integrity + Fingerprint answers: *"This file hasn't been modified."*

But cannot answer: *"Was this file malicious from the start?"*

### Real-World Threats

- **PyPI Typosquatting** (2024 incidents)
- **Dependency Hijacking** (legitimate package takeover)
- **Build Pipeline Compromise** (poisoned CI/CD outputs)

---

## 3. Proposed Features

### 3.1 Code Signature Verification

| Platform | Mechanism |
|:---|:---|
| macOS | `codesign` / Notarization |
| Linux | GPG / Sigstore |

### 3.2 Build Attestation (PEP 740)

```json
{
  "attestation": {
    "build_system": "GitHub Actions",
    "slsa_level": 2,
    "signed_by": "sigstore.dev"
  }
}
```

### 3.3 Trusted Publisher Registry

```toml
[tool.velo.provenance]
mode = "advisory"  # "off" | "advisory" | "strict"
trusted_publishers = [
  "PyPI:python-cryptographic-authority",
  "GitHub:pytorch/pytorch"
]
```

---

## 4. Critical Challenges

### 4.1 Trust Anchor Problem

> **问题**: 谁是"可信"的源头？

| Option | Issue |
|:---|:---|
| PyPI signatures | Not mandatory, <5% coverage |
| GitHub SLSA | Partial coverage only |
| User keyring | Complex configuration |
| Velo whitelist | Not scalable |

**Verdict**: No unified trust anchor in Python ecosystem.

### 4.2 Failure Policy Dilemma

| Policy | Pro | Con |
|:---|:---|:---|
| `block` | Most secure | Blocks 99% of packages |
| `warn` | Non-disruptive | Alert fatigue |
| `skip` | Compatible | Useless |

### 4.3 Offline Environments

- OCSP/CRL checks require network
- Air-gapped environments need "signature cache"
- Adds operational complexity

### 4.4 Ecosystem Readiness

| Metric | Current | Required |
|:---|:---|:---|
| PEP 740 adoption | <5% | >50% |
| Sigstore for Python | Early | Mature |
| Top 100 PyPI attestations | ~10 | >50 |

---

## 5. Recommendation

### v0.9.x - v1.0: DO NOT IMPLEMENT

- ROI too low
- Ecosystem not ready
- Path Integrity + BLAKE3 covers 95% of practical threats

### v1.1+: Re-evaluate When

- PEP 740 adoption > 30%
- Top 100 PyPI packages have attestations
- Sigstore becomes standard for Python wheels

### Implementation Path (When Ready)

1. Start with `advisory` mode only
2. Target high-value packages first (cryptography, torch, numpy)
3. Never block by default

---

## 6. Monitoring Triggers

Re-open this RFC when:

- [ ] PEP 740 reaches "Accepted" status with PyPI integration
- [ ] Sigstore adoption in pip/uv exceeds 30%
- [ ] Major supply chain incident forces industry response

---

## 7. References

- [PEP 740 – Index support for digital attestations](https://peps.python.org/pep-0740/)
- [SLSA Supply Chain Levels](https://slsa.dev/)
- [Sigstore for Python](https://docs.sigstore.dev/)
- [RFC-0035: Native Library Preload](./0035-native-library-preload.md)

---

**Custodian**: Velo Architect
**Last Updated**: 2026-01-24
