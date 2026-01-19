# SPEC-0009: vtest Naming Sovereignty

> **Status**: **TITANIUM (Active)**
> **Authority**: The Grand Council
> **Version**: 1.0.0

## 1. The Mandate

To prevent ambiguity between standard Rust/Python testing and Velo's Zygote-accelerated native orchestration, the marker **`vtest`** is hereby declared the exclusive sovereign identifier for all components related to `velo test`.

## 2. Distinction: `test` vs `vtest`

| Feature | `test` (Internal/Standard) | `vtest` (Velo Native) |
|:---|:---|:---|
| **Context** | Rust unit tests (`#[test]`) or generic logic. | Velo's end-to-end test orchestration engine. |
| **Orchestration** | Handled by `cargo test` or `pytest`. | Handled by Velo's `TestCoordinator` + Zygote. |
| **Performance** | Standard process spawning. | Miracle Fork (Zygote COW) acceleration. |
| **Sovereignty** | High collision risk. | **Zero collision** (Velo-exclusive namespace). |

## 3. Implementation Standards

### 3.1. Directory Structure
All native Crate/Module code for the test executor MUST reside in directories named `vtest`.
- **Correct**: `src/vtest/`, `crates/vtest/`
- **Incorrect**: `src/test/`

### 3.2. Code Artifacts
- **Binary/Command**: `velo test` (Internal alias: `vtest`)
- **Structs**: `VtestCoordinator`, `VtestWorker`
- **Internal Modules**: `velo::vtest`

### 3.3. Documentation
All RFCs and User Guides must refer to the feature as **`vtest`** when discussing implementation details, while the user-facing command remains `velo test`.

## 4. Enforcement

- **Architectural Audit**: Any use of the generic `test` name for Velo's native test features will be flagged as a **P1 Architectural Defect**.
- **CI Linting**: Future CI checks will enforce the absence of generic `test` naming in core execution paths.

---

**Custodian**: Velo Architect
**Last Updated**: 2026-01-19
