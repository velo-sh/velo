# Handoff Checklist: Phase 8 (Vibe Engine)

**Reference**: [Sovereign Directive: Phase 8](./handover_developer_phase_8_live.md)  
**Goal**: Implement and verify the sub-60ms Vibe-Coding loop.

---

## 💻 Developer Task List (Implementation)

### 1. Engine Core (`src/v_live/`)
- [ ] **Sovereign Command**: Implement `vibe` as a bin alias to `velo vibe`.
- [ ] **The Greedy Reaper**: Implement `while waitpid(-1, ..., WNOHANG) > 0` in the Master supervisor loop.
- [ ] **Self-Healing Watcher**: Refactor file-watcher to ignore `SyntaxError` crashes, maintaining the watch loop.
- [ ] **Pipe-Fence Isolation**: Implement atomic closing/draining of stale child UDS before new child binding.
- [ ] **Sub-10ms Fork**: Optimize the `Miracle Fork` path using `os._exit(0)` and native PyO3 result extraction.

### 2. WebSocket Gateway (`src/v_live/gateway.rs`)
- [ ] **JSON Default Egress**: Implement MessagePack-to-JSON conversion for default WebSocket frames.
- [ ] **Session Tracking**: Implement heartbeat/idle cleanup to prune dead connections.
- [ ] **Frame Management**: Enforce 5MB hard limit on outgoing frames.

### 3. CLI & Command Spectrum
- [ ] **`--vibe` Flag**: Support the flag on `velo run`, `velo serve`, and `velo test`.
- [ ] **Instant TDD**: Bind `velo test --vibe` to trigger `vtest` via the live monitor.

---

## 🧪 QA Task List (Verification)

### 1. Stability Audit (Adversarial)
- [ ] **Zombie Storm Test**: Run 100 saves in 10 seconds; verify 0 zombie processes remain.
- [ ] **Syntax Error Survival**: Inject a `SyntaxError`; verify the `vibe` monitor remains active and recovers on the next valid save.
- [ ] **Orphan Protection**: Kill the Master process (SIGKILL); verify all Python child forks are reaped by the kernel.

### 2. Performance Gate (The 60ms Rule)
- [ ] **Latency Benchmark**: Measure E2E latency from *File Save* to *WebSocket JSON Egress*. Target: **< 20ms**.
- [ ] **Log Isolation**: Verify that logs from a killed stale worker never leak into the output of the current worker.

### 3. Protocol Verification
- [ ] **JSON Compliance**: Verify that standard browser-based WebSocket clients can parse the output without custom decoders.
- [ ] **Frame Cap**: Stress test with a 10MB variable watch; verify the 5MB truncation or rejection logic.

---

**Authorized by**: 0xMaster (Architect)
