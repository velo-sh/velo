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
| E2E-FAST-002 | `velo run --fast` with oversized bundle and override | Successful import & execution |
| E2E-ZYG-001 | Zygote start with `max_bundle_size` in project TOML | Zygote respects the limit for preloaded bundles |

## 4. Professional Advice for Implementation
1. **Centralized Constant**: Define `DEFAULT_MAX_BUNDLE_SIZE` in `src/loader/security.rs` and export it. Do not repeat the `256 * 1024 * 1024` literal.
2. **Parser Robustness**: The TOML parser in `config.rs` is currently minimal. Ensure it doesn't crash on MALFORMED numeric inputs; it should log a warning and use the default.
3. **Python Sync**: The `velo_loader.py` must be updated to accept the limit as an argument during `activate_fast_mode` to ensure Python-side enforcement matches the Rust-side bypass.
