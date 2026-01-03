use rkyv::util::AlignedVec;

pub use crate::graph::{ModuleRecord, StaticImportGraph, TargetArch};

// Methods moved to mod.rs or replaced by StaticImportGraph implementation

pub fn serialize_to_aligned_bytes(graph: &StaticImportGraph) -> AlignedVec {
    // AlignedVec already has alignment. rkyv::to_bytes returns AlignedVec usually or similar.
    // In 0.8 it returns AlignedVec.
    rkyv::to_bytes::<rkyv::rancor::Error>(graph).expect("Failed to serialize graph")
}

pub fn calculate_padding(current_offset: u64, alignment: u64) -> u64 {
    (alignment - (current_offset % alignment)) % alignment
}

pub fn verify_graph(bytes: &[u8]) -> std::result::Result<(), String> {
    // Safety: bytes must be aligned for ArchivedStaticImportGraph
    let graph =
        match rkyv::access::<crate::graph::ArchivedStaticImportGraph, rkyv::rancor::Error>(bytes) {
            Ok(g) => g,
            Err(e) => return Err(format!("Rkyv validation failed: {:?}", e)),
        };

    if graph.target_arch_id != TargetArch::current().id() {
        return Err(format!(
            "Architecture mismatch: expected {}, got {}",
            TargetArch::current().id(),
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
    use std::collections::{HashMap, HashSet};

    #[test]
    fn test_benchmark_deserialization() {
        let mut graph = StaticImportGraph {
            version: 1,
            target_arch_id: TargetArch::current().id(),
            endianness: if cfg!(target_endian = "big") { 1 } else { 0 },
            dependency_pool: Vec::new(),
            index_type: 1,
            module_names: Vec::new(),
            module_records: Vec::new(),
            load_order: Vec::new(),
            source_hash: [0u8; 32],
            mutable_path_packages: HashSet::new(),
            search_locations: HashMap::new(),
            namespace_packages: HashSet::new(),
            package_paths: HashMap::new(),
        };

        // Create a reasonably sized graph (100 modules)
        for i in 0..100 {
            let pool_start = graph.dependency_pool.len() as u32;
            graph.dependency_pool.extend_from_slice(&[0, 1, 2, 3, 4]);

            let record = ModuleRecord::new(pool_start, 5, false, 0);
            graph.module_records.push(record);
            graph.module_names.push(format!("module_{:03}", i));
            graph.load_order.push(i as u32);
        }

        let bytes = serialize_to_aligned_bytes(&graph);

        // Measure access (deserialization latency)
        let start = std::time::Instant::now();
        verify_graph(&bytes).unwrap();
        let elapsed = start.elapsed();

        println!("⚡ Static Graph Deserialization Latency: {:?}", elapsed);
        assert!(elapsed.as_micros() < 500, "Latency too high: {:?}", elapsed);
    }

    #[test]
    fn test_arch_mismatch() {
        let graph = StaticImportGraph {
            version: 1,
            target_arch_id: 255,
            endianness: if cfg!(target_endian = "big") { 1 } else { 0 },
            dependency_pool: Vec::new(),
            index_type: 1,
            module_names: vec!["test".to_string()],
            module_records: vec![ModuleRecord::new(0, 0, false, 0)],
            load_order: vec![0],
            source_hash: [0u8; 32],
            mutable_path_packages: HashSet::new(),
            search_locations: HashMap::new(),
            namespace_packages: HashSet::new(),
            package_paths: HashMap::new(),
        };

        let bytes = serialize_to_aligned_bytes(&graph);
        let result = verify_graph(&bytes);
        assert!(result.is_err(), "Result should be error, got {:?}", result);
        let err = result.err().unwrap();
        assert!(err.contains("Architecture mismatch"), "Error was: {}", err);
    }
}
