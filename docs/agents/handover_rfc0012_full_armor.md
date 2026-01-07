# Handover: RFC-0012 Full Armor -> Next Agent / Architect

## 1. Context Snapshot
- **Current State**: **STABLE & TITANIUM CERTIFIED**. All security invariants from RFC-0012 are implemented and verified.
- **Last Action**: Merged `phase-6.1.1/zygote-worker-integration` into `main` and pushed to remote. Verified with 230 unit tests + Executioner Suite.
- **Next Step**: Conduct final Phase 6.2 Sign-off or proceed to performance/feature extensions.

## 2. Technical State (TITANIUM Engine)
- **Centralized Safety**: All hygiene and environment shielding logic is in [safety.rs](file:///Users/gjwang/eclipse-workspace/rust_source/velo/src/lifecycle/safety.rs).
- **Cross-Platform Parity**:
    - **macOS**: Uses Atomic Socket Creation with `umask(077)` in randomized/project-hashed temp dirs.
    - **Linux**: Uses Abstract Namespace Sockets (`@velo-zygote...`) with mandatory `SO_PEERCRED` mutual authentication.
- **Surgical Scrubbing**: Environment variables (`PATH`, `PYTHONPATH`) are surgically cleaned instead of hard-aborting, ensuring robust startup even in "dirty" shells.

## 3. Invisible Knowledge
- **Test Alignment**: The unit test `test_environment_shield_basic` was updated to expect *Surgical Scrubbing* (filtering) instead of a `Result::Err`. This is intentional and follows the hardened-but-robust philosophy.
- **macOS Caveat**: macOS temp directory paths (from `std::env::temp_dir()`) can be extremely long. We've implemented a 104-char fallback to `/tmp` to prevent Unix socket path truncation.
- **Linux Capability**: Peer Auth (`SO_PEERCRED`) is only compiled on Linux targets. It is essential for abstract sockets as they bypass filesystem permissions.

## 4. The "Keys"
- **Zygote Log**: Located at `~/.velo/zygote.log` (or project root depending on environment).
- **Socket Pattern**: `velo-zygote-v{PROTOCOL_VERSION}.sock`. In abstract namespace on Linux, it starts with an `@`.
- **Protocol Version**: Currently `0x01` (MessagePack).

---
**Handover Signed**: Velo Security Specialist (AI)
**Date**: 2026-01-06
