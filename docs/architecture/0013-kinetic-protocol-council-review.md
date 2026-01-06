# Grand Council Review: RFC-0013 Kinetic Protocol

> **Authority**: SOP-001 Master Lifecycle
> **Date**: 2026-01-06
> **Verdict**: ✅ **APPROVED** (Unanimous Consent)

---

## 1. Summary

RFC-0013 proposes the **Kinetic Protocol**, shifting `velo serve` from Process Spawner to Resilient IPC Client for <50ms startup.

---

## 2. Council Composition

| Persona | Reason |
|:---|:---|
| Architect | Fundamental architecture shift |
| Security Engineer | `SO_PEERCRED`, socket probing, taint |
| Rust Core Dev | `KineticClient` hot path |
| Python Core Dev | `KineticServer`, fork, PGO |
| HPC Engineer | <50ms performance SLA |
| Network SRE | IPC handshake, fallback logic |

---

## 3. Votes

| Persona | Vote | Concern |
|:---|:---|:---|
| Architect | ✅ APPROVE    | Formally accepted with RFC v1.1 amendments |
| Security Engineer | ✅ APPROVE    | P0-1 (SO_PEERCRED) Resolved (§5.1) |
| Rust Core Dev | ✅ APPROVE    | 10ms budget clarified (§3.1) |
| Python Core Dev | ✅ APPROVE    | P0-2 (PRNG re-seeding) Resolved (§5.2) |
| HPC Engineer | ✅ APPROVE    | MAX_PROFILE_SIZE added (§4.1) |
| Network SRE | ✅ APPROVE    | Fallback triggers enumerated (§3.1) |

---

## 4. P0 Blocking Issues

> [!CAUTION]
> These MUST be resolved before re-review.

| ID | Issue | Status |
|:---|:---|:---:|
| **P0-1** | `SO_PEERCRED` failure handling | ✅ RESOLVED |
| **P0-2** | Post-fork PRNG re-seeding | ✅ RESOLVED |

---

## 5. P1 Issues

| ID | Issue | Owner |
|:---|:---|:---|
| P1-1 | Clarify 10ms timeout: global budget or per-step? | Rust |
| P1-2 | Add `MAX_PROFILE_SIZE` (e.g., 64KB) for PGO profile | HPC |
| P1-3 | List fallback triggers: `EPIPE`, `ECONNRESET`, `ECONNREFUSED`, `ETIMEDOUT` | Network |
| P1-4 | Link to `implementation_plan.md` per SOP-001 | Architect |

---

## 6. Recommended RFC Amendments

### 6.1 Section 5 (Security) - Add:

```markdown
### 5.1 SO_PEERCRED Failure Handling
* **Action**: If `getsockopt(SO_PEERCRED)` fails or UID mismatch → close socket immediately.
* **Logging**: Log at `WARN` level with peer PID (if available).
* **Fallback**: This does NOT trigger Cold Start fallback; it's a security rejection.
```

### 6.2 Section 5 (Security) - Add:

```markdown
### 5.2 Taint Re-Randomization Contract
Post-fork, the child MUST call:
1. `random.seed(secrets.token_bytes(32))`
2. `os.urandom(1)` (force kernel entropy refill)
This MUST happen BEFORE any user code executes.
```

### 6.3 Section 3.1 - Clarify:

```markdown
* **Timeout Budget**: The 10ms covers the ENTIRE handshake (connect + auth + payload + ack).
```

---

## 7. Next Steps

1. **Architect**: Amend RFC-0013 with sections 6.1, 6.2, 6.3 above.
2. **Re-submit**: Call `/ask-council` again after amendments.
3. **Proceed**: Only upon **UNANIMOUS CONSENT**.

---

**Signed**: Grand Council (Simulated)
