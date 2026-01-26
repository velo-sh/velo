use crate::cycle::Tarjan;
use crate::dependency::{DependencyScanner, DependencyType};
use serde::Serialize;
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

#[derive(Serialize, Default, Debug)]
pub struct BuildMetrics {
    pub module_count: usize,
    pub hard_dependencies: usize,
    pub soft_dependencies: usize,
    pub cyclic_dependencies: usize,
    pub build_time_ms: u128,
}

pub struct GraphBuilder {
    pub project_root: PathBuf,
    pub modules: HashMap<String, LogicalModule>,
    pub metrics: BuildMetrics,
}

impl GraphBuilder {
    pub fn new(project_root: PathBuf) -> Self {
        Self {
            project_root,
            modules: HashMap::new(),
            metrics: BuildMetrics::default(),
        }
    }

    pub fn build(&mut self) -> Vec<LogicalModule> {
        self.scan_project();
        self.resolve_dependencies();
        self.compute_topological_order();

        self.modules.values().cloned().collect()
    }

    pub fn to_static_graph(&self) -> crate::StaticImportGraph {
        use crate::{ModuleRecord, StaticImportGraph, TargetArch};
        use std::collections::{HashMap, HashSet};

        let mut module_records = Vec::new();
        let mut module_names = Vec::new();
        let mut dependency_pool = Vec::new();
        let mut name_to_idx = HashMap::new();

        // Sort by Topological Rank (RFC-0009 §2.3) then by name for determinism
        let mut sorted_names: Vec<_> = self.modules.keys().collect();
        sorted_names.sort_by_key(|&n| (self.modules[n].topological_rank, n));

        // 1. Build name to index mapping
        for (idx, &name) in sorted_names.iter().enumerate() {
            name_to_idx.insert(name.clone(), idx as u32);
            module_names.push(name.clone());
        }

        // 2. Build records and dependency pool
        for name in &module_names {
            let module = &self.modules[name];
            let pool_start = dependency_pool.len() as u32;

            let mut count = 0;
            for dep in &module.dependencies {
                if let Some(&dep_idx) = name_to_idx.get(dep) {
                    dependency_pool.push(dep_idx);
                    count += 1;
                }
            }

            let record = ModuleRecord::new(
                pool_start,
                count,
                module.is_package,
                if module.soft_dependencies.is_empty() {
                    0
                } else {
                    1
                },
            );
            module_records.push(record);
        }

        // 3. Load order indices
        // 3. Load order indices
        // FUNC-603: Default to Empty (Lazy) loading. Only explicit preloads should go here.
        // Previously: (0..module_records.len() as u32).collect(); which forced Eager loading.
        let load_order = Vec::new();

        StaticImportGraph {
            version: 1,
            target_arch_id: TargetArch::current().id(),
            endianness: if cfg!(target_endian = "big") { 1 } else { 0 },
            dependency_pool,
            index_type: 1, // HashMap
            module_names,
            module_records,
            load_order,
            source_hash: [0u8; 32], // TODO: Compute from inputs
            mutable_path_packages: HashSet::new(),
            search_locations: {
                let mut locs = HashMap::new();
                for (name, module) in &self.modules {
                    if module.is_package
                        && let Some(parent) = module.path.parent()
                    {
                        let path_str = parent.to_string_lossy().to_string();
                        locs.insert(name.clone(), vec![path_str]);
                    }
                }
                locs
            },
            namespace_packages: HashSet::new(),
            package_paths: HashMap::new(),
        }
    }

    pub fn scan_project(&mut self) {
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
                DependencyType::Hard => {
                    hard_deps.push(dep.name);
                    self.metrics.hard_dependencies += 1;
                }
                DependencyType::Soft => {
                    soft_deps.push(dep.name);
                    self.metrics.soft_dependencies += 1;
                }
            }
        }

        self.metrics.module_count += 1;

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

    /// ARCH-6.0-13: Namespace Mapper
    ///
    /// Resolves dependencies by:
    /// 1. Resolving relative imports to absolute module names
    /// 2. Filtering out stdlib/external dependencies (keep only project-internal)
    fn resolve_dependencies(&mut self) {
        // Build path -> module_name mapping for future resolution
        let _path_to_name: HashMap<PathBuf, String> = self
            .modules
            .values()
            .map(|m| (m.path.clone(), m.name.clone()))
            .collect();

        // Collect all known module names for filtering
        let known_modules: std::collections::HashSet<String> =
            self.modules.keys().cloned().collect();

        // Process each module
        let module_names: Vec<String> = self.modules.keys().cloned().collect();
        for name in module_names {
            let module = self.modules.get(&name).unwrap();
            let module_package = Self::get_package_name(&module.name);

            // Resolve and filter hard dependencies
            let resolved_hard: Vec<String> = module
                .dependencies
                .iter()
                .filter_map(|dep| {
                    let resolved = self.resolve_import(dep, &module_package);
                    // Keep only dependencies that are in our project
                    if known_modules.contains(&resolved) {
                        Some(resolved)
                    } else {
                        None // Filter out stdlib/external
                    }
                })
                .collect();

            // Resolve and filter soft dependencies
            let resolved_soft: Vec<String> = module
                .soft_dependencies
                .iter()
                .filter_map(|dep| {
                    let resolved = self.resolve_import(dep, &module_package);
                    if known_modules.contains(&resolved) {
                        Some(resolved)
                    } else {
                        None
                    }
                })
                .collect();

            // Update the module with resolved dependencies
            if let Some(m) = self.modules.get_mut(&name) {
                m.dependencies = resolved_hard;
                m.soft_dependencies = resolved_soft;
            }
        }
    }

    /// Resolve a potentially relative import to an absolute module name
    ///
    /// Python relative import semantics:
    /// - `.foo` (1 dot) = current package + foo
    /// - `..foo` (2 dots) = parent package + foo
    fn resolve_import(&self, import_name: &str, current_package: &Option<String>) -> String {
        if !import_name.starts_with('.') {
            // Absolute import - return as-is
            return import_name.to_string();
        }

        // Relative import - count leading dots
        let dots = import_name.chars().take_while(|&c| c == '.').count();
        let relative_part = &import_name[dots..];

        let Some(package) = current_package else {
            // Top-level module trying relative import - invalid, return as-is
            return import_name.to_string();
        };

        // Navigate up the package hierarchy
        // dots=1 means current package (0 levels up)
        // dots=2 means parent package (1 level up)
        let levels_up = dots - 1;
        let parts: Vec<&str> = package.split('.').collect();

        if levels_up > parts.len() {
            // Trying to go above root - invalid
            return import_name.to_string();
        }

        // Build the resolved name
        let base_parts = &parts[..parts.len() - levels_up];
        if relative_part.is_empty() {
            base_parts.join(".")
        } else if base_parts.is_empty() {
            relative_part.to_string()
        } else {
            format!("{}.{}", base_parts.join("."), relative_part)
        }
    }

    /// Get the package name for a module (everything before the last segment)
    fn get_package_name(module_name: &str) -> Option<String> {
        let parts: Vec<&str> = module_name.split('.').collect();
        if parts.len() > 1 {
            Some(parts[..parts.len() - 1].join("."))
        } else {
            None
        }
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

        let names = &graph.module_names;
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

        // Verify dependency linkage
        let record_a = &graph.module_records[idx_a];
        assert_eq!(record_a.pool_len, 1);
        let dep_idx = graph.dependency_pool[record_a.pool_start() as usize];
        assert_eq!(dep_idx, idx_b as u32);
    }

    #[test]
    fn test_resolve_relative_imports() {
        let builder = GraphBuilder::new(PathBuf::from("."));

        // Test absolute import (no change)
        let result = builder.resolve_import("os", &None);
        assert_eq!(result, "os");

        // Test single-dot relative import: .foo from pkg.sub -> pkg.sub.foo (current package)
        let result = builder.resolve_import(".foo", &Some("pkg.sub".to_string()));
        assert_eq!(result, "pkg.sub.foo");

        // Test double-dot relative import: ..bar from pkg.sub -> pkg.bar (parent package)
        let result = builder.resolve_import("..bar", &Some("pkg.sub".to_string()));
        assert_eq!(result, "pkg.bar");

        // Test single-dot import of package itself: . from pkg.sub -> pkg.sub
        let result = builder.resolve_import(".", &Some("pkg.sub".to_string()));
        assert_eq!(result, "pkg.sub");

        // Test relative import from top-level (should return as-is)
        let result = builder.resolve_import(".foo", &None);
        assert_eq!(result, ".foo");

        // Test triple-dot: ...baz from pkg.sub.deep -> pkg.baz
        let result = builder.resolve_import("...baz", &Some("pkg.sub.deep".to_string()));
        assert_eq!(result, "pkg.baz");
    }

    #[test]
    fn test_get_package_name() {
        assert_eq!(
            GraphBuilder::get_package_name("pkg.sub.module"),
            Some("pkg.sub".to_string())
        );
        assert_eq!(GraphBuilder::get_package_name("module"), None);
        assert_eq!(
            GraphBuilder::get_package_name("pkg.module"),
            Some("pkg".to_string())
        );
    }
}
