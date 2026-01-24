//! RFC-0035: Native Library Fingerprinting (INV-PRELOAD-001)
//!
//! This module implements the metadata structure and hashing logic for
//! mapping native libraries to their runtime fingerprints.

use anyhow::{Context, Result};
use goblin::elf::Elf;
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

/// Loading stage for the library
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum LoadStage {
    /// Load before Python interpreter initialization
    PreInit,
    /// Load after Python interpreter initialization (e.g. extension modules)
    PostInit,
}

impl NativeLibFingerprint {
    /// Parse ELF metadata (SONAME, NEEDED) from a library
    pub fn parse_elf(path: &Path) -> Result<(String, Vec<String>)> {
        let buffer = std::fs::read(path)
            .with_context(|| format!("Failed to read library for ELF parsing: {:?}", path))?;
        let elf =
            Elf::parse(&buffer).with_context(|| format!("Failed to parse ELF: {:?}", path))?;

        let soname = elf.soname.unwrap_or("").to_string();
        let needed = elf.libraries.iter().map(|s| s.to_string()).collect();

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
}
