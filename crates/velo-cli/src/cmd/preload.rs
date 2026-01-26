//! Handle 'velo preload' commands
//!
//! Subcommands:
//! - analyze: Generate preload.lock from configuration
//! - verify: Validate preload.lock against current environment

use anyhow::Result;
use clap::{Parser, Subcommand};
use std::path::{Path, PathBuf};
use velo_core::common::paths::VeloPaths;
use velo_core::config::VeloConfig;
use velo_core::custody::native_fingerprint::{
    LibPlatform, LoadStage, NativeLibFingerprint, PreloadLock,
};
use velo_core::python_info::PythonInfo;

#[derive(Parser, Debug)]
#[command(name = "preload", about = "Manage native library preloading")]
pub struct PreloadCmd {
    #[command(subcommand)]
    pub operation: PreloadOperation,
}

#[derive(Subcommand, Debug)]
pub enum PreloadOperation {
    /// Generate preload.lock by analyzing configured libraries
    Analyze,
    /// Validate preload.lock against installed libraries
    Verify,
    /// Show preload statistics from preload.lock
    Stats,
    /// Load libraries from a JSON lock string (Internal use)
    Load {
        #[arg(long)]
        lock: String,
        #[arg(long, default_value = "pre-init")]
        stage: String,
    },
    /// Vetting a library via fork-vet-load (Security Vetting)
    Check {
        #[arg(long)]
        path: PathBuf,
        #[arg(long)]
        global: bool,
        /// Expected BLAKE3 hash (if provided, verification is enforced)
        #[arg(long)]
        expected_hash: Option<String>,
        /// Expected mtime (for fast-path verification)
        #[arg(long)]
        expected_mtime: Option<u64>,
    },
}

pub fn cmd_preload(args: &[String]) -> Result<()> {
    let cmd = PreloadCmd::try_parse_from(&args[1..])?;

    match cmd.operation {
        PreloadOperation::Analyze => analyze_impl(),
        PreloadOperation::Verify => verify_impl(),
        PreloadOperation::Stats => stats_impl(),
        PreloadOperation::Load { lock, stage } => load_impl(&lock, &stage),
        PreloadOperation::Check {
            path,
            global,
            expected_hash,
            expected_mtime,
        } => check_impl(&path, global, expected_hash, expected_mtime),
    }
}

fn analyze_impl() -> Result<()> {
    let project_dir = std::env::current_dir()?;
    let pyproject = VeloPaths::pyproject(&project_dir);
    let config = VeloConfig::load_with_overrides(&pyproject);

    // Get Python info for platform metadata
    let python_path = velo_core::python::detect_python(&project_dir)?;
    let py_info = PythonInfo::detect(&python_path)?;

    let mut fingerprints = Vec::new();

    // 1. Process libraries from config with expansion
    // RFC-0035 §3.4: Use config.native_libraries
    for raw_path_str in &config.native_libraries {
        // Step A: Expand placeholders
        let expanded_pattern = expand_library_placeholders(raw_path_str, &py_info);

        // Step B: Glob expansion
        let matched_paths = if expanded_pattern.contains('*') || expanded_pattern.contains('?') {
            match glob::glob(&expanded_pattern) {
                Ok(paths) => paths.filter_map(Result::ok).collect(),
                Err(e) => {
                    log::error!("Invalid glob pattern '{}': {}", expanded_pattern, e);
                    continue;
                }
            }
        } else {
            vec![PathBuf::from(&expanded_pattern)]
        };

        for lib_path in matched_paths {
            let lib_path = if lib_path.is_absolute() {
                lib_path
            } else {
                project_dir.join(lib_path)
            };

            if !lib_path.exists() {
                log::warn!("Configured native library not found: {:?}", lib_path);
                continue;
            }

            // RFC-0035 Phase 6: Recursive Dependency Discovery
            let dependencies = resolve_dependencies_recursive(&lib_path)?;
            let mut all_to_process = vec![lib_path];
            all_to_process.extend(dependencies);

            for path in all_to_process {
                let canonical_lib = path.canonicalize()?;

                // Avoid duplicates
                if fingerprints.iter().any(|f: &NativeLibFingerprint| {
                    if let Ok(c) = project_dir.join(&f.relative_path).canonicalize() {
                        return c == canonical_lib;
                    }
                    false
                }) {
                    continue;
                }

                let (hash, header_hash) = NativeLibFingerprint::calculate_hashes(&canonical_lib)?;
                let (soname, _needed) = NativeLibFingerprint::parse_native_lib(&canonical_lib)?;
                let metadata = canonical_lib.metadata()?;
                let mtime = metadata
                    .modified()?
                    .duration_since(std::time::UNIX_EPOCH)?
                    .as_secs();

                // RFC-0035 Phase 6.5: Attribution & Path Integrity
                let package = detect_package_name(&canonical_lib);
                let venv_path = std::env::var("VIRTUAL_ENV").ok().map(PathBuf::from);
                if !VeloPaths::is_path_trusted(&canonical_lib, &project_dir, venv_path.as_deref()) {
                    log::warn!(
                        "Supply Chain Security Warning: Native library {:?} is outside project/venv prefixes!",
                        canonical_lib
                    );
                }

                // Calculate relative path to project root
                let relative_path = canonical_lib
                    .strip_prefix(&project_dir)
                    .map(|p| p.to_path_buf())
                    .unwrap_or_else(|_| canonical_lib.clone());

                let fp = NativeLibFingerprint {
                    relative_path,
                    package,
                    soname,
                    hash,
                    header_hash,
                    mtime,
                    platform: LibPlatform {
                        os: std::env::consts::OS.to_string(),
                        arch: std::env::consts::ARCH.to_string(),
                        python_version: format!(
                            "{}.{}",
                            py_info.version.major, py_info.version.minor
                        ),
                        libc_type: detect_libc_type(),
                        libc_version: detect_libc_version(),
                        soabi: py_info.abi_tag.clone(),
                    },
                    load_stage: LoadStage::PreInit,
                    provenance: None,
                };
                fingerprints.push(fp);
            }
        }
    }

    let lock = PreloadLock::new(fingerprints);
    let lock_json = lock.to_json()?;
    let lock_path = project_dir.join("preload.lock");
    std::fs::write(&lock_path, lock_json)?;

    println!(
        "✅ Generated preload.lock with {} library fingerprints",
        lock.fingerprints.len()
    );
    Ok(())
}

fn verify_impl() -> Result<()> {
    let project_dir = std::env::current_dir()?;
    let lock_path = project_dir.join("preload.lock");
    if !lock_path.exists() {
        anyhow::bail!("preload.lock not found. Run 'velo preload analyze' first.");
    }

    let lock_json = std::fs::read_to_string(&lock_path)?;
    let lock = PreloadLock::from_json(&lock_json)?;

    let mut all_ok = true;
    for fp in &lock.fingerprints {
        let full_path = project_dir.join(&fp.relative_path);

        // In verify command, we allow (or encourage) deep verify
        match fp.verify(&full_path, true) {
            Ok(true) => println!("✅ {:?}: OK", fp.relative_path),
            Ok(false) => {
                println!("❌ {:?}: Fingerprint mismatch!", fp.relative_path);
                all_ok = false;
            }
            Err(e) => {
                println!("❌ {:?}: Error: {}", fp.relative_path, e);
                all_ok = false;
            }
        }
    }

    if all_ok {
        println!("✨ Verification successful.");
        Ok(())
    } else {
        anyhow::bail!("Verification failed.");
    }
}

fn load_impl(lock_json: &str, stage_str: &str) -> Result<()> {
    use velo_core::custody::preload_orchestrator::PreloadOrchestrator;

    let lock = PreloadLock::from_json(lock_json)?;
    let project_dir = std::env::current_dir()?;
    let orch = PreloadOrchestrator::new(lock, &project_dir);

    let stage = match stage_str.to_lowercase().as_str() {
        "pre-init" => LoadStage::PreInit,
        "post-init" => LoadStage::PostInit,
        _ => anyhow::bail!("Invalid loading stage: {}", stage_str),
    };

    orch.load_stage(stage, &project_dir)?;
    Ok(())
}

fn check_impl(
    path: &Path,
    global: bool,
    expected_hash: Option<String>,
    expected_mtime: Option<u64>,
) -> Result<()> {
    use velo_core::custody::preload_loader::PreloadLoader;

    // RFC-0035 INV-PRELOAD-002: Enforce strict path containment for `check` command
    // Only allow paths within project root or venv - system paths are NOT trusted
    let project_dir = std::env::current_dir()?;
    let venv_path = std::env::var("VIRTUAL_ENV").ok().map(PathBuf::from);

    // Resolve relative paths to absolute for proper boundary checking
    let resolved_path = if path.is_absolute() {
        path.to_path_buf()
    } else {
        project_dir.join(path)
    };

    let is_in_project = resolved_path.starts_with(&project_dir);
    let is_in_venv = venv_path
        .as_ref()
        .is_some_and(|venv| resolved_path.starts_with(venv));

    if !is_in_project && !is_in_venv {
        anyhow::bail!(
            "Path {} is outside trusted boundaries (project root or venv). \
             Only libraries in site-packages or project directories may be vetted.",
            path.display()
        );
    }

    // RFC-0035 Phase 6.5: Integrity Verification BEFORE Vetting
    if let Some(hash) = expected_hash {
        let mtime = expected_mtime.unwrap_or(0);
        // Create a temporary fingerprint for verification
        let _fp = NativeLibFingerprint {
            relative_path: path.to_path_buf(),
            package: "unknown".to_string(),
            soname: "unknown".to_string(),
            hash: hash.clone(),
            header_hash: String::new(), // Deep verify will check full hash
            mtime,
            platform: LibPlatform {
                os: String::new(),
                arch: String::new(),
                python_version: String::new(),
                libc_type: String::new(),
                libc_version: String::new(),
                soabi: String::new(),
            },
            load_stage: LoadStage::PreInit,
            provenance: None,
        };

        // For check command, we ALWAYS deep verify if a hash is provided
        let (actual_hash, _) = NativeLibFingerprint::calculate_hashes(&resolved_path)?;
        if actual_hash != hash {
            anyhow::bail!(
                "Integrity Violation: Native library {:?} does not match fingerprint.\n  Expected: {}\n  Actual:   {}\n  Hint: Run 'velo preload analyze' to refresh lock file.",
                path,
                hash,
                actual_hash
            );
        }
    }
    PreloadLoader::vett_only(&resolved_path, global)
}

/// Display preload statistics from preload.lock
fn stats_impl() -> Result<()> {
    use velo_core::custody::native_fingerprint::PreloadLock;

    let lock_path = PathBuf::from("preload.lock");
    if !lock_path.exists() {
        println!("⚠️  No preload.lock found. Run 'velo preload analyze' first.");
        return Ok(());
    }

    let content = std::fs::read_to_string(&lock_path)?;
    let lock: PreloadLock = serde_json::from_str(&content)?;

    // Calculate statistics
    let total_libs = lock.fingerprints.len();
    let mut total_size_bytes: u64 = 0;
    let mut packages: std::collections::HashMap<String, usize> = std::collections::HashMap::new();
    let mut pre_init_count = 0;
    let mut post_init_count = 0;

    for fp in &lock.fingerprints {
        // Count by package
        *packages.entry(fp.package.clone()).or_insert(0) += 1;

        // Count by stage
        match fp.load_stage {
            LoadStage::PreInit => pre_init_count += 1,
            LoadStage::PostInit => post_init_count += 1,
        }

        // Calculate file size (if file exists)
        let cwd = std::env::current_dir()?;
        let full_path = cwd.join(&fp.relative_path);
        if let Ok(meta) = std::fs::metadata(&full_path) {
            total_size_bytes += meta.len();
        }
    }

    // Format size
    let size_str = if total_size_bytes >= 1024 * 1024 * 1024 {
        format!(
            "{:.2} GB",
            total_size_bytes as f64 / (1024.0 * 1024.0 * 1024.0)
        )
    } else if total_size_bytes >= 1024 * 1024 {
        format!("{:.2} MB", total_size_bytes as f64 / (1024.0 * 1024.0))
    } else if total_size_bytes >= 1024 {
        format!("{:.2} KB", total_size_bytes as f64 / 1024.0)
    } else {
        format!("{} bytes", total_size_bytes)
    };

    // Print statistics
    println!("┌────────────────────────────────────────┐");
    println!("│        📊 Preload Statistics           │");
    println!("├────────────────────────────────────────┤");
    println!("│  Lock File: {:} │", lock_path.display());
    println!("│  Version: {:}                          │", lock.version);
    println!("│  Generator: {:}                   │", lock.generator);
    println!("├────────────────────────────────────────┤");
    println!("│  Total Libraries: {:>20} │", total_libs);
    println!("│  Total Size: {:>24} │", size_str);
    println!("│  PreInit Stage: {:>21} │", pre_init_count);
    println!("│  PostInit Stage: {:>20} │", post_init_count);
    println!("├────────────────────────────────────────┤");
    println!("│  Libraries by Package:                 │");
    for (pkg, count) in &packages {
        println!("│    {}: {} │", pkg, count);
    }
    println!("└────────────────────────────────────────┘");

    Ok(())
}

fn detect_libc_type() -> String {
    #[cfg(target_os = "linux")]
    {
        "gnu".to_string() // Assume GNU for now, could detect musl via ldd
    }
    #[cfg(target_os = "macos")]
    {
        "bsd".to_string()
    }
    #[cfg(not(any(target_os = "linux", target_os = "macos")))]
    {
        "unknown".to_string()
    }
}

fn detect_libc_version() -> String {
    #[cfg(target_os = "linux")]
    {
        use std::process::Command;
        if let Ok(output) = Command::new("getconf").arg("GNU_LIBC_VERSION").output() {
            let s = String::from_utf8_lossy(&output.stdout).trim().to_string();
            if s.starts_with("glibc ") {
                return s.replace("glibc ", "");
            }
            return s;
        }
    }
    "unknown".to_string()
}

fn expand_library_placeholders(s: &str, py: &PythonInfo) -> String {
    let mut res = s.to_string();

    // ${PYTHON_VERSION} -> 3.11
    res = res.replace(
        "${PYTHON_VERSION}",
        &format!("{}.{}", py.version.major, py.version.minor),
    );

    // ${SOABI} -> cpython-311-darwin
    res = res.replace("${SOABI}", &py.abi_tag);

    // ${OS} -> macos, linux
    res = res.replace("${OS}", std::env::consts::OS);

    // ${ARCH} -> aarch64, x86_64
    res = res.replace("${ARCH}", std::env::consts::ARCH);

    // ${SO_EXT} -> .dylib, .so
    let ext = match std::env::consts::OS {
        "macos" => "dylib",
        _ => "so",
    };
    res = res.replace("${SO_EXT}", ext);

    res
}

fn resolve_dependencies_recursive(path: &Path) -> Result<Vec<PathBuf>> {
    let mut visited: std::collections::HashSet<PathBuf> = std::collections::HashSet::new();
    let mut dependencies = Vec::new();
    let mut to_visit = vec![path.to_path_buf()];

    while let Some(current) = to_visit.pop() {
        if !visited.insert(current.clone()) {
            continue;
        }

        #[cfg(target_os = "macos")]
        let deps = resolve_otool_deps(&current)?;
        #[cfg(target_os = "linux")]
        let deps = resolve_ldd_deps(&current)?;
        #[cfg(not(any(target_os = "macos", target_os = "linux")))]
        let deps: Vec<PathBuf> = Vec::new();

        for dep in deps {
            if dep.exists() && !visited.contains(&dep) {
                // Heuristic: Only follow libraries in the same prefix or venv
                // to avoid bloating preload.lock with standard system libs.
                // However, RFC-0035 asks for comprehensive vetting.
                // Let's filter out core system paths but keep user/venv paths.
                let dep_str = dep.to_string_lossy();
                let is_system = dep_str.starts_with("/usr/lib")
                    || dep_str.starts_with("/lib")
                    || dep_str.starts_with("/System/Library");

                if !is_system {
                    dependencies.push(dep.clone());
                    to_visit.push(dep);
                }
            }
        }
    }

    Ok(dependencies)
}

#[cfg(target_os = "macos")]
fn resolve_otool_deps(path: &Path) -> Result<Vec<PathBuf>> {
    use std::process::Command;
    let output = Command::new("otool")
        .args(["-L", path.to_str().unwrap()])
        .output()?;
    let s = String::from_utf8_lossy(&output.stdout);
    let mut deps = Vec::new();

    for line in s.lines().skip(1) {
        let line = line.trim();
        if let Some(path_part) = line.split(" (").next() {
            let dep_path = PathBuf::from(path_part);
            if dep_path.exists() && dep_path.is_absolute() {
                deps.push(dep_path);
            }
        }
    }
    Ok(deps)
}

#[cfg(target_os = "linux")]
fn resolve_ldd_deps(path: &Path) -> Result<Vec<PathBuf>> {
    use std::process::Command;
    let output = Command::new("ldd").arg(path).output()?;
    let s = String::from_utf8_lossy(&output.stdout);
    let mut deps = Vec::new();

    for line in s.lines() {
        // e.g. "libz.so.1 => /lib/x86_64-linux-gnu/libz.so.1 (0x00007f9c...)"
        if let Some(pos) = line.find("=>") {
            let part = &line[pos + 2..];
            if let Some(path_part) = part.split_whitespace().next() {
                let dep_path = PathBuf::from(path_part);
                if dep_path.exists() && dep_path.is_absolute() {
                    deps.push(dep_path);
                }
            }
        }
    }
    Ok(deps)
}

#[cfg(not(any(target_os = "macos", target_os = "linux")))]
fn resolve_otool_deps(_path: &Path) -> Result<Vec<PathBuf>> {
    Ok(Vec::new())
}
#[cfg(not(any(target_os = "macos", target_os = "linux")))]
fn resolve_ldd_deps(_path: &Path) -> Result<Vec<PathBuf>> {
    Ok(Vec::new())
}

fn detect_package_name(path: &Path) -> String {
    let components: Vec<_> = path.components().collect();
    for i in 0..components.len() {
        let comp = components[i].as_os_str().to_string_lossy();
        if (comp == "site-packages" || comp == "dist-packages") && i + 1 < components.len() {
            let pkg_name = components[i + 1].as_os_str().to_string_lossy();
            // Strip .dist-info, .egg-info etc if it's the top level
            if pkg_name.contains(".dist-info") || pkg_name.contains(".egg-info") {
                return pkg_name.split('.').next().unwrap_or("unknown").to_string();
            }
            return pkg_name.to_string();
        }
    }
    "unknown".to_string()
}
