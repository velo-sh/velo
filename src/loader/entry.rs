//! Module entry and index structures
//!
//! RFC-0006 Section 2.4: ModuleEntry with unified BLAKE3 hash

use crate::loader::error::Result;
use std::collections::HashMap;

/// Module entry in bundle index
///
/// RFC-0006 Section 2.4: ModuleEntry structure
/// Uses unified BLAKE3 hash (replaces CRC32 + source_hash)
#[derive(Debug, Clone, PartialEq)]
pub struct ModuleEntry {
    /// Module name (e.g., "numpy.core")
    pub name: String,
    /// Offset in bundle data section
    pub offset: u64,
    /// Marshalled bytecode size
    pub size: u64,
    /// BLAKE3 hash (unified: replaces CRC32 + source_hash)
    ///
    /// RFC-0006: BLAKE3 is a superset of CRC32 functionality:
    /// - Detects bit errors (like CRC32)
    /// - Detects tampering (unlike CRC32)
    /// - ~3-6 GB/s (fast enough for per-module verification)
    pub hash: [u8; 32],
}

impl ModuleEntry {
    /// Create new module entry with computed hash
    pub fn new(name: String, offset: u64, size: u64, data: &[u8]) -> Self {
        let hash = blake3::hash(data);
        Self {
            name,
            offset,
            size,
            hash: *hash.as_bytes(),
        }
    }

    /// Serialize to bytes
    pub fn to_bytes(&self) -> Vec<u8> {
        let mut bytes = Vec::new();

        // Name length (u32) + name bytes
        let name_bytes = self.name.as_bytes();
        bytes.extend_from_slice(&(name_bytes.len() as u32).to_le_bytes());
        bytes.extend_from_slice(name_bytes);

        // Fixed fields
        bytes.extend_from_slice(&self.offset.to_le_bytes());
        bytes.extend_from_slice(&self.size.to_le_bytes());
        bytes.extend_from_slice(&self.hash);

        bytes
    }

    /// Deserialize from bytes
    pub fn from_bytes(data: &[u8]) -> Result<Self> {
        let mut cursor = 0;

        // Read name length and name
        if data.len() < cursor + 4 {
            return Err(crate::loader::error::LoaderError::InsecureBundle(
                "Incomplete ModuleEntry header".into(),
            ));
        }
        let name_len = u32::from_le_bytes(data[cursor..cursor + 4].try_into().map_err(|_| {
            crate::loader::error::LoaderError::InsecureBundle("Invalid name length".into())
        })?) as usize;
        cursor += 4;

        let name = String::from_utf8_lossy(&data[cursor..cursor + name_len]).to_string();
        cursor += name_len;

        // Read fixed fields
        if data.len() < cursor + 16 {
            return Err(crate::loader::error::LoaderError::InsecureBundle(
                "Incomplete ModuleEntry fields".into(),
            ));
        }
        let offset = u64::from_le_bytes(data[cursor..cursor + 8].try_into().map_err(|_| {
            crate::loader::error::LoaderError::InsecureBundle("Invalid offset".into())
        })?);
        cursor += 8;

        let size = u64::from_le_bytes(data[cursor..cursor + 8].try_into().map_err(|_| {
            crate::loader::error::LoaderError::InsecureBundle("Invalid size".into())
        })?);
        cursor += 8;

        let mut hash = [0u8; 32];
        hash.copy_from_slice(&data[cursor..cursor + 32]);

        Ok(ModuleEntry {
            name,
            offset,
            size,
            hash,
        })
    }

    /// Verify module data integrity and nesting depth
    pub fn verify(&self, data: &[u8], code_header_offset: u8) -> Result<()> {
        crate::loader::verify::verify_module_hash(data, &self.hash, &self.name, code_header_offset)
    }
}

/// O(1) module lookup index
#[derive(Debug, Default)]
pub struct ModuleIndex {
    modules: HashMap<String, ModuleEntry>,
}

impl ModuleIndex {
    /// Create empty index
    pub fn new() -> Self {
        Self {
            modules: HashMap::new(),
        }
    }

    /// Insert module entry (computes hash from data)
    pub fn insert(&mut self, name: String, offset: u64, size: u64, data: &[u8]) {
        let entry = ModuleEntry::new(name.clone(), offset, size, data);
        self.modules.insert(name, entry);
    }

    /// Insert pre-computed entry
    pub fn insert_entry(&mut self, entry: ModuleEntry) {
        self.modules.insert(entry.name.clone(), entry);
    }

    /// O(1) lookup
    pub fn get(&self, name: &str) -> Option<&ModuleEntry> {
        self.modules.get(name)
    }

    /// Number of modules
    pub fn len(&self) -> usize {
        self.modules.len()
    }

    /// Check if empty
    pub fn is_empty(&self) -> bool {
        self.modules.is_empty()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_module_entry_hash() {
        let data = b"module bytecode";
        let entry = ModuleEntry::new("test.module".to_string(), 0, data.len() as u64, data);
        assert_eq!(entry.hash, *blake3::hash(data).as_bytes());
    }
}
