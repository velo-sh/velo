//! Custody module - Embedded toolchain management for Velo (RFC-0018)
//!
//! This module implements the "Integrated Custody" model where Velo embeds
//! and manages the `uv` toolchain as a private asset, eliminating external
//! dependency requirements for users.
//!
//! # Architecture
//!
//! ```text
//! ┌─────────────────────────────────────────────────────────────────┐
//! │                    Velo Binary (Rust)                           │
//! │  ┌──────────────────────────────────────────────────────────┐   │
//! │  │  Embedded uv bytes (include_bytes!)                      │   │
//! │  │  ├── uv-aarch64-apple-darwin                             │   │
//! │  │  ├── uv-x86_64-apple-darwin                              │   │
//! │  │  └── uv-x86_64-unknown-linux-musl                        │   │
//! │  └──────────────────────────────────────────────────────────┘   │
//! │                           │                                      │
//! │                    Custodian Trait                               │
//! │                           │                                      │
//! │                    ┌──────▼──────┐                               │
//! │                    │  extract()  │──► ~/.velo/bin/{hash}/uv     │
//! │                    │  verify()   │    (BLAKE3 verified)          │
//! │                    │  execute()  │                               │
//! │                    └─────────────┘                               │
//! └─────────────────────────────────────────────────────────────────┘
//! ```

pub mod asset;
pub mod autopilot;
pub mod custodian;
pub mod error;
pub mod fingerprint;
pub mod native_fingerprint;
pub mod preload_loader;
pub mod preload_orchestrator;
pub mod preload_verifier;
pub mod sync;

pub use autopilot::{AutopilotDecision, AutopilotEngine};
pub use custodian::{Custodian, UvCustodian};
pub use error::{CustodyError, Result};
pub use fingerprint::EnvironmentFingerprint;
pub use sync::EnvironmentSync;

/// Get the Velo build hash for versioned extraction paths
pub fn velo_build_hash() -> &'static str {
    // Use the git commit hash or cargo package version
    option_env!("VELO_BUILD_HASH").unwrap_or(env!("CARGO_PKG_VERSION"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_velo_build_hash_not_empty() {
        let hash = velo_build_hash();
        assert!(!hash.is_empty(), "Build hash should not be empty");
    }
}
