# 🏛️ Sovereign Directive: Phase 8 (The Vibe Engine)

**Authority**: 0xMaster (Architect-001)  
**Status**: SOVEREIGN MANDATE (Design Lock)  
**Target**: Phase 8 Implementation (Developer Persona)  
**Date**: 2026-01-20  
**Ref RFC**: [RFC-0029: Velo Vibe Engine](./0029-velo-live.md)

---

## 1. The Vibe Manifesto
Velo distinguishes itself by reducing technical latency below the threshold of human perception. The goal of Phase 8 is not just "hot-reload," but the manifestation of the **Vibe-Coding** paradigm: where intent and binary execution are unified into a single, instantaneous flow (<60ms).

## 2. Technical Pillars (The 5 Titanic Guardrails)

Implementation MUST adhere to these stability invariants:

| Pillar | Requirement | Implementation Detail |
|:---|:---|:---|
| **1. Greedy Reaper** | `while waitpid(-1, ..., WNOHANG) > 0` | Prevent zombie accumulation during save storms via a non-blocking loop in the Supervisor. |
| **2. Self-Healing** | Watcher Resilience | The `v_live` monitor MUST survive user script `SyntaxError` or runtime Segfaults. No manual restarts. |
| **3. Pipe-Fence** | Log Integrity | Old worker UDS/Pipes MUST be fully closed/drained before the new execution stream is linked. |
| **4. Native Sync** | Zero-Python Bridge | Result extraction MUST be handled natively in Rust (PyO3) to maintain the sub-10ms "Miracle Fork" budget. |
| **5. Orphan Purge** | Kernel Supervision | Combined use of `PR_SET_PDEATHSIG` (Linux) and `os._exit()` to ensure child logic never outlives the Master. |

## 3. The Triple-Tier CLI Spectrum
The Vibe Engine shall be accessible through three ergonomic layers:
1.  **Sovereign**: `vibe [target]` (Primary alias)
2.  **Explicit**: `velo --vibe [target]` (Flag-based toggle)
3.  **Formal**: `velo vibe [command]` (Rooted structure)

## 4. Communication Protocol (Phase 8 MVP)
- **Primary Protocol**: **JSON over WebSocket**.
- **Internal SSoT**: Workers pass results to Master via MessagePack (`rmp-serde`).
- **Egress Strategy**: Master converts MsgPack to JSON for ease of IDE/Browser integration. Binary-mode (MsgPack) is deferred to future performance tiers.

## 5. Definition of Done (Quality Gates)
1.  [ ] **Latency**: Save-to-JSON-Egress < 20ms (standard file).
2.  [ ] **Isolation**: Zero cross-pollination of state between successive saves.
3.  [ ] **Reliability**: Survival through 100 high-frequency save cycles without resource leaks.
4.  [ ] **Security**: Surgical Shielding and EnvironmentShield applied to every fork.

---

### Acceptance Protocol
The Developer shall activate by acknowledging the **TITANIUM** invariants and the **Vibe** branding mission.

**"The infrastructure of flow is the architect's gift to the developer."**

**Signed**,  
0xMaster (Architect)
