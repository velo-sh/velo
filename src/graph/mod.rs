use rkyv::{Archive, Deserialize, Serialize};
use std::collections::{HashMap, HashSet};

#[repr(u8)]
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TargetArch {
    Unknown = 0,
    X86_64 = 1,
    Aarch64 = 2,
}

impl TargetArch {
    pub fn current() -> Self {
        #[cfg(target_arch = "x86_64")]
        {
            TargetArch::X86_64
        }
        #[cfg(target_arch = "aarch64")]
        {
            TargetArch::Aarch64
        }
        #[cfg(not(any(target_arch = "x86_64", target_arch = "aarch64")))]
        {
            TargetArch::Unknown
        }
    }

    pub fn id(&self) -> u8 {
        *self as u8
    }
}

/// RFC-0009 v2.0: Optimized static import graph
#[derive(Archive, Deserialize, Serialize, Debug, Clone)]
pub struct StaticImportGraph {
    pub version: u32,
    pub target_arch_id: u8,
    pub endianness: u8, // 0: Little, 1: Big

    /// Flattened dependency indices (pointing to module_records)
    pub dependency_pool: Vec<u32>,

    pub index_type: u8, // 0 for PHF (future), 1 for HashMap

    pub module_names: Vec<String>,
    pub module_records: Vec<ModuleRecord>,

    pub load_order: Vec<u32>, // Indices into module_records
    pub source_hash: [u8; 32],

    // === Audit & Namespace Fields ===
    pub mutable_path_packages: HashSet<String>,
    pub search_locations: HashMap<String, Vec<String>>,
    pub namespace_packages: HashSet<String>,

    /// Explicit __path__ storage for packages (P-02)
    pub package_paths: HashMap<u32, String>,
}

/// RFC-0009 v2.0 §3.2: Bit-packed module record
#[derive(Archive, Deserialize, Serialize, Debug, Clone, Copy)]
pub struct ModuleRecord {
    /// [0..31] pool_start index into dependency_pool, [31] is_package flag
    pub packed_start_info: u32,
    pub pool_len: u32,
    pub dependency_flags: u8,
}

impl ModuleRecord {
    pub fn pool_start(&self) -> u32 {
        self.packed_start_info & 0x7FFF_FFFF
    }

    pub fn is_package(&self) -> bool {
        (self.packed_start_info >> 31) != 0
    }

    pub fn new(pool_start: u32, pool_len: u32, is_package: bool, dependency_flags: u8) -> Self {
        let packed = (pool_start & 0x7FFF_FFFF) | (if is_package { 1 << 31 } else { 0 });
        Self {
            packed_start_info: packed,
            pool_len,
            dependency_flags,
        }
    }
}

pub mod builder;
pub mod cycle;
pub mod dependency;
pub mod metrics;
pub mod serializer;

pub use metrics::report_metrics;
