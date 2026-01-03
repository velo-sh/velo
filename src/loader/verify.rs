//! Bundle verification using BLAKE3
//!
//! RFC-0006 Section 3.1: Secure Loading Sequence
//! CRITICAL: Read → Verify → Load atomic sequence
//!
//! BLAKE3 provides:
//! - 10x faster than SHA-256 (~3-6 GB/s vs ~0.5 GB/s)
//! - Matches NVMe SSD speed (hash no longer bottleneck)
//! - 256-bit output, 128-bit collision resistance
//! - Native Merkle Tree support for Phase 5.3

use crate::loader::error::{LoaderError, Result};

/// Verified bundle containing data already loaded into RAM
#[derive(Debug)]
pub struct VerifiedBundle {
    /// Raw bundle data (already in memory - TOCTOU safe)
    pub data: Vec<u8>,
    /// Header end offset (data starts after this)
    pub header_end: usize,
}

/// Verify BLAKE3 hash matches
///
/// RFC-0006 Section 3.1: TOCTOU Prevention
/// Data MUST already be in RAM when this is called.
///
/// BLAKE3 is ~10x faster than SHA-256 (~3-6 GB/s)
pub fn verify_blake3(data: &[u8], expected: &[u8; 32]) -> Result<()> {
    let actual = blake3::hash(data);

    if actual.as_bytes() != expected {
        return Err(LoaderError::BundleCorrupted {
            expected: hex::encode(expected),
            actual: hex::encode(actual.as_bytes()),
        });
    }

    Ok(())
}

/// Verify module integrity using BLAKE3
///
/// RFC-0006 Section 3.4: Unified BLAKE3 Verification
/// Replaces CRC32 - BLAKE3 is fast enough (~3-6 GB/s) and provides
/// both error detection AND tampering protection.
pub fn verify_module_hash(data: &[u8], expected: &[u8; 32], module_name: &str) -> Result<()> {
    let actual = blake3::hash(data);

    if actual.as_bytes() != expected {
        return Err(LoaderError::ModuleCorrupted {
            module_name: module_name.to_string(),
        });
    }

    Ok(())
}

/// Atomic: Read entire file → Verify → Return verified bundle
///
/// RFC-0006 Section 3.1: Secure Loading Sequence
/// This function implements the MANDATORY sequence:
/// 1. Sanity check: reject if size > 256MB (DoS prevention)
/// 2. Read entire file to RAM
/// 3. Verify BLAKE3 content_hash
/// 4. Return verified bundle (safe for marshal.loads())
pub fn load_and_verify(path: &std::path::Path, limit: Option<u64>) -> Result<VerifiedBundle> {
    use crate::loader::header::BundleHeader;
    use crate::loader::security;

    let effective_limit = limit.unwrap_or(security::DEFAULT_MAX_BUNDLE_SIZE);

    // Step 0: Security checks BEFORE reading
    security::validate_all(path, effective_limit)?;

    // Step 1: Read entire file to RAM (TOCTOU-safe)
    let data = std::fs::read(path)?;

    // Step 2a: Validate magic
    BundleHeader::parse_magic(&data)?;

    // Step 2b: Extract content hash and index offset from header
    // Header layout:
    // 0..4: MAGIC
    // 4..8: VERSION
    // 8..12: COUNT
    // 12..20: INDEX_OFFSET (u64 LE)
    // 20..52: CONTENT_HASH (32 bytes)
    if data.len() < 52 {
        return Err(LoaderError::BundleCorrupted {
            expected: "valid header (at least 52 bytes)".to_string(),
            actual: format!("{} bytes", data.len()),
        });
    }

    let mut index_offset_bytes = [0u8; 8];
    index_offset_bytes.copy_from_slice(&data[12..20]);
    let index_offset = u64::from_le_bytes(index_offset_bytes) as usize;

    let mut expected_hash = [0u8; 32];
    expected_hash.copy_from_slice(&data[20..52]);

    let header_end = 128;

    // Step 2c: Verify BLAKE3 of data section (~3-6 GB/s)
    if data.len() >= index_offset && index_offset > header_end {
        verify_blake3(&data[header_end..index_offset], &expected_hash)?;
    } else if index_offset > header_end {
        // Truncated data section
        return Err(LoaderError::BundleCorrupted {
            expected: format!("data section up to {}", index_offset),
            actual: "truncated".to_string(),
        });
    }

    // Step 3: Return verified bundle
    Ok(VerifiedBundle { data, header_end })
}

#[cfg(test)]
mod tests {

    #[test]
    fn test_blake3_calculation() {
        let data = b"test data";
        let hash = blake3::hash(data);
        assert!(hash.as_bytes().iter().any(|&b| b != 0)); // Non-zero hash
    }

    #[test]
    fn test_blake3_speed_note() {
        // BLAKE3 is ~10x faster than SHA-256
        // ~3-6 GB/s vs ~0.5 GB/s
        // This matches NVMe SSD speed, so hash is no longer the bottleneck
        let data = vec![0u8; 1024 * 1024]; // 1MB
        let _hash = blake3::hash(&data);
        // In production: 1MB at 3GB/s = 0.33ms
    }
}
