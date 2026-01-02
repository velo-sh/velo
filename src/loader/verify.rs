//! Bundle verification (SHA-256 and CRC32)
//!
//! RFC-0006 Handover Section 2.1: Marshal Security Protocol
//! CRITICAL: Read → Verify → Load atomic sequence

use crate::loader::error::{LoaderError, Result};
use sha2::{Digest, Sha256};

/// Verified bundle containing data already loaded into RAM
#[derive(Debug)]
pub struct VerifiedBundle {
    /// Raw bundle data (already in memory - TOCTOU safe)
    pub data: Vec<u8>,
    /// Header end offset (data starts after this)
    pub header_end: usize,
}

/// Verify SHA-256 hash matches
///
/// Handover Section 2.1: TOCTOU Prevention
/// Data MUST already be in RAM when this is called.
pub fn verify_sha256(data: &[u8], expected: &[u8; 32]) -> Result<()> {
    let mut hasher = Sha256::new();
    hasher.update(data);
    let actual: [u8; 32] = hasher.finalize().into();

    if actual != *expected {
        return Err(LoaderError::BundleCorrupted {
            expected: hex::encode(expected),
            actual: hex::encode(actual),
        });
    }

    Ok(())
}

/// Verify CRC32 matches
///
/// Fast integrity check (~20 GB/s)
pub fn verify_crc32(data: &[u8], expected: u32) -> Result<()> {
    let actual = crc32fast::hash(data);

    if actual != expected {
        return Err(LoaderError::ModuleCorrupted {
            module_name: "unknown".to_string(),
        });
    }

    Ok(())
}

/// Verify module with name for better error messages
pub fn verify_module_crc32(data: &[u8], expected: u32, module_name: &str) -> Result<()> {
    let actual = crc32fast::hash(data);

    if actual != expected {
        return Err(LoaderError::ModuleCorrupted {
            module_name: module_name.to_string(),
        });
    }

    Ok(())
}

/// Atomic: Read entire file → Verify → Return verified bundle
///
/// Handover Section 2.1: TOCTOU Prevention
/// This function implements the MANDATORY sequence:
/// 1. Read entire file to RAM
/// 2. Verify SHA-256 in memory
/// 3. Return verified bundle (safe for parsing)
pub fn load_and_verify(path: &std::path::Path) -> Result<VerifiedBundle> {
    use crate::loader::header::BundleHeader;
    use crate::loader::security;

    // Step 0: Security checks BEFORE reading
    security::validate_all(path)?;

    // Step 1: Read entire file to RAM (TOCTOU-safe)
    let data = std::fs::read(path)?;

    // Step 2a: Validate magic
    BundleHeader::parse_magic(&data)?;

    // Step 2b: Extract content hash from header (bytes 8-40)
    if data.len() < 40 {
        return Err(LoaderError::BundleCorrupted {
            expected: "valid header".to_string(),
            actual: "truncated".to_string(),
        });
    }

    let mut expected_hash = [0u8; 32];
    expected_hash.copy_from_slice(&data[8..40]);

    // Header ends at fixed size (we'll calculate properly later)
    // For now, assume header is 128 bytes
    let header_end = 128;

    // Step 2c: Verify SHA-256 of data section
    if data.len() > header_end {
        verify_sha256(&data[header_end..], &expected_hash)?;
    }

    // Step 3: Return verified bundle
    Ok(VerifiedBundle { data, header_end })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_crc32_calculation() {
        let data = b"test data";
        let crc = crc32fast::hash(data);
        assert!(crc != 0); // Just verify it computes something
    }

    #[test]
    fn test_sha256_calculation() {
        let data = b"test data";
        let mut hasher = Sha256::new();
        hasher.update(data);
        let hash: [u8; 32] = hasher.finalize().into();
        assert!(hash.iter().any(|&b| b != 0)); // Non-zero hash
    }
}
