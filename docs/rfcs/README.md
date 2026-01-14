# Velo RFCs (Request for Comments)

This directory contains design documents for significant Velo features and architectural decisions.

## What is an RFC?

RFCs are design documents that describe proposed changes to Velo. They provide a structured way to:

- Communicate technical decisions transparently
- Gather community feedback before implementation
- Document the reasoning behind architectural choices

## Active RFCs

| RFC | Title | Status | Target |
|-----|-------|--------|--------|
| [0001](./0001-phase-1.5-env-detection.md) | Phase 1.5 Environment Fingerprinting | ✅ Implemented | v0.2.0 |
| [0002](./0002-phase-3-zygote.md) | Phase 3 Zygote Mode | ✅ Implemented | v0.3.0 |
| [0003](./0003-phase-3.5-ecosystem.md) | Phase 3.5 Ecosystem Integration | ✅ Implemented | v0.3.5 |
| [0004](./0004-phase-4-analyze.md) | Phase 4.0 Smart Optimization | ✅ Implemented | v0.4.0 |
| [0005](./0005-phase-4.1-cleanup-security.md) | Phase 4.1 Cleanup & Security | ✅ Implemented | v0.4.1 |
| [0006](./0006-phase-5.0-fast-loader.md) | Phase 5.0 Fast Loader | ✅ Implemented | v0.5.0 |
| [0007](./0007-benchmarking-infrastructure.md) | Performance Tracking | ✅ Implemented | v0.5.0 |
| [0008](./0008-phase-5.1-zygote-optimization.md) | Phase 5.1 Zygote 10ms | ✅ Accepted | v0.5.1 |
| [0010](./0010-phase-6.1-serve-analyze.md) | Phase 6.1 Serve, Analyze & Polish | ✅ Approved | v0.6.1 |
| [0011](./0011-zygote-worker-integration.md) | Phase 6.1.1 Zygote Worker Integration | ✅ Approved | v0.6.2 |
| [0012](./0012-full-armor-security-standard.md) | 'Full Armor' Security Standard | ✅ Audited | v0.6.2 |
| [0013](./0013-kinetic-protocol.md) | Kinetic Protocol (UDS Optimization) | ✅ Implemented | v0.6.3 |
| [0014](./0014-cow-venv-architecture.md) | CoW-Venv & Top 100 Framework | ✅ Accepted | v0.7.0 |
| [0015](./0015-memory-gravity.md) | Memory Gravity (Tensor SHM) | ✅ Implemented | v0.7.0 |
| [0016](./0016-environment-convergence.md) | Environment Convergence & SSoT | ✅ Superseded by SPEC-0005 | v0.7.1 |
| [0017](./0017-test-tier-discovery.md) | Test Tier Discovery (QA Optimization) | [/] In Progress | v0.7.1 |
| [0018](./0018-integrated-custody.md) | Integrated Custody (uv / Autopilot) | ✅ Approved | v0.7.2 |
| [0019](./0019-native-sovereignty.md) | Native Sovereignty (Rust Host) | ✅ Approved | v0.8.0 |
| [0020](./0020-zygote-observability.md) | Zygote Observability | ✅ Approved | v0.8.0 |
| [0021](./0021-unified-process-supervision.md) | Unified Process Supervision | ✅ Approved | v0.8.1 |
| [0022](./0022-operational-experience.md) | Operational Experience Standard | ✅ Approved | v0.8.1 |
| [0023](./0023-tiered-environment-namespacing.md) | Tiered Environment Namespacing | ✅ Approved | v0.8.2 |
| [0024](./0024-forensic-compatibility-specification.md) | Forensic Compatibility Specification | ✅ Approved | v0.8.2 |
| [SPEC-0005](../architecture/SPEC-0005-SSOT-MASTER-STANDARD.md) | **SSOT Master Standard** | ✅ **Master** | v0.7.2 |
| [SPEC-0006](../architecture/SPEC-0006-POLYGLOT-GOVERNANCE.md) | **Polyglot Service Governance** | ✅ **Master** | v0.8.2 |
| [SPEC-0007](../architecture/SPEC-0007-PERFORMANCE-MASTER-STANDARD.md) | **High-Performance Master Standard** | ✅ **Master** | v0.8.2 |
| [SPEC-0008](../architecture/SPEC-0008-TIERED-TESTING-STANDARD.md) | **Tiered Testing Master Standard** | ✅ **Master** | v0.8.2 |

## Quality Assurance Reports

- **[PHASE_6_2_DESIGN_AUDIT](./docs/qa/audit_reports/PHASE_6_2_DESIGN_AUDIT.md)**: 16-Dimension Multi-Persona Review.

## Architecture Decision Records (ADRs)

| ADR | Title | RFC | Status |
|-----|-------|-----|--------|
| [ADR-0010-001](./ADR-0010-001-gap-decisions.md) | Gap Analysis Decisions | RFC-0010 | ✅ Approved |

## RFC Lifecycle

```
Draft → RFC → Accepted → Implemented → Closed
                ↓
            Rejected/Deferred
```

## Contributing

We welcome feedback on any RFC! Please:

1. Open a [GitHub Issue](https://github.com/velo-sh/velo/issues) referencing the RFC number
2. Or submit a PR with suggested changes

## Optimization RFCs

| RFC | Title | Status | Target |
|-----|-------|--------|--------|
| [OPT-0010-001](./OPT-0010-001-msgpack-ipc.md) | MessagePack IPC Protocol | ✅ Implemented | v0.6.1 |

## Past RFCs

*None yet - we're just getting started!*
