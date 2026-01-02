//! Bundle header structure and validation
//!
//! RFC-0006 Section 2.17: Enhanced Header

use crate::loader::error::{LoaderError, Result};

/// Magic bytes for Velo bundle format
pub const MAGIC: &[u8; 4] = b"VELO";

/// Current bundle format version
pub const VERSION: u32 = 1;

/// Page size for alignment (4KB)
pub const PAGE_SIZE: u64 = 4096;

/// Hash algorithm identifier (RFC-0006 Section 2.17)
#[repr(u8)]
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum HashAlgorithm {
    /// BLAKE3 (default, 3-6 GB/s)
    Blake3 = 0,
    // Reserved: Sha256 = 1, Sha3 = 2
}

impl HashAlgorithm {
    pub fn from_u8(v: u8) -> Option<Self> {
        match v {
            0 => Some(HashAlgorithm::Blake3),
            _ => None,
        }
    }

    pub fn name(&self) -> &'static str {
        match self {
            HashAlgorithm::Blake3 => "BLAKE3",
        }
    }
}

/// Bundle header structure (RFC-0006 Section 2.17)
///
/// Complete header with all fields for full RFC compliance.
#[derive(Debug, Clone)]
pub struct BundleHeader {
    // === Identity ===
    /// Magic bytes: "VELO"
    pub magic: [u8; 4],
    /// Bundle format version
    pub version: u32,
    /// Hash algorithm (0 = BLAKE3)
    pub hash_algorithm: HashAlgorithm,

    // === Bundle Structure ===
    /// Size of module index section
    pub index_size: u32,
    /// Number of modules in bundle
    pub module_count: u32,
    /// Offset to module index
    pub index_offset: u64,

    // === Integrity ===
    /// Hash of data section (algorithm per hash_algorithm)
    pub content_hash: [u8; 32],
    /// BLAKE3 of import_graph.json (from Phase 4.0)
    pub import_graph_hash: [u8; 32],

    // === Python Environment ===
    /// ABI tag (e.g., "cp312-darwin-arm64")
    pub abi_tag: [u8; 32],
    /// Environment fingerprint (BLAKE3 from Phase 1.5)
    pub env_fingerprint: [u8; 32],
    /// Python version string (e.g., "3.12.1")
    pub python_version: [u8; 16],
    /// Cache tag (e.g., "cpython-312")
    pub cache_tag: [u8; 16],
    /// Optimization level: 0, 1 (-O), or 2 (-OO)
    pub optimize_level: u8,
    /// Page size (always 4096)
    pub page_size: u32,
}

impl BundleHeader {
    /// Parse and validate magic bytes
    pub fn parse_magic(data: &[u8]) -> Result<()> {
        if data.len() < 4 {
            return Err(LoaderError::InvalidMagic {
                actual: "too short".to_string(),
            });
        }

        if &data[..4] != MAGIC {
            return Err(LoaderError::InvalidMagic {
                actual: String::from_utf8_lossy(&data[..4]).to_string(),
            });
        }

        Ok(())
    }

    /// Validate bundle version
    pub fn validate_version(version: u32) -> Result<()> {
        if version != VERSION {
            return Err(LoaderError::InvalidVersion { version });
        }
        Ok(())
    }

    /// Check Python version compatibility
    pub fn check_python_version(bundle_version: &str, runtime_version: &str) -> Result<()> {
        if bundle_version != runtime_version {
            return Err(LoaderError::PythonVersionMismatch {
                bundle_version: bundle_version.to_string(),
                runtime_version: runtime_version.to_string(),
            });
        }
        Ok(())
    }

    /// Check cache tag compatibility
    pub fn check_cache_tag(bundle_tag: &str, runtime_tag: &str) -> Result<()> {
        if bundle_tag != runtime_tag {
            return Err(LoaderError::CacheTagMismatch {
                bundle_tag: bundle_tag.to_string(),
                runtime_tag: runtime_tag.to_string(),
            });
        }
        Ok(())
    }

    /// Align offset to page boundary (4KB)
    ///
    /// Handover Section 4: 对齐要求
    pub fn align_to_page(offset: u64) -> u64 {
        let page = PAGE_SIZE;
        offset.div_ceil(page) * page
    }

    /// Generate zero padding for alignment
    ///
    /// Handover Section 8: Padding must be 0x00 (compression-friendly)
    pub fn generate_padding(current_offset: usize) -> Vec<u8> {
        let page = PAGE_SIZE as usize;
        let aligned = current_offset.div_ceil(page) * page;
        let padding_len = aligned - current_offset;
        vec![0u8; padding_len]
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_magic_constant() {
        assert_eq!(MAGIC, b"VELO");
    }

    #[test]
    fn test_version_constant() {
        assert_eq!(VERSION, 1);
    }

    #[test]
    fn test_page_size_constant() {
        assert_eq!(PAGE_SIZE, 4096);
    }
}
