# Handover: Developer (Phase XI - Kinetic Optimization)

> **Authority**: SOP-001 §2.3
> **Source RFC**: [RFC-0013 v1.1](../rfcs/0013-kinetic-protocol.md)
> **Status**: **PENDING ASSIGNMENT**

## 1. Objective
Implement the Kinetic Protocol to achieve <50ms startup latency by shifting `velo serve` to an IPC Client model.

## 2. P0 Implementation Requirements (Rust)
- [ ] **Kinetic Client**: Modify `src/serve/runner.rs` to implement the handshake logic.
- [ ] **10ms Wall-Clock Timeout**: strictly enforced during the entire handshake.
- [ ] **Silent Fallback**: Transparently drop to cold start on *any* IPC failure (`EPIPE`, `ECONNRESET`, etc.).
- [ ] **macOS Peer Sec**: Implement `getpeereid` check or Inode verification for the UDS socket.

## 3. P0 Implementation Requirements (Python)
- [ ] **Kinetic Server**: Modify `velo_zygote/main.py`.
- [ ] **SO_PEERCRED**: Enforce UID matching on Linux.
- [ ] **PRNG Re-Seed**: Call `random.seed(secrets.token_bytes(32))` and `os.urandom(1)` immediately post-fork.
- [ ] **Profile Storage**: Store `kinetic_profile.json` in `.velo/` hidden directory.

## 4. Acceptance Criteria (Definition of Done)
- [ ] Code passes `cargo clippy` and `cargo fmt`.
- [ ] No regression in Cold Start stability.
- [ ] Security audit confirms no identity leakage in the Zygote.
