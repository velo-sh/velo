# Detailed Design: Asset Management (uv Embedding)

This document provides the architectural specification for the `Asset Management` component, responsible for the lifecycle and custody of the embedded `uv` toolchain.

## 1. The `Custodian` Trait
The `Custodian` trait defines the contract for managing embedded binaries across diverse operating systems and architectures.

```rust
pub trait Custodian {
    /// Returns the target extraction path including build-hash.
    fn target_path(&self) -> PathBuf;

    /// Verifies the integrity of the extracted asset.
    fn verify(&self) -> Result<bool, CustodyError>;

    /// Atomic extraction of the embedded bytes to the target path.
    fn extract(&self) -> Result<(), CustodyError>;

    /// Executes a managed command through the toolchain context.
    fn execute(&self, args: Vec<String>) -> Result<ExitStatus, CustodyError>;
}
```

## 2. Platform-Specific Meta-Matrix
The Velo binary embeds three primary toolchain variants:

| OS | Arch | cfg Attribute | Asset Name |
| :--- | :--- | :--- | :--- |
| macOS | arm64 | `all(target_os="macos", target_arch="aarch64")` | `uv-aarch64-apple-darwin` |
| macOS | x86_64 | `all(target_os="macos", target_arch="x86_64")` | `uv-x86_64-apple-darwin` |
| Linux | x86_64 | `all(target_os="linux", target_arch="x86_64")` | `uv-x86_64-unknown-linux-musl` |

## 3. Atomic Extraction Protocol (SEC-GATED)
To satisfy **RFC-0012** (Surgical Shielding) and protect against TOCTOU/race conditions:

1.  **Isolation**: Set `umask(077)` before directory creation.
2.  **Creation**: Create `~/.velo/bin/{build_hash}/` with `0o700`.
3.  **Temporary Write**: Write embedded bytes to `uv.tmp` within the target directory.
4.  **Permission Hardening**: Apply `0o755` to `uv.tmp`.
5.  **Atomic Handover**: Use `std::fs::rename("uv.tmp", "uv")`. This ensures a single atomic "Commit" of the binary to the system.

## 4. Command Shadowing (The Proxy Model)
Velo acts as a thin proxy to the embedded `uv` to maintain the **"Integrated Custody"** illusion.

*   **Logic**: When `velo python` is called, the supervisor maps this to:
    ```bash
    ~/.velo/bin/{hash}/uv run --no-config --python-preference only-managed ...
    ```
*   **Environment Scrubbing**: The proxy MUST unset `PYTHONPATH` and `PYTHONHOME` from the host environment to ensure the managed `.venv` remains hermetic.

## 5. Environment Convergence (Fingerprinting)
Velo maintains a `.velo/env.state` file containing:
*   **Source Hashes**: BLAKE3 hash of `pyproject.toml` and `uv.lock`.
*   **Velo Identity**: Build hash of the executing Velo binary.

If the state is missing or hashes mismatch, Velo triggers an implicit `uv sync` before proceeding with the user's command.
