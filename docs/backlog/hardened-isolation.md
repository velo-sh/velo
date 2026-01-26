# Velo Architectural Backlog: Production Hardening

This document records high-priority architectural improvements deferred for future implementation (Post-v1.0 or Post-RFC-0033).

## 1. Linux Landlock (LSM) Integration
- **Objective**: Implement path-level access control for Workers.
- **Context**: Beyond Network/Namespace isolation, Landlock (LSM) provides a strict whitelist for file system access inside the Zygote fork.
- **Implementation Note**: Target \`v_shield.rs\` on Linux 5.13+. Requires a whitelist configuration standard.
- **Value**: TITANIUM-grade security; prevents Python script escape to host \`/etc/\` or other sensitive paths.

## 2. IPC Protocol Fuzzing
- **Objective**: Stress test IPC boundaries.
- **Context**: Use \`cargo-fuzz\` to test deserialization logic (rkyv/serde) in \`velo-protocol\`.
- **Value**: Identify DoS or memory safety edge cases in cross-process communication before they occur in production.
