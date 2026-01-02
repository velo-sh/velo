//! Module entry and index structures
//!
//! RFC-0006 Section 2.5: ModuleEntry structure

use crate::loader::error::Result;
use std::collections::HashMap;

/// Module entry in bundle index
#[derive(Debug, Clone)]
pub struct ModuleEntry {
    /// Fully qualified module name (e.g., "numpy.core")
    pub name: String,
    /// Offset in data section
    pub offset: u64,
    /// Marshalled bytecode size
    pub size: u64,
    /// CRC32 for fast integrity check (~20 GB/s)
    pub crc32: u32,
    /// SHA-256 of source file for cache invalidation
    pub source_hash: [u8; 32],
}

impl ModuleEntry {
    /// Serialize entry to bytes
    pub fn to_bytes(&self) -> Vec<u8> {
        let mut bytes = Vec::new();

        // Name length (u32) + name bytes
        let name_bytes = self.name.as_bytes();
        bytes.extend_from_slice(&(name_bytes.len() as u32).to_le_bytes());
        bytes.extend_from_slice(name_bytes);

        // Fixed fields
        bytes.extend_from_slice(&self.offset.to_le_bytes());
        bytes.extend_from_slice(&self.size.to_le_bytes());
        bytes.extend_from_slice(&self.crc32.to_le_bytes());
        bytes.extend_from_slice(&self.source_hash);

        bytes
    }

    /// Deserialize entry from bytes
    pub fn from_bytes(data: &[u8]) -> Result<Self> {
        let mut cursor = 0;

        // Read name length and name
        let name_len = u32::from_le_bytes(data[cursor..cursor + 4].try_into().unwrap()) as usize;
        cursor += 4;

        let name = String::from_utf8_lossy(&data[cursor..cursor + name_len]).to_string();
        cursor += name_len;

        // Read fixed fields
        let offset = u64::from_le_bytes(data[cursor..cursor + 8].try_into().unwrap());
        cursor += 8;

        let size = u64::from_le_bytes(data[cursor..cursor + 8].try_into().unwrap());
        cursor += 8;

        let crc32 = u32::from_le_bytes(data[cursor..cursor + 4].try_into().unwrap());
        cursor += 4;

        let mut source_hash = [0u8; 32];
        source_hash.copy_from_slice(&data[cursor..cursor + 32]);

        Ok(ModuleEntry {
            name,
            offset,
            size,
            crc32,
            source_hash,
        })
    }
}

/// Module index for O(1) lookup
#[derive(Debug, Default)]
pub struct ModuleIndex {
    modules: HashMap<String, ModuleEntry>,
}

impl ModuleIndex {
    /// Create new empty index
    pub fn new() -> Self {
        Self {
            modules: HashMap::new(),
        }
    }

    /// Insert module entry
    pub fn insert(&mut self, name: String, offset: u64, size: u64, crc32: u32) {
        let entry = ModuleEntry {
            name: name.clone(),
            offset,
            size,
            crc32,
            source_hash: [0u8; 32], // Will be filled during build
        };
        self.modules.insert(name, entry);
    }

    /// Get module entry by name (O(1) HashMap lookup)
    pub fn get(&self, name: &str) -> Option<&ModuleEntry> {
        self.modules.get(name)
    }

    /// Number of modules in index
    pub fn len(&self) -> usize {
        self.modules.len()
    }

    /// Check if index is empty
    pub fn is_empty(&self) -> bool {
        self.modules.is_empty()
    }
}
