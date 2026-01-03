use rkyv::{Archive, Deserialize, Serialize, util::AlignedVec};

#[derive(Archive, Deserialize, Serialize, Debug, Clone)]
pub struct StaticImportGraph {
    pub version: u32,
    pub target_arch_id: u8, // S-01
    pub endianness: u8,     // 0=LE, 1=BE
    pub index_type: u8,     // 0=PHF, 1=HashMap

    pub module_records: Vec<ModuleRecord>,
    pub string_pool: Vec<u8>,
}

#[derive(Archive, Deserialize, Serialize, Debug, Clone)]
pub struct ModuleRecord {
    pub packed_start_info: u32,
    pub pool_len: u32,
    pub dependency_flags: u8,
    pub dependency_indices: Vec<u32>,
}

impl ModuleRecord {
    pub fn is_package(&self) -> bool {
        (self.packed_start_info >> 31) != 0
    }

    pub fn pool_start(&self) -> u32 {
        self.packed_start_info & 0x7FFFFFFF
    }

    pub fn new(pool_start: u32, pool_len: u32, is_package: bool) -> Self {
        let mut packed = pool_start & 0x7FFFFFFF;
        if is_package {
            packed |= 1 << 31;
        }
        Self {
            packed_start_info: packed,
            pool_len,
            dependency_flags: 0,
            dependency_indices: Vec::new(),
        }
    }
}

pub fn serialize_to_aligned_bytes(graph: &StaticImportGraph) -> AlignedVec {
    // AlignedVec already has alignment. rkyv::to_bytes returns AlignedVec usually or similar.
    // In 0.8 it returns AlignedVec.
    rkyv::to_bytes::<rkyv::rancor::Error>(graph).expect("Failed to serialize graph")
}

pub fn calculate_padding(current_offset: u64, alignment: u64) -> u64 {
    (alignment - (current_offset % alignment)) % alignment
}

pub fn verify_graph(bytes: &[u8]) -> Result<(), String> {
    use crate::graph::TargetArch;

    // Safety: bytes must be aligned for ArchivedStaticImportGraph
    let graph = match rkyv::access::<ArchivedStaticImportGraph, rkyv::rancor::Error>(bytes) {
        Ok(g) => g,
        Err(e) => return Err(format!("Rkyv validation failed: {:?}", e)),
    };

    if graph.target_arch_id != TargetArch::current() as u8 {
        return Err(format!(
            "Architecture mismatch: expected {}, got {}",
            TargetArch::current() as u8,
            graph.target_arch_id
        ));
    }

    let current_endian = if cfg!(target_endian = "big") { 1 } else { 0 };
    if graph.endianness != current_endian {
        return Err("Endianness mismatch".to_string());
    }

    if graph.version != 1 {
        return Err(format!("Unsupported graph version: {}", graph.version));
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::graph::TargetArch;

    #[test]
    fn test_benchmark_deserialization() {
        let mut graph = StaticImportGraph {
            version: 1,
            target_arch_id: TargetArch::current() as u8,
            endianness: if cfg!(target_endian = "big") { 1 } else { 0 },
            index_type: 1,
            module_records: Vec::new(),
            string_pool: Vec::new(),
        };

        // Create a reasonably sized graph (100 modules)
        for i in 0..100 {
            let mut record = ModuleRecord::new((i * 10) as u32, 10, false);
            record.dependency_indices = vec![0, 1, 2, 3, 4];
            graph.module_records.push(record);
            graph
                .string_pool
                .extend_from_slice(format!("module_{:03}", i).as_bytes());
        }

        let bytes = serialize_to_aligned_bytes(&graph);

        // Measure access (deserialization latency)
        let start = std::time::Instant::now();
        let _ = verify_graph(&bytes).unwrap();
        let elapsed = start.elapsed();

        println!("⚡ Static Graph Deserialization Latency: {:?}", elapsed);
        assert!(elapsed.as_micros() < 500, "Latency too high: {:?}", elapsed);
    }

    #[test]
    fn test_arch_mismatch() {
        let mut graph = StaticImportGraph {
            version: 1,
            target_arch_id: 255,
            endianness: if cfg!(target_endian = "big") { 1 } else { 0 },
            index_type: 1,
            module_records: Vec::new(),
            string_pool: Vec::new(),
        };
        graph.module_records.push(ModuleRecord::new(0, 4, false));
        graph.string_pool.extend_from_slice(b"test");

        let bytes = serialize_to_aligned_bytes(&graph);
        let result = verify_graph(&bytes);
        assert!(result.is_err(), "Result should be error, got {:?}", result);
        let err = result.err().unwrap();
        assert!(err.contains("Architecture mismatch"), "Error was: {}", err);
    }
}
