//! RFC-0015 Architectural Invariants & Constants
//!
//! This module centralizes magic numbers and hardcoded strings for the
//! Memory Gravity subsystem to ensure "First Principles" architectural robustness.

use std::path::Path;

/// H-29 Invariant: Shared memory segments MUST be aligned to 64-byte boundaries.
pub const VELO_ALIGNMENT: usize = 64;

/// Safetensors Header Prefix Size (u64 LE)
pub const HEADER_LEN_SIZE: usize = 8;

/// Environment variable to enable strict NUMA enforcement (H-30).
pub const ENV_STRICT_NUMA: &str = "VELO_STRICT_NUMA";

/// Environment variable to configure the NUMA nodemask (bitmask).
pub const ENV_NUMA_MASK: &str = "VELO_NUMA_MASK";

/// Default NUMA mask (Node 0 only).
pub const DEFAULT_NUMA_MASK: u64 = 1;

/// Default segment name for SHM creation.
pub const DEFAULT_SEGMENT_NAME: &str = "velo-shm";

// --- Linux Specific Invariants ---

#[cfg(target_os = "linux")]
pub mod linux {
    /// NUMA policy constant for strict binding.
    pub const MPOL_BIND: libc::c_int = 2;

    /// NUMA policy flag for strict allocation.
    pub const MPOL_MF_STRICT: libc::c_uint = 1 << 0;

    /// Maximum number of NUMA nodes supported in the bitmask.
    pub const NUMA_MAX_NODES: libc::c_ulong = 64;
}

/// Helper to check if a path is a valid safetensors source.
pub fn is_valid_safetensors(path: &Path) -> bool {
    path.extension()
        .map(|s| s == "safetensors")
        .unwrap_or(false)
}
