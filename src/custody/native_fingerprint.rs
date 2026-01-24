//! RFC-0035: Native Library Fingerprinting (INV-PRELOAD-001)
//!
//! This module implements the metadata structure and hashing logic for
//! mapping native libraries to their runtime fingerprints.

use anyhow::{Context, Result, bail};
use serde::{Deserialize, Serialize};
use std::fs::File;
use std::io::{Read, Seek, SeekFrom};
use std::path::{Path, PathBuf};

/// Runtime fingerprint of a native library
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NativeLibFingerprint {
    pub relative_path: PathBuf,
    pub package: String,
    pub soname: String,
    pub hash: String,        // Full BLAKE3 hash
    pub header_hash: String, // BLAKE3 of first 4KB
    pub mtime: u64,
    pub platform: LibPlatform,
    pub load_stage: LoadStage,
    /// Provenance information for future supply chain verification (Phase 7+)
    #[serde(skip_serializing_if = "Option::is_none")]
    pub provenance: Option<Provenance>,
}

/// Platform-specific metadata for compatibility checking
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LibPlatform {
    pub os: String,
    pub arch: String,
    pub python_version: String,
    pub libc_type: String,
    pub libc_version: String,
    pub soabi: String,
}

/// Provenance information for supply chain verification (RFC-0035 Phase 7 Roadmap)
/// Currently a placeholder for future implementation of:
/// - Code signing verification (macOS codesign, Linux sigstore)
/// - Build attestation (SLSA, PEP 740)
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Provenance {
    /// Signature type: "codesign" | "gpg" | "sigstore" | "slsa" | null
    #[serde(skip_serializing_if = "Option::is_none")]
    pub signature_type: Option<String>,
    /// Base64-encoded signature or attestation
    #[serde(skip_serializing_if = "Option::is_none")]
    pub signature: Option<String>,
    /// URL to verify attestation (e.g., sigstore transparency log)
    #[serde(skip_serializing_if = "Option::is_none")]
    pub attestation_url: Option<String>,
    /// Verification status from last analysis: "verified" | "unverified" | "unsigned"
    #[serde(skip_serializing_if = "Option::is_none")]
    pub status: Option<String>,
}

/// Loading stage for the library
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum LoadStage {
    /// Load before Python interpreter initialization
    PreInit,
    /// Load after Python interpreter initialization (e.g. extension modules)
    PostInit,
}

impl NativeLibFingerprint {
    /// Parse metadata (SONAME, NEEDED) from a native library (ELF or Mach-O)
    pub fn parse_native_lib(path: &Path) -> Result<(String, Vec<String>)> {
        let buffer = std::fs::read(path)
            .with_context(|| format!("Failed to read library for parsing: {:?}", path))?;

        let mut soname = String::new();
        let mut needed = Vec::new();

        match goblin::Object::parse(&buffer)? {
            goblin::Object::Elf(elf) => {
                soname = elf.soname.unwrap_or("").to_string();
                needed = elf.libraries.iter().map(|s| s.to_string()).collect();
            }
            goblin::Object::Mach(mach) => {
                // For Mach-O, we use the install name
                match mach {
                    goblin::mach::Mach::Binary(bin) => {
                        soname = bin.name.unwrap_or("").to_string();
                        // For libraries this is a list of dylibs
                        needed = bin.libs.iter().map(|s| s.to_string()).collect();
                    }
                    goblin::mach::Mach::Fat(_fat) => {
                        // For fat binaries, we'll just take the first slice?
                        // Simplified for now
                    }
                }
            }
            _ => bail!("Unsupported binary format for {:?}", path),
        }

        Ok((soname, needed))
    }

    /// Calculate BLAKE3 hashes for a library (header-only and full)
    pub fn calculate_hashes(path: &Path) -> Result<(String, String)> {
        let mut file = File::open(path)
            .with_context(|| format!("Failed to open library for hashing: {:?}", path))?;

        // 1. Header Hash (First 4KB)
        let mut header = [0u8; 4096];
        let bytes_read = file.read(&mut header)?;
        let header_hash = blake3::hash(&header[..bytes_read]).to_hex().to_string();

        // 2. Full Hash
        file.seek(SeekFrom::Start(0))?;
        let mut hasher = blake3::Hasher::new();
        let mut buffer = [0u8; 8192];
        loop {
            let n = file.read(&mut buffer)?;
            if n == 0 {
                break;
            }
            hasher.update(&buffer[..n]);
        }
        let full_hash = hasher.finalize().to_hex().to_string();

        Ok((full_hash, header_hash))
    }

    /// Verify library against fingerprint (INV-PRELOAD-001, INV-PRELOAD-007)
    /// Uses mtime as a fast-path (P2-002)
    pub fn verify(&self, path: &Path, deep_verify: bool) -> Result<bool> {
        let metadata = path
            .metadata()
            .with_context(|| format!("Failed to get metadata for {:?}", path))?;

        let current_mtime = metadata
            .modified()?
            .duration_since(std::time::UNIX_EPOCH)?
            .as_secs();

        // P2-002: Fast-path via mtime
        if current_mtime == self.mtime && !deep_verify {
            return Ok(true);
        }

        // Slow-path: Calculate hashes
        let (full_hash, header_hash) = Self::calculate_hashes(path)?;

        // Header verification for early exit
        if header_hash != self.header_hash {
            return Ok(false);
        }

        if deep_verify && full_hash != self.hash {
            return Ok(false);
        }

        Ok(true)
    }
}

/// Root structure of the `preload.lock` file (RFC-0035 §3.4)
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PreloadLock {
    pub version: String,
    pub generator: String,
    pub fingerprints: Vec<NativeLibFingerprint>,
}

impl PreloadLock {
    pub fn new(fingerprints: Vec<NativeLibFingerprint>) -> Self {
        Self {
            version: "1.0".to_string(),
            generator: format!("velo-{}", env!("CARGO_PKG_VERSION")),
            fingerprints,
        }
    }

    pub fn to_json(&self) -> Result<String> {
        serde_json::to_string_pretty(self).context("Failed to serialize preload.lock to JSON")
    }

    pub fn from_json(json: &str) -> Result<Self> {
        serde_json::from_str(json).context("Failed to parse preload.lock from JSON")
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use tempfile::tempdir;

    #[test]
    fn test_preload_lock_roundtrip() {
        let fp = NativeLibFingerprint {
            relative_path: PathBuf::from("lib/libtorch.so"),
            package: "torch".to_string(),
            soname: "libtorch.so".to_string(),
            hash: "full_hash".to_string(),
            header_hash: "head_hash".to_string(),
            mtime: 123456789,
            platform: LibPlatform {
                os: "linux".to_string(),
                arch: "x86_64".to_string(),
                python_version: "3.10".to_string(),
                libc_type: "gnu".to_string(),
                libc_version: "2.31".to_string(),
                soabi: "cpython-310-x86_64-linux-gnu".to_string(),
            },
            load_stage: LoadStage::PreInit,
            provenance: None,
        };

        let lock = PreloadLock::new(vec![fp]);
        let json = lock.to_json().unwrap();

        // Assert JSON contains key fields
        assert!(json.contains("\"version\": \"1.0\""));
        assert!(json.contains("\"generator\": \"velo-"));
        assert!(json.contains("\"relative_path\": \"lib/libtorch.so\""));

        let decoded: PreloadLock = PreloadLock::from_json(&json).unwrap();
        assert_eq!(decoded.version, "1.0");
        assert_eq!(decoded.fingerprints.len(), 1);
        assert_eq!(decoded.fingerprints[0].soname, "libtorch.so");
    }

    #[test]
    fn test_hash_calculation() {
        let tmp = tempdir().unwrap();
        let lib_path = tmp.path().join("test.so");
        let content = vec![0u8; 8192]; // 8KB
        fs::write(&lib_path, &content).unwrap();

        let (full, head) = NativeLibFingerprint::calculate_hashes(&lib_path).unwrap();
        assert_eq!(full, blake3::hash(&content).to_hex().to_string());
        assert_eq!(head, blake3::hash(&content[..4096]).to_hex().to_string());
    }

    #[test]
    fn test_mtime_fast_path() {
        let tmp = tempdir().unwrap();
        let lib_path = tmp.path().join("test.so");
        fs::write(&lib_path, "binary").unwrap();

        let metadata = lib_path.metadata().unwrap();
        let mtime = metadata
            .modified()
            .unwrap()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_secs();

        let mut fp = NativeLibFingerprint {
            relative_path: PathBuf::from("test.so"),
            package: "test".to_string(),
            soname: "test.so".to_string(),
            hash: "fake".to_string(),
            header_hash: "fake".to_string(),
            mtime,
            platform: LibPlatform {
                os: "linux".to_string(),
                arch: "x86_64".to_string(),
                python_version: "3.10".to_string(),
                libc_type: "gnu".to_string(),
                libc_version: "2.31".to_string(),
                soabi: "abc".to_string(),
            },
            load_stage: LoadStage::PreInit,
            provenance: None,
        };

        // 1. mtime matches, should skip hash and return true
        assert!(fp.verify(&lib_path, false).unwrap());

        // 2. mtime matches but deep_verify is true, should check hash and fail
        assert!(!fp.verify(&lib_path, true).unwrap());

        // 3. mtime changed, should check hash and fail
        fp.mtime -= 1;
        assert!(!fp.verify(&lib_path, false).unwrap());
    }
}
