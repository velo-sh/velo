# QA-REQ-003: Configurable Bundle Size Limit

## 1. Overview
RFC-0006 hardcoded the 256MB limit for DoS prevention. Phase 5.2 externalizes this into `pyproject.toml` while maintaining a secure default.

## 2. Security Red Lines (Mandatory)
- **SEC-001**: System MUST default to 256MB if no configuration is present.
- **SEC-002**: System MUST reject negative or non-numeric values in `max_bundle_size` and fallback to 256MB.
- **SEC-003**: The limit MUST be enforced BEFORE the file is read into memory (Rust: `security.rs`, Python: `velo_loader.py`).

## 3. Test Matrix

### 3.1 Unit Testing (Rust)
| Test ID | Scenario | Expected Result |
|---------|----------|-----------------|
| UNIT-CONF-001 | `max_bundle_size = 512` in TOML | `VeloConfig` returns `512 * 1024 * 1024` bytes |
| UNIT-SEC-001 | No config, 257MB file | `LoaderError::BundleTooLarge` |
| UNIT-SEC-002 | `max_bundle_size = 400`, 300MB file | Success (Validation Passed) |

### 3.2 Integration Testing (E2E)
| Test ID | Scenario | Expected Result |
|---------|----------|-----------------|
| E2E-FAST-001 | `velo run --fast` with oversized bundle and no config | CLI error: Bundle too large (256MB limit) |
| E2E-FAST-002 | `velo run --fast` with oversized bundle and override | Successful import & execution (Speedup ≥3x) |
| E2E-COMPAT-003 | Django project with custom `max_bundle_size` | Server starts successfully (Fulfills RFC-0006 requirements) |
| E2E-ZYG-001 | Zygote start with `max_bundle_size` in project TOML | Zygote respects the limit for preloaded bundles |

## 4. Hardening Traceability (Audit P0s)
The following tests (to be implemented in `tests/security/`) MUST verify the P0 fixes:
- **SEC-AUD-001**: Global Hash Tampering (Header/Data).
- **SEC-AUD-002**: Recursive Marshal Bomb (Depth > 500).
- **SEC-AUD-003**: Symlink/Canonicalization Bypass.
- **SEC-AUD-004**: TOCTOU File Replacement (Atomic Read).

## 5. Professional Advice for Implementation
1. **Centralized Constant**: Define `DEFAULT_MAX_BUNDLE_SIZE` in `src/loader/security.rs`.
2. **Triple Magic Check**: In `header.rs`, verify `MAGIC` + `VERSION` + `ABI` tag simultaneously.
3. **Python Sync**: Inject the *effective limit* as a literal to Python to prevent Config Drift.
