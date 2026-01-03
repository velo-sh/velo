use crate::graph::cycle::Tarjan;
use crate::graph::dependency::{DependencyScanner, DependencyType};
use std::collections::HashMap;
use std::path::{Path, PathBuf};

#[derive(Debug, Clone)]
pub struct LogicalModule {
    pub name: String,
    pub path: PathBuf,
    pub is_package: bool,
    pub dependencies: Vec<String>,
    pub soft_dependencies: Vec<String>,
    pub scc_id: Option<usize>,
    pub topological_rank: Option<usize>,
}

pub struct GraphBuilder {
    project_root: PathBuf,
    modules: HashMap<String, LogicalModule>,
}

impl GraphBuilder {
    pub fn new(project_root: PathBuf) -> Self {
        Self {
            project_root,
            modules: HashMap::new(),
        }
    }

    pub fn build(&mut self) -> Vec<LogicalModule> {
        self.scan_project();
        self.resolve_dependencies();
        self.compute_topological_order();

        self.modules.values().cloned().collect()
    }

    pub fn to_static_graph(&self) -> crate::graph::serializer::StaticImportGraph {
        use crate::graph::TargetArch;
        use crate::graph::serializer::{ModuleRecord, StaticImportGraph};

        let mut module_records = Vec::new();
        let mut string_pool = Vec::new();
        let mut name_to_idx = HashMap::new();

        // Sort by Topological Rank (RFC-0009 §2.3) then by name for determinism
        let mut names: Vec<_> = self.modules.keys().collect();
        names.sort_by_key(|&n| (self.modules[n].topological_rank, n));

        // 1. Build initial records and string pool
        for (idx, &name) in names.iter().enumerate() {
            let module = &self.modules[name];
            let name_bytes = module.name.as_bytes();
            let pool_start = string_pool.len() as u32;
            let pool_len = name_bytes.len() as u32;

            string_pool.extend_from_slice(name_bytes);

            let record = ModuleRecord::new(pool_start, pool_len, module.is_package);
            module_records.push(record);
            name_to_idx.insert(name.clone(), idx as u32);
        }

        // 2. Fill in dependencies
        for (idx, &name) in names.iter().enumerate() {
            let module = &self.modules[name];
            let mut dep_indices = Vec::new();

            for dep in &module.dependencies {
                if let Some(&dep_idx) = name_to_idx.get(dep) {
                    dep_indices.push(dep_idx);
                }
            }

            module_records[idx].dependency_indices = dep_indices;

            // Set flags (has_soft_deps)
            if !module.soft_dependencies.is_empty() {
                module_records[idx].dependency_flags |= 1 << 0;
            }
        }

        StaticImportGraph {
            version: 1,
            target_arch_id: TargetArch::current() as u8,
            endianness: if cfg!(target_endian = "big") { 1 } else { 0 },
            index_type: 1, // Standard HashMap for now (Fallback)
            module_records,
            string_pool,
        }
    }

    fn scan_project(&mut self) {
        // Walk the project root and find all .py files
        // (Similar to the logic in bundle_builder.py)
        // For now, assume we use a walker
        let walker = ignore::WalkBuilder::new(&self.project_root)
            .hidden(true)
            .git_ignore(true)
            .build();

        for entry in walker {
            let entry = match entry {
                Ok(e) => e,
                Err(_) => continue,
            };

            let path = entry.path();
            if path.extension().is_some_and(|ext| ext == "py") {
                self.add_file(path);
            }
        }
    }

    fn add_file(&mut self, path: &Path) {
        let rel_path = path.strip_prefix(&self.project_root).unwrap_or(path);
        let mut parts: Vec<String> = rel_path
            .components()
            .map(|c| c.as_os_str().to_string_lossy().to_string())
            .collect();

        let filename = parts.pop().unwrap();
        let is_package = filename == "__init__.py";
        let module_name = if is_package {
            parts.join(".")
        } else {
            let name = filename.strip_suffix(".py").unwrap();
            if parts.is_empty() {
                name.to_string()
            } else {
                format!("{}.{}", parts.join("."), name)
            }
        };

        if module_name.is_empty() {
            return;
        }

        let source = std::fs::read_to_string(path).unwrap_or_default();
        let mut scanner = DependencyScanner::new();
        let deps = scanner.scan(&source);

        let mut hard_deps = Vec::new();
        let mut soft_deps = Vec::new();
        for dep in deps {
            match dep.dep_type {
                DependencyType::Hard => hard_deps.push(dep.name),
                DependencyType::Soft => soft_deps.push(dep.name),
            }
        }

        self.modules.insert(
            module_name.clone(),
            LogicalModule {
                name: module_name,
                path: path.to_path_buf(),
                is_package,
                dependencies: hard_deps,
                soft_dependencies: soft_deps,
                scc_id: None,
                topological_rank: None,
            },
        );
    }

    fn resolve_dependencies(&mut self) {
        // Here we could resolve relative imports or filter out stdlib
        // For Phase 6.0, we mostly care about internal dependencies
    }

    /// RFC-0009 §2.3: Order modules topologically (dependencies before dependants)
    /// This ensures preloading is deterministic and follows the import chain.
    fn compute_topological_order(&mut self) {
        let names: Vec<String> = self.modules.keys().cloned().collect();
        let name_to_idx: HashMap<String, usize> = names
            .iter()
            .enumerate()
            .map(|(i, n)| (n.clone(), i))
            .collect();

        // 1. Build adjacency list (dependant -> dependency)
        let mut adjacency = vec![Vec::new(); names.len()];
        let mut in_degree = vec![0; names.len()];

        for (i, name) in names.iter().enumerate() {
            if let Some(module) = self.modules.get(name) {
                for dep in &module.dependencies {
                    if let Some(&j) = name_to_idx.get(dep) {
                        // Edge: j (dependency) -> i (dependant)
                        adjacency[j].push(i);
                        in_degree[i] += 1;
                    }
                }
            }
        }

        // 2. Kahn's Algorithm for topological sort
        let mut queue = std::collections::VecDeque::new();
        for (i, &degree) in in_degree.iter().enumerate() {
            if degree == 0 {
                queue.push_back(i);
            }
        }

        let mut order = 0;
        let mut sorted_indices = Vec::new();

        while let Some(i) = queue.pop_front() {
            let name = &names[i];
            if let Some(module) = self.modules.get_mut(name) {
                module.topological_rank = Some(order);
            }
            sorted_indices.push(i);
            order += 1;

            for &next in &adjacency[i] {
                in_degree[next] -= 1;
                if in_degree[next] == 0 {
                    queue.push_back(next);
                }
            }
        }

        // 3. Handle cycles (SCCs)
        // If some nodes weren't visited, they are part of one or more cycles.
        if sorted_indices.len() < names.len() {
            // Re-run Tarjan for cycle identification
            let mut cycle_adj = vec![Vec::new(); names.len()];
            for (i, name) in names.iter().enumerate() {
                if let Some(module) = self.modules.get(name) {
                    for dep in &module.dependencies {
                        if let Some(&j) = name_to_idx.get(dep) {
                            cycle_adj[i].push(j);
                        }
                    }
                }
            }

            let tarjan = Tarjan::new(names.len());
            let sccs = tarjan.execute(&cycle_adj);

            for (scc_id, scc) in sccs.iter().enumerate() {
                for &idx in scc {
                    let name = &names[idx];
                    if let Some(module) = self.modules.get_mut(name) {
                        module.scc_id = Some(scc_id);
                        // Cyclic nodes get a high rank to load after non-cyclic dependencies
                        module.topological_rank = Some(u32::MAX as usize - 1000 + scc_id);
                    }
                }
            }
        }
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    #[test]
    fn test_topological_order() {
        let mut builder = GraphBuilder::new(PathBuf::from("."));

        // A -> B -> C
        builder.modules.insert(
            "A".to_string(),
            LogicalModule {
                name: "A".to_string(),
                path: PathBuf::from("a.py"),
                is_package: false,
                dependencies: vec!["B".to_string()],
                soft_dependencies: vec![],
                scc_id: Some(2), // Dependants have higher SCC IDs
                topological_rank: Some(2),
            },
        );
        builder.modules.insert(
            "B".to_string(),
            LogicalModule {
                name: "B".to_string(),
                path: PathBuf::from("b.py"),
                is_package: false,
                dependencies: vec!["C".to_string()],
                soft_dependencies: vec![],
                scc_id: Some(1),
                topological_rank: Some(1),
            },
        );
        builder.modules.insert(
            "C".to_string(),
            LogicalModule {
                name: "C".to_string(),
                path: PathBuf::from("c.py"),
                is_package: false,
                dependencies: vec![],
                soft_dependencies: vec![],
                scc_id: Some(0), // Dependencies have lower SCC IDs
                topological_rank: Some(0),
            },
        );

        let graph = builder.to_static_graph();

        // Find names in order
        let names: Vec<String> = graph
            .module_records
            .iter()
            .map(|r| {
                let start = (r.packed_start_info & 0x7FFFFFFF) as usize;
                let end = start + r.pool_len as usize;
                String::from_utf8_lossy(&graph.string_pool[start..end]).to_string()
            })
            .collect();

        let idx_a = names.iter().position(|r| r == "A").unwrap();
        let idx_b = names.iter().position(|r| r == "B").unwrap();
        let idx_c = names.iter().position(|r| r == "C").unwrap();

        // Should be C, B, A (dependencies before dependants)
        assert!(
            idx_c < idx_b,
            "C should be before B ({} vs {})",
            idx_c,
            idx_b
        );
        assert!(
            idx_b < idx_a,
            "B should be before A ({} vs {})",
            idx_b,
            idx_a
        );
    }
}
