//! Script execution for Velo
//!
//! This module handles running Python scripts with optional profiling.

use anyhow::{Context, Result};
use std::path::Path;
use std::process::Command;

use crate::profile;

/// Run a Python script.
pub fn run_script(python: &Path, script_path: &str, pythonpath: Option<String>) -> Result<()> {
    let path = Path::new(script_path);
    if !path.exists() {
        anyhow::bail!("Script not found: {}", script_path);
    }

    // Get script directory for relative imports
    let script_dir = path
        .parent()
        .map(|p| p.to_string_lossy().to_string())
        .unwrap_or_else(|| ".".to_string());

    // Build PYTHONPATH
    let final_pythonpath = match pythonpath {
        Some(pp) => format!("{}:{}", script_dir, pp),
        None => script_dir,
    };

    // Run the script using user's Python
    let status = Command::new(python)
        .env("PYTHONPATH", &final_pythonpath)
        .env("PYTHONUNBUFFERED", "1")
        .arg(script_path)
        .status()
        .context("Failed to run Python")?;

    if !status.success() {
        crate::graph::report_metrics();
        std::process::exit(status.code().unwrap_or(1));
    }

    crate::graph::report_metrics();
    Ok(())
}

/// Run a Python script with profiling enabled.
/// Injects sitecustomize.py to track import times and displays results.
#[allow(clippy::collapsible_if)]
pub fn run_script_with_profile(
    python: &Path,
    script_path: &str,
    pythonpath: Option<String>,
) -> Result<()> {
    use std::fs;
    use std::io::Write;

    let path = Path::new(script_path);
    if !path.exists() {
        anyhow::bail!("Script not found: {}", script_path);
    }

    // Create temp directory for sitecustomize.py and profile output
    let temp_dir = std::env::temp_dir().join("velo_profile");
    fs::create_dir_all(&temp_dir)?;

    // Write sitecustomize.py
    let sitecustomize_path = temp_dir.join("sitecustomize.py");
    let mut file = fs::File::create(&sitecustomize_path)?;
    file.write_all(profile::SITECUSTOMIZE_PY.as_bytes())?;

    // Profile output path
    let profile_output = temp_dir.join("profile.json");

    // Get script directory for relative imports
    let script_dir = path
        .parent()
        .map(|p| p.to_string_lossy().to_string())
        .unwrap_or_else(|| ".".to_string());

    // Build PYTHONPATH with temp dir first (for sitecustomize.py)
    let temp_dir_str = temp_dir.to_string_lossy().to_string();
    let final_pythonpath = match pythonpath {
        Some(pp) => format!("{}:{}:{}", temp_dir_str, script_dir, pp),
        None => format!("{}:{}", temp_dir_str, script_dir),
    };

    println!("⏱️  Running with profiling enabled...\n");

    // Measure total time
    let start = std::time::Instant::now();

    // Run the script using user's Python with profile output env var
    let status = Command::new(python)
        .env("PYTHONPATH", &final_pythonpath)
        .env("PYTHONUNBUFFERED", "1")
        .env("VELO_PROFILE_OUTPUT", &profile_output)
        .arg(script_path)
        .status()
        .context("Failed to run Python")?;

    let total_time = start.elapsed();

    // Display profile results if available
    if profile_output.exists() {
        if let Ok(profile_data) = profile::ProfileData::from_file(&profile_output) {
            println!("\n{}", profile_data.format_table(10));

            // Show optimization suggestions for top imports
            let top = profile_data.top_imports(5);
            let suggestions: Vec<_> = top
                .iter()
                .filter_map(|(name, _)| {
                    profile::get_optimization_suggestions(name)
                        .map(|s| format!("   • {}: {}", name, s))
                })
                .collect();

            if !suggestions.is_empty() {
                println!("💡 Optimization Suggestions:");
                for s in suggestions {
                    println!("{}", s);
                }
                println!();
            }
        }
    }

    println!("Total execution time: {:.2}s", total_time.as_secs_f64());

    // Cleanup temp files
    let _ = fs::remove_file(&sitecustomize_path);
    let _ = fs::remove_file(&profile_output);

    if !status.success() {
        crate::graph::report_metrics();
        std::process::exit(status.code().unwrap_or(1));
    }

    crate::graph::report_metrics();
    Ok(())
}
