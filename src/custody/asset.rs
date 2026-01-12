//! Embedded asset management for uv toolchain
//!
//! This module handles platform-specific binary embedding and metadata.
//! The actual binaries are downloaded at build time via build.rs.

use crate::custody::error::{CustodyError, Result};

/// Platform identifier for the current compilation target
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Platform {
    MacOsArm64,
    MacOsX86_64,
    LinuxX86_64,
}

impl Platform {
    /// Detect the current platform at compile time
    #[cfg(all(target_os = "macos", target_arch = "aarch64"))]
    pub const CURRENT: Platform = Platform::MacOsArm64;

    #[cfg(all(target_os = "macos", target_arch = "x86_64"))]
    pub const CURRENT: Platform = Platform::MacOsX86_64;

    #[cfg(all(target_os = "linux", target_arch = "x86_64"))]
    pub const CURRENT: Platform = Platform::LinuxX86_64;

    // Fallback for unsupported platforms (Windows, etc.)
    #[cfg(not(any(
        all(target_os = "macos", target_arch = "aarch64"),
        all(target_os = "macos", target_arch = "x86_64"),
        all(target_os = "linux", target_arch = "x86_64")
    )))]
    pub const CURRENT: Platform = Platform::LinuxX86_64; // Will fail at runtime

    /// Get the asset filename for this platform
    pub fn asset_name(&self) -> &'static str {
        match self {
            Platform::MacOsArm64 => "uv-aarch64-apple-darwin",
            Platform::MacOsX86_64 => "uv-x86_64-apple-darwin",
            Platform::LinuxX86_64 => "uv-x86_64-unknown-linux-musl",
        }
    }
}

/// Embedded uv binary asset
pub struct UvAsset {
    /// Platform this asset is for
    pub platform: Platform,
    /// Raw binary bytes (will be populated when assets are embedded)
    bytes: Option<&'static [u8]>,
    /// BLAKE3 hash for integrity verification
    blake3_hash: Option<&'static str>,
}

impl UvAsset {
    /// Check if embedded assets are available
    pub fn is_available() -> bool {
        // For now, return false until assets are embedded
        // This will be updated when build.rs downloads the binaries
        cfg!(feature = "embedded_uv")
    }

    /// Get the embedded asset for the current platform
    pub fn current() -> Result<Self> {
        let platform = Platform::CURRENT;

        // Check if we're on a supported platform
        #[cfg(not(any(
            all(target_os = "macos", target_arch = "aarch64"),
            all(target_os = "macos", target_arch = "x86_64"),
            all(target_os = "linux", target_arch = "x86_64")
        )))]
        {
            return Err(CustodyError::UnsupportedPlatform);
        }

        Ok(Self {
            platform,
            bytes: None,       // Placeholder until assets embedded
            blake3_hash: None, // Placeholder until build.rs generates
        })
    }

    /// Get the raw bytes of the embedded binary
    pub fn bytes(&self) -> Result<&[u8]> {
        self.bytes.ok_or(CustodyError::UnsupportedPlatform)
    }

    /// Get the expected BLAKE3 hash
    pub fn expected_hash(&self) -> Option<&str> {
        self.blake3_hash
    }

    /// Get the size of the embedded binary
    pub fn size(&self) -> usize {
        self.bytes.map(|b| b.len()).unwrap_or(0)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_platform_asset_name() {
        assert_eq!(Platform::MacOsArm64.asset_name(), "uv-aarch64-apple-darwin");
        assert_eq!(Platform::MacOsX86_64.asset_name(), "uv-x86_64-apple-darwin");
        assert_eq!(
            Platform::LinuxX86_64.asset_name(),
            "uv-x86_64-unknown-linux-musl"
        );
    }

    #[test]
    fn test_current_platform_detection() {
        // Should compile and not panic
        let _ = Platform::CURRENT;
    }
}
