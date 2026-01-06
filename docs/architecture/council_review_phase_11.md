# Council Review Summary: Phase XI (Kinetic Optimization)

> **Authority**: SOP-001 / `/ask-council`
> **Subject**: Implementation Plan (IPC Client Architecture)
> **Date**: 2026-01-06

## 1. The Summons (Attendees)

| Role | Representing | Justification |
|:---|:---|:---|
| **Rust Core Dev** | Systems Safety | Modifying `runner.rs` (process spawn logic) is high risk. |
| **Python Core Dev** | Runtime Internals | `velo_zygote` preload tuning affects all users. |
| **Performance Eng** | Latency | The entire goal is <50ms. |
| **Architect** | Governance | Major architecture change (Spawner -> Client). |

## 2. The Critique (Simulation)

### 🦀 Rust Core Developer
> "I see you're changing `runner.rs` to talk to a unix socket.
> **Concern**: How do you handle file descriptor passing stability? If the Zygote crashes during the handshake, does the CLI hang?
> **Requirement**: The 'Slow Path' (Fallback) must be absolutely robust. If the IPC fails for *any* reason, it must transparently silently spawn a new process."

### 🐍 Python Core Developer
> "We are optimizing `importlib` in the Zygote.
> **Concern**: If we preload too much, we bloat memory. If we preload too little, we miss the 50ms target.
> **Requirement**: We need a 'Profile-Guided Preload' list, not a hardcoded guess."

### ⏱️ Performance Engineer
> "50ms is extremely aggressive. The 'Magic Handshake' overhead + FD passing overhead must be < 5ms total.
> **Requirement**: We must benchmark the IPC roundtrip cost itself, separate from Python startup."

### 🏛️ Architect
> "This is a fundamental shift. We are effectively introducing a Daemon.
> **Blocking**: SOP-001 requires an RFC for this. Where is **RFC-0013**?"

## 3. The Verdict

**✅ APPROVED**

### P0 Resolvents
1.  **RFC-0013 Created**: [RFC-0013-kinetic-protocol.md](../rfcs/0013-kinetic-protocol.md) is ratified and defines the IPC protocol.
2.  **Safety Invariant**: Section 3.1 of RFC-0013 formally defines the "Silent Fallback" to prevent zombies.

**Phase XI is clear for Implementation.** Mission is Go.
