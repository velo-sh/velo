# Phase 6.1: The Hook - QA Handover

> **Goal**: Verify robustness, performance, and security of the Velo server exoskeleton.
> **Reference**: [RFC-0010](../../rfcs/0010-phase-6.1-serve-analyze.md)

## 🧪 Test Matrix & Verification Goals

### 1. Framework Detection
- [ ] **T1**: FastAPI instance detection.
- [ ] **T2**: Flask factory pattern detection.
- [ ] **T3**: Django `wsgi.py`/`asgi.py` detection.
- [ ] **T4**: Verify "Did you mean?" suggestions for invalid CLI inputs.

### 2. Hot Reload & Signals
- [ ] **T5**: Measure restart time (Write -> Ready) - Goal < 50ms.
- [ ] **T6**: Verify clean `sys.modules` after restart.
- [ ] **T7**: Verify signal forwarding: `Ctrl+C` kills entire process tree.

### 3. Analyze & Insights
- [ ] **T8**: Verify `stat()` savings report accuracy using `strace`.
- [ ] **T9**: Verify JSON export consistency with CLI display.

### 4. Security
- [ ] **SEC-T1**: Verify path traversal protection in discovery.
- [ ] **SEC-T2**: Verify `O_EXCL` flags on PID files.
- [ ] **SEC-T3**: Verify correct `.venv` isolation for user projects.

## 🏁 Acceptance Criteria
1. **Zero Zombies**: No orphanned processes after exit.
2. **Performance**: Mean restart latency < 50ms.

---
*Signed by: Architect*
