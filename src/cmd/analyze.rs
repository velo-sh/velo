//! Handle 'velo analyze' command
//!
//! Analyzes Python project import times and suggests optimizations.
//! Uses runtime profiling (not hardcoded framework lists) per RFC-0004.

use anyhow::{Context, Result};
use std::path::{Path, PathBuf};
use std::process::Command;

use crate::common::paths::VeloPaths;
use crate::config::VeloConfig;
use crate::profile::{ProfileData, SITECUSTOMIZE_PY, get_optimization_suggestions};
use crate::python;
use crate::shm::registry::MemoryRegistry;
use crate::zygote::ZygoteLauncher;

/// Arguments for the analyze command.
#[derive(Debug, Clone)]
pub struct AnalyzeArgs {
    /// Entry point file (default: auto-detect)
    pub file: Option<PathBuf>,
    /// Output file for JSON report
    pub output: Option<PathBuf>,
    /// Show preload suggestions
    pub suggest_preload: bool,
    /// Auto-fix: update pyproject.toml with recommendations
    pub fix: bool,
    /// Threshold in ms for "slow" imports (default: 100)
    pub slow_threshold_ms: u64,
    /// Show import graph and savings report (D9, RFC §5.4)
    pub graph: bool,
    /// Map a .safetensors file into shared memory (Memory Gravity)
    pub shm: Option<PathBuf>,
}

impl Default for AnalyzeArgs {
    fn default() -> Self {
        Self {
            file: None,
            output: None,
            suggest_preload: false,
            fix: false,
            slow_threshold_ms: 100,
            graph: false,
            shm: None,
        }
    }
}

/// Validate a path argument for security issues
/// DEF-4.0-002: Reject special paths like /dev/null
/// DEF-4.0-003: Reject paths with null bytes
fn validate_path(path: &str, arg_name: &str) -> Result<PathBuf> {
    // DEF-4.0-001: Check for empty path
    if path.is_empty() {
        anyhow::bail!("{} is empty", arg_name);
    }

    // DEF-4.0-003: Check for null bytes
    if path.contains('\0') {
        anyhow::bail!("{} contains invalid null byte: {:?}", arg_name, path);
    }

    // DEF-4.0-002: Reject device paths
    if path.starts_with("/dev/") {
        anyhow::bail!(
            "{} access denied: device path not allowed: {}",
            arg_name,
            path
        );
    }

    // SEC-P0-002: Path Traversal Protection
    // Ensure the path is within the project root for BOTH absolute AND relative paths
    let path_buf = PathBuf::from(path);
    let project_root = std::env::current_dir().unwrap_or_else(|_| Path::new(".").to_path_buf());
    let canonical_root = project_root.canonicalize().unwrap_or(project_root.clone());

    // Convert relative path to absolute by joining with canonical project root
    let full_path = if path_buf.is_absolute() {
        path_buf.clone()
    } else {
        canonical_root.join(&path_buf)
    };

    // Strict canonicalization check
    let canonical_path = if full_path.exists() {
        full_path.canonicalize().ok()
    } else if let Some(parent) = full_path.parent() {
        parent
            .canonicalize()
            .ok()
            .map(|p| p.join(full_path.file_name().unwrap_or_default()))
    } else {
        None
    };

    if let Some(cp) = canonical_path {
        if !cp.starts_with(&canonical_root) {
            anyhow::bail!(
                "{} access denied: path traversal detected (resolves outside project root)",
                arg_name
            );
        }
    } else {
        // Fallback for cases where even the parent doesn't exist
        let normalized = normalize_path_components(&full_path);
        if !normalized.starts_with(&canonical_root) {
            anyhow::bail!(
                "{} access denied: path traversal detected (would resolve outside project root)",
                arg_name
            );
        }
    }

    Ok(path_buf)
}

/// Normalize path by resolving .. and . components without requiring the path to exist
fn normalize_path_components(path: &Path) -> PathBuf {
    let mut components = Vec::new();
    for component in path.components() {
        match component {
            std::path::Component::ParentDir => {
                components.pop();
            }
            std::path::Component::CurDir => {}
            c => components.push(c),
        }
    }
    components.iter().collect()
}

// Local VeloConfig removed in favor of crate::config::VeloConfig

/// ANSI color codes for terminal output
mod colors {
    pub const RESET: &str = "\x1b[0m";
    pub const BOLD: &str = "\x1b[1m";
    pub const RED: &str = "\x1b[31m";
    pub const GREEN: &str = "\x1b[32m";
    pub const YELLOW: &str = "\x1b[33m";
    pub const CYAN: &str = "\x1b[36m";
    pub const DIM: &str = "\x1b[2m";
}

/// Handle 'velo analyze' command
pub fn cmd_analyze(args: &[String]) -> Result<()> {
    let parsed = parse_args(args)?;

    // Determine project directory
    let project_dir = std::env::current_dir().unwrap_or_else(|_| Path::new(".").to_path_buf());

    // Read existing [tool.velo] config
    let config = VeloConfig::load_with_overrides(&VeloPaths::pyproject(&project_dir));

    // Determine effective threshold (CLI > config > default)
    let effective_threshold = if parsed.slow_threshold_ms != 100 {
        parsed.slow_threshold_ms // CLI takes priority
    } else {
        config.slow_threshold_ms
    };

    // Show existing config (always present now via VeloConfig::load_with_overrides)
    eprintln!(
        "{}📦 Using [tool.velo] config:{}",
        colors::CYAN,
        colors::RESET
    );
    if !config.preload.is_empty() {
        eprintln!("   preload = {:?}", config.preload);
    }
    eprintln!("   slow_threshold_ms = {}", config.slow_threshold_ms);
    eprintln!();

    // DEF-70-004: Validate SHM argument early to fail fast on errors
    // This allows detecting invalid/malicious SHM files before finding the entry point script
    if let Some(ref shm_path) = parsed.shm {
        // We use MemoryRegistry's validation logic which handles 1PB checks etc.
        MemoryRegistry::validate_source(shm_path)
            .with_context(|| format!("InvalidSourceFile: {}", shm_path.display()))?;
    }

    // Find entry point script
    let script = match &parsed.file {
        Some(f) => f.clone(),
        None => find_entry_point(&project_dir)?,
    };

    // Detect Python
    let python_path = python::detect_python(&project_dir)?;

    // Security notice: velo analyze executes the script to gather real import times
    // This is by design (RFC-0004) - measuring actual import performance requires execution
    eprintln!(
        "{}⚠️  note: script will be executed to measure import times{}",
        colors::YELLOW,
        colors::RESET
    );

    // Run with profiling
    eprintln!(
        "{}📊 analyzing imports for {}...{}",
        colors::CYAN,
        script.display(),
        colors::RESET
    );

    let profile_data = run_with_profile(
        &python_path,
        &script,
        &project_dir,
        parsed.shm.as_ref(),
        &config,
    )?;

    // Display results
    display_analysis(&profile_data, effective_threshold);

    // Show savings report if --graph requested (D9, RFC §5.4)
    if parsed.graph {
        display_savings_report(&profile_data);
    }

    // Show suggestions if requested
    if parsed.suggest_preload {
        display_preload_suggestions(&profile_data, effective_threshold, Some(&config));
    }

    // Output to file if requested
    if let Some(output_path) = &parsed.output {
        save_json_report(&profile_data, output_path)?;
        eprintln!(
            "\n{}✅ Report saved to {}{}",
            colors::GREEN,
            output_path.display(),
            colors::RESET
        );
    }

    // Auto-fix if requested
    if parsed.fix {
        update_pyproject_toml(&project_dir, &profile_data, effective_threshold)?;
    }

    Ok(())
}

/// Parse command-line arguments
fn parse_args(args: &[String]) -> Result<AnalyzeArgs> {
    let mut parsed = AnalyzeArgs::default();
    let mut i = 2; // Skip "velo" and "analyze"

    while i < args.len() {
        let arg = &args[i];

        // Handle --key=value syntax
        if let Some((key, value)) = arg.split_once('=') {
            match key {
                "--output" | "-o" => {
                    parsed.output = Some(validate_path(value, "--output")?);
                }
                "--slow-threshold-ms" => {
                    parsed.slow_threshold_ms = value
                        .parse()
                        .with_context(|| format!("Invalid --slow-threshold-ms value: {}", value))?;
                }
                "--shm" => {
                    parsed.shm = Some(validate_path(value, "--shm")?);
                }
                _ => {
                    anyhow::bail!("Unknown option: {}", key);
                }
            }
            i += 1;
            continue;
        }

        // Handle --key value syntax
        match arg.as_str() {
            "--output" | "-o" => {
                i += 1;
                if i >= args.len() {
                    anyhow::bail!("--output requires a path argument");
                }
                parsed.output = Some(validate_path(&args[i], "--output")?);
            }
            "--suggest-preload" => {
                parsed.suggest_preload = true;
            }
            "--fix" => {
                parsed.fix = true;
                parsed.suggest_preload = true; // --fix implies --suggest-preload
            }
            "--slow-threshold-ms" => {
                i += 1;
                if i >= args.len() {
                    anyhow::bail!("--slow-threshold-ms requires a number argument");
                }
                parsed.slow_threshold_ms = args[i]
                    .parse()
                    .with_context(|| "Invalid --slow-threshold-ms value")?;
            }
            "--graph" => {
                parsed.graph = true;
            }
            "--shm" => {
                i += 1;
                if i >= args.len() {
                    anyhow::bail!("--shm requires a path argument");
                }
                parsed.shm = Some(validate_path(&args[i], "--shm")?);
            }
            "-h" | "--help" => {
                print_analyze_help();
                std::process::exit(0);
            }
            arg if arg.starts_with('-') => {
                anyhow::bail!("Unknown option: {}", arg);
            }
            _ => {
                parsed.file = Some(validate_path(&args[i], "file")?);
            }
        }
        i += 1;
    }

    Ok(parsed)
}

/// Print help message for analyze command
fn print_analyze_help() {
    println!(
        r#"velo analyze - Analyze import times and suggest optimizations

USAGE:
    velo analyze [OPTIONS] [file.py]

ARGUMENTS:
    [file.py]    Entry point file (auto-detects main.py, app.py if not specified)

OPTIONS:
    --slow-threshold-ms <MS>  Threshold for 'slow' imports (default: 100)
    --suggest-preload         Show preload suggestions for slow imports
    --graph                   Show startup savings report (stat() elimination)
    --fix                     Auto-update pyproject.toml with preload config
    --output, -o <FILE>       Save JSON report to file
    --shm <PATH>              Map .safetensors into shared memory (Memory Gravity)
    -h, --help                Print help

EXAMPLES:
    velo analyze                    # Analyze with auto-detected entry point
    velo analyze main.py            # Analyze specific file
    velo analyze --graph            # Show savings from Velo optimization
    velo analyze --slow-threshold-ms 50  # Custom threshold
    velo analyze --fix              # Update pyproject.toml automatically

NOTE:
    ⚠️  The script WILL BE EXECUTED to measure real import times.
    Only run this on code you trust.
"#
    );
}

/// Find entry point file automatically
fn find_entry_point(project_dir: &Path) -> Result<PathBuf> {
    // Common entry point names
    let candidates = ["main.py", "app.py", "run.py", "__main__.py"];

    for name in candidates {
        let path = project_dir.join(name);
        if path.exists() {
            return Ok(path);
        }
    }

    anyhow::bail!(
        "No entry point found. Please specify a file: velo analyze <script.py>\n\
         Tried: main.py, app.py, run.py, __main__.py"
    )
}

/// Run script with profiling and return parsed data
fn run_with_profile(
    python_path: &Path,
    script: &Path,
    project_dir: &Path,
    shm_path: Option<&PathBuf>,
    config: &VeloConfig,
) -> Result<ProfileData> {
    // Create temp directory for sitecustomize.py and profiling results
    let temp_dir = tempfile::tempdir().context("Failed to create temp directory")?;
    let sitecustomize_path = temp_dir.path().join("sitecustomize.py");
    let profile_output_path = temp_dir.path().join("velo_profile.json");

    // Write sitecustomize.py
    std::fs::write(&sitecustomize_path, SITECUSTOMIZE_PY)
        .context("Failed to write sitecustomize.py")?;

    // Build PYTHONPATH with sitecustomize directory first
    let pythonpath_dir = temp_dir.path().to_string_lossy().to_string();

    // Create a wrapper script that imports sitecustomize before running the user script
    let wrapper_content = format!(
        r#"import sys; import os; os.environ['VELO_PROFILE_OUTPUT'] = r"{}"; sys.path.insert(0, r"{}"); import sitecustomize; exec(open(r"{}").read()); sitecustomize._velo_write_profile()"#,
        profile_output_path.to_string_lossy(),
        &pythonpath_dir,
        script.to_string_lossy()
    );

    if let Some(shm_path) = shm_path {
        // USE ZYGOTE for Memory Gravity analysis
        use crate::zygote;
        if !zygote::is_supported() {
            anyhow::bail!(
                "Memory Gravity (--shm) requires Zygote which is not supported on this platform"
            );
        }

        let socket_path = zygote::ipc::default_socket_path();
        let mut launcher =
            ZygoteLauncher::new(socket_path.clone()).with_python(python_path.to_path_buf());

        // Ensure Zygote is running
        if !socket_path.exists() {
            eprintln!("🚀 Starting Zygote for SHM analysis...");
            launcher
                .start(&[], None, false, config)
                .context("Failed to start Zygote")?;
        }

        // Create SHM segment
        let registry = MemoryRegistry::new(config.clone());
        let segment_name = format!("shm-analyze-{}", std::process::id());
        let shm_file = registry
            .create_segment(&segment_name, shm_path)
            .context("Failed to create SHM segment")?;

        // Write wrapper to a temporary file because Zygote needs a Path
        let wrapper_path = temp_dir.path().join("velo_analyze_wrapper.py");
        std::fs::write(&wrapper_path, &wrapper_content)
            .context("Failed to write wrapper script")?;

        // Spawn worker via Zygote
        let worker = launcher
            .spawn_worker(
                &wrapper_path,
                &[],
                false, // async_mode
                false, // fast_mode
                None,  // bundle_path
                Some(project_dir.to_path_buf()),
                None, // max_bundle_size
                Some(&shm_file.file),
                config,
            )
            .context("Failed to spawn analysis worker via Zygote")?;

        // Set environment variable for profiling output path
        // Note: Zygote doesn't inherit environment from CLI, so we must ensure
        // the worker knows where to write the JSON.
        // Actually, ZygoteLauncher::spawn_worker currently doesn't support custom env vars.
        // But WAIT: sitecustomize._velo_write_profile() uses VELO_PROFILE_OUTPUT env var.

        // TODO: Update spawn_worker to support environment variables if needed.
        // For now, we'll rely on the default behavior or fix sitecustomize.

        // wait for worker
        let _ = worker.wait();
    } else {
        // NORMAL MODE: run fresh process
        Command::new(python_path)
            .arg("-c")
            .arg(&wrapper_content)
            .current_dir(project_dir)
            .env("PYTHONPATH", &pythonpath_dir)
            .env(
                "VELO_PROFILE_OUTPUT",
                profile_output_path.to_string_lossy().as_ref(),
            )
            .output()
            .context("Failed to run Python script")?;
    }

    // Parse profile data
    if profile_output_path.exists() {
        ProfileData::from_file(&profile_output_path)
    } else {
        anyhow::bail!(
            "No profile data generated. Script may have crashed before imports completed."
        )
    }
}

/// Display analysis results with visual bar chart
fn display_analysis(profile: &ProfileData, threshold_ms: u64) {
    let top = profile.top_imports(15);
    let max_time = top.first().map(|(_, t)| *t).unwrap_or(1.0);

    println!();
    println!(
        "{}┌─────────────────────────────────────────────────────────────┐{}",
        colors::BOLD,
        colors::RESET
    );
    println!(
        "{}│                    Import Analysis                          │{}",
        colors::BOLD,
        colors::RESET
    );
    println!(
        "{}├─────────────────────────────────────────────────────────────┤{}",
        colors::BOLD,
        colors::RESET
    );

    for (name, time_ms) in &top {
        let bar_width = ((time_ms / max_time) * 25.0) as usize;
        let bar: String = "█".repeat(bar_width);

        // Color based on threshold
        let (color, label) = if *time_ms >= threshold_ms as f64 {
            (colors::RED, " ← SLOW")
        } else if *time_ms >= (threshold_ms / 2) as f64 {
            (colors::YELLOW, "")
        } else {
            (colors::GREEN, "")
        };

        println!(
            "│ {:28} {:>7.1}ms │ {}{:25}{} {}│",
            truncate_str(name, 28),
            time_ms,
            color,
            bar,
            colors::RESET,
            label
        );
    }

    // Show remaining count
    let remaining = profile.import_times.len().saturating_sub(15);
    if remaining > 0 {
        let remaining_time: f64 =
            profile.total_import_time_ms - top.iter().map(|(_, t)| t).sum::<f64>();
        println!(
            "│ {}({} more modules){:>23.1}ms │                           │",
            colors::DIM,
            remaining,
            remaining_time,
        );
        print!("{}", colors::RESET);
    }

    println!(
        "{}├─────────────────────────────────────────────────────────────┤{}",
        colors::BOLD,
        colors::RESET
    );
    println!(
        "{}│ TOTAL                           {:>7.1}ms │                           │{}",
        colors::BOLD,
        profile.total_import_time_ms,
        colors::RESET
    );
    println!(
        "{}└─────────────────────────────────────────────────────────────┘{}",
        colors::BOLD,
        colors::RESET
    );
}

/// Display preload suggestions based on slow imports
fn display_preload_suggestions(
    profile: &ProfileData,
    threshold_ms: u64,
    existing_config: Option<&VeloConfig>,
) {
    let slow_imports: Vec<_> = profile
        .import_times
        .iter()
        .filter(|(_, time)| **time >= threshold_ms as f64)
        .map(|(name, time)| (name.as_str(), *time))
        .collect();

    if slow_imports.is_empty() {
        println!(
            "\n{}✨ No slow imports detected (threshold: {}ms){}",
            colors::GREEN,
            threshold_ms,
            colors::RESET
        );
        return;
    }

    println!();
    println!(
        "{}💡 Optimization Suggestions:{}",
        colors::CYAN,
        colors::RESET
    );
    println!();

    // Sort by time descending
    let mut sorted = slow_imports;
    sorted.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));

    // Get top-level module names for preload
    let preload_modules: Vec<_> = sorted
        .iter()
        .map(|(name, _)| name.split('.').next().unwrap_or(name))
        .collect::<std::collections::HashSet<_>>()
        .into_iter()
        .collect();

    // Check which are already configured
    let already_preloaded: Vec<_> = if let Some(cfg) = existing_config {
        preload_modules
            .iter()
            .filter(|m| cfg.preload.iter().any(|p| p == **m))
            .cloned()
            .collect()
    } else {
        vec![]
    };

    let new_modules: Vec<_> = preload_modules
        .iter()
        .filter(|m| !already_preloaded.contains(m))
        .cloned()
        .collect();

    if !already_preloaded.is_empty() {
        println!(
            "  {}✓ Already in preload:{} {:?}",
            colors::GREEN,
            colors::RESET,
            already_preloaded
        );
    }

    if !new_modules.is_empty() {
        println!(
            "  {}1. Add to preload:{} {:?}",
            colors::BOLD,
            colors::RESET,
            new_modules
        );
    }

    // Show specific suggestions for known modules
    println!();
    for (name, time) in &sorted {
        if let Some(suggestion) = get_optimization_suggestions(name) {
            println!(
                "  {}• {}{} ({:.1}ms): {}",
                colors::YELLOW,
                name,
                colors::RESET,
                time,
                suggestion
            );
        }
    }

    // Show config hint if there are new modules
    if !new_modules.is_empty() {
        println!();
        println!("  {}Add to pyproject.toml:{}", colors::DIM, colors::RESET);
        println!("  {}[tool.velo]{}", colors::DIM, colors::RESET);
        println!(
            "  {}preload = {:?}{}",
            colors::DIM,
            new_modules,
            colors::RESET
        );
    }
}

/// Display startup savings report (D9, RFC §5.4)
///
/// Shows estimated savings from Velo's optimization compared to traditional Python.
fn display_savings_report(profile: &ProfileData) {
    let module_count = profile.import_times.len();

    // Traditional Python: approximately 4 stat() calls per module
    // (check .py, .pyc, package __init__.py, etc.)
    let traditional_stats = module_count * 4;

    // Velo: 0 stat() calls with bundled imports (mmap-based)
    let velo_stats = 0;

    // Estimated time per stat() call: ~0.3ms on typical SSD
    // This is conservative; NFS/network drives can be 10x slower
    let time_per_stat_ms = 0.33;
    let estimated_savings_ms = (traditional_stats as f64) * time_per_stat_ms;

    // Calculate percentage of import time that could be saved
    let import_overhead_pct = if profile.total_import_time_ms > 0.0 {
        (estimated_savings_ms / profile.total_import_time_ms * 100.0).min(100.0)
    } else {
        0.0
    };

    println!();
    println!(
        "{}┌─────────────────────────────────────────────────────────────┐{}",
        colors::BOLD,
        colors::RESET
    );
    println!(
        "{}│                  Startup Savings Report                     │{}",
        colors::BOLD,
        colors::RESET
    );
    println!(
        "{}├─────────────────────────────────────────────────────────────┤{}",
        colors::BOLD,
        colors::RESET
    );
    println!(
        "│ {}Modules analyzed:{}          {:>6}                           │",
        colors::CYAN,
        colors::RESET,
        module_count
    );
    println!(
        "│ Traditional Python:   {:>6} stat() syscalls                 │",
        traditional_stats
    );
    println!(
        "│ {}Velo optimized:{}       {:>6} stat() syscalls                 │",
        colors::GREEN,
        colors::RESET,
        velo_stats
    );
    println!(
        "{}├─────────────────────────────────────────────────────────────┤{}",
        colors::BOLD,
        colors::RESET
    );
    println!(
        "│ {}Estimated time saved:{}    ~{:.0}ms ({:.0}% of import overhead)  │",
        colors::GREEN,
        colors::RESET,
        estimated_savings_ms,
        import_overhead_pct
    );
    println!(
        "{}└─────────────────────────────────────────────────────────────┘{}",
        colors::BOLD,
        colors::RESET
    );

    // Additional context
    println!();
    println!(
        "{}💡 Tip:{} Use 'velo bundle' to create an optimized bundle, then",
        colors::CYAN,
        colors::RESET
    );
    println!("       'velo run --fast' to skip filesystem checks entirely.");
}

/// Save JSON report to file
fn save_json_report(profile: &ProfileData, output_path: &Path) -> Result<()> {
    let json = serde_json::to_string_pretty(&profile.import_times)
        .context("Failed to serialize profile data")?;
    std::fs::write(output_path, json).context("Failed to write report file")?;
    Ok(())
}

/// Update pyproject.toml with preload configuration
fn update_pyproject_toml(
    project_dir: &Path,
    profile: &ProfileData,
    threshold_ms: u64,
) -> Result<()> {
    let pyproject_path = VeloPaths::pyproject(project_dir);

    // Get slow imports as top-level module names
    let preload_modules: Vec<String> = profile
        .import_times
        .iter()
        .filter(|(_, time)| **time >= threshold_ms as f64)
        .map(|(name, _)| name.split('.').next().unwrap_or(name).to_string())
        .collect::<std::collections::HashSet<_>>()
        .into_iter()
        .collect();

    if preload_modules.is_empty() {
        eprintln!(
            "\n{}ℹ️ No slow imports to add to preload{}",
            colors::CYAN,
            colors::RESET
        );
        return Ok(());
    }

    // Read existing pyproject.toml or create new one
    let content = if pyproject_path.exists() {
        std::fs::read_to_string(&pyproject_path).context("Failed to read pyproject.toml")?
    } else {
        String::new()
    };

    // Check if [tool.velo] section exists
    let new_content = if content.contains("[tool.velo]") {
        // Update existing section (simple approach - just warn for now)
        eprintln!(
            "\n{}⚠️ [tool.velo] section already exists. Please update manually:{}",
            colors::YELLOW,
            colors::RESET
        );
        eprintln!("  preload = {:?}", preload_modules);
        return Ok(());
    } else {
        // Append new section
        let velo_config = format!("\n[tool.velo]\npreload = {:?}\n", preload_modules);
        format!("{}{}", content, velo_config)
    };

    std::fs::write(&pyproject_path, new_content).context("Failed to write pyproject.toml")?;

    eprintln!(
        "\n{}✅ Updated pyproject.toml with preload configuration{}",
        colors::GREEN,
        colors::RESET
    );
    eprintln!("  preload = {:?}", preload_modules);

    Ok(())
}

/// Truncate string with ellipsis
fn truncate_str(s: &str, max_len: usize) -> String {
    if s.len() <= max_len {
        format!("{:width$}", s, width = max_len)
    } else {
        format!("{}...", &s[..max_len - 3])
    }
}

// ============================================================================
// TESTS
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_args_default() {
        let args = vec!["velo".to_string(), "analyze".to_string()];
        let parsed = parse_args(&args).unwrap();
        assert!(parsed.file.is_none());
        assert_eq!(parsed.slow_threshold_ms, 100);
        assert!(!parsed.suggest_preload);
        assert!(!parsed.fix);
    }

    #[test]
    fn test_parse_args_with_file() {
        let args = vec![
            "velo".to_string(),
            "analyze".to_string(),
            "main.py".to_string(),
        ];
        let parsed = parse_args(&args).unwrap();
        assert_eq!(parsed.file, Some(PathBuf::from("main.py")));
    }

    #[test]
    fn test_parse_args_with_threshold() {
        let args = vec![
            "velo".to_string(),
            "analyze".to_string(),
            "--slow-threshold-ms".to_string(),
            "50".to_string(),
            "main.py".to_string(),
        ];
        let parsed = parse_args(&args).unwrap();
        assert_eq!(parsed.slow_threshold_ms, 50);
        assert_eq!(parsed.file, Some(PathBuf::from("main.py")));
    }

    #[test]
    fn test_parse_args_fix_implies_suggest() {
        let args = vec![
            "velo".to_string(),
            "analyze".to_string(),
            "--fix".to_string(),
        ];
        let parsed = parse_args(&args).unwrap();
        assert!(parsed.fix);
        assert!(parsed.suggest_preload); // --fix implies --suggest-preload
    }

    #[test]
    fn test_truncate_str() {
        assert_eq!(truncate_str("short", 10), "short     ");
        assert_eq!(truncate_str("verylongmodulename", 10), "verylon...");
    }

    #[test]
    fn test_parse_args_equals_syntax() {
        // DEF-4.0-001: Support --key=value syntax
        let args = vec![
            "velo".to_string(),
            "analyze".to_string(),
            "--slow-threshold-ms=50".to_string(),
            "main.py".to_string(),
        ];
        let parsed = parse_args(&args).unwrap();
        assert_eq!(parsed.slow_threshold_ms, 50);
        assert_eq!(parsed.file, Some(PathBuf::from("main.py")));
    }

    #[test]
    fn test_parse_args_output_equals_syntax() {
        let args = vec![
            "velo".to_string(),
            "analyze".to_string(),
            "--output=report.json".to_string(),
        ];
        let parsed = parse_args(&args).unwrap();
        assert_eq!(parsed.output, Some(PathBuf::from("report.json")));
    }

    #[test]
    fn test_validate_path_dev_null() {
        // DEF-4.0-002: /dev/null should be rejected
        let result = validate_path("/dev/null", "file");
        assert!(result.is_err());
        assert!(result.unwrap_err().to_string().contains("device path"));
    }

    #[test]
    fn test_validate_path_null_byte() {
        // DEF-4.0-003: Null bytes should be rejected
        let result = validate_path("file\0.py", "file");
        assert!(result.is_err());
        assert!(result.unwrap_err().to_string().contains("null byte"));
    }

    #[test]
    fn test_validate_path_empty() {
        let result = validate_path("", "file");
        assert!(result.is_err());
        assert!(result.unwrap_err().to_string().contains("empty"));
    }

    #[test]
    fn test_validate_path_valid() {
        let result = validate_path("main.py", "file");
        assert!(result.is_ok());
        assert_eq!(result.unwrap(), PathBuf::from("main.py"));
    }

    #[test]
    fn test_validate_path_relative_traversal() {
        // SEC-P0-002: Relative path traversal should be rejected
        let result = validate_path("../../etc/passwd", "file");
        assert!(result.is_err());
        assert!(result.unwrap_err().to_string().contains("path traversal"));
    }

    #[test]
    fn test_validate_path_relative_traversal_nested() {
        // SEC-P0-002: Nested relative path traversal should be rejected
        let result = validate_path("subdir/../../../etc/passwd", "file");
        assert!(result.is_err());
        assert!(result.unwrap_err().to_string().contains("path traversal"));
    }
}
