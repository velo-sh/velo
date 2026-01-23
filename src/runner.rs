//! Script execution for Velo
//!
//! This module handles running Python scripts with optional profiling.

use anyhow::{Context, Result};
use std::path::{Path, PathBuf};
use std::process::Command;

use crate::lifecycle::{EnvironmentShield, apply_standard_hygiene};
use crate::profile;

/// Run a Python script.
pub fn run_script(
    python: &Path,
    script_path: &str,
    pythonpath: Option<String>,
    config: &crate::config::VeloConfig,
) -> Result<()> {
    let res = (|| -> Result<()> {
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
        let mut cmd = Command::new(python);

        // RFC-0012: Surgical Environment Management (§3.1 & §3.5)
        let shield = EnvironmentShield::new(config);
        shield.apply(&mut cmd).map_err(anyhow::Error::msg)?;

        // Build final PYTHONPATH
        cmd.env("PYTHONPATH", &final_pythonpath);

        // Phase 8.0: Bridge of Truth (Configuration Injection)
        cmd.env(
            "VELO_GRACEFUL_SHUTDOWN_TIMEOUT",
            config.graceful_shutdown_timeout.to_string(),
        );
        cmd.env(
            "VELO_SOCKET_STARTUP_TIMEOUT",
            config.zygote_socket_timeout.to_string(),
        );
        cmd.env("VELO_MAX_BUNDLE_SIZE", config.max_bundle_size.to_string());
        cmd.env(
            "VELO_SLOW_THRESHOLD_MS",
            config.slow_threshold_ms.to_string(),
        );
        cmd.env(
            "VELO_SECURITY_HPC_THREADS",
            config.security_hpc_threads.to_string(),
        );

        // RFC-0012 §3.6: FD & Signal Hygiene
        apply_standard_hygiene(&mut cmd);

        let status = cmd
            .arg(script_path)
            .status()
            .context("Failed to run Python")?;

        if !status.success() {
            std::process::exit(status.code().unwrap_or(1));
        }

        Ok(())
    })();

    crate::graph::report_metrics();
    res
}

/// Run a Python script with profiling enabled.
/// Injects sitecustomize.py to track import times and displays results.
#[allow(clippy::collapsible_if)]
pub fn run_script_with_profile(
    python: &Path,
    script_path: &str,
    pythonpath: Option<String>,
    config: &crate::config::VeloConfig,
) -> Result<()> {
    let res = (|| -> Result<()> {
        println!("⏱️  Running with profiling enabled...\n");

        let (status, _total_time, profile_data) =
            run_script_with_profile_capture(python, script_path, pythonpath, config)?;

        // Display profile results if available
        if let Some(profile_data) = profile_data {
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

        println!("Total execution time: {:.2}s", _total_time.as_secs_f64());

        if !status.success() {
            std::process::exit(status.code().unwrap_or(1));
        }

        Ok(())
    })();

    crate::graph::report_metrics();
    res
}

/// Internal helper to run script and capture profile data.
pub fn run_script_with_profile_capture(
    python: &Path,
    script_path: &str,
    pythonpath: Option<String>,
    config: &crate::config::VeloConfig,
) -> Result<(
    std::process::ExitStatus,
    std::time::Duration,
    Option<profile::ProfileData>,
)> {
    use std::fs;
    use std::io::Write;

    let path = Path::new(script_path);
    if !path.exists() {
        anyhow::bail!("Script not found: {}", script_path);
    }

    // Create temp directory
    let temp_root = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
    let temp_dir = tempfile::Builder::new()
        .prefix("velo_profile_")
        .tempdir_in(&temp_root)?;
    let temp_dir_path = temp_dir.path();

    // Write sitecustomize.py
    let sitecustomize_path = temp_dir_path.join("sitecustomize.py");
    let mut file = fs::File::create(&sitecustomize_path)?;
    file.write_all(profile::SITECUSTOMIZE_PY.as_bytes())?;

    // Profile output path
    let profile_output = temp_dir_path.join("profile.json");

    // Get script directory
    let script_dir = path
        .parent()
        .map(|p| p.to_string_lossy().to_string())
        .unwrap_or_else(|| ".".to_string());

    // Build PYTHONPATH
    let temp_dir_str = temp_dir_path.to_string_lossy().to_string();
    let final_pythonpath = match pythonpath {
        Some(pp) => format!("{}:{}:{}", temp_dir_str, script_dir, pp),
        None => format!("{}:{}", temp_dir_str, script_dir),
    };

    // Measure total time
    let start = std::time::Instant::now();

    // Run the script
    let mut cmd = Command::new(python);
    let shield = EnvironmentShield::new(config);
    shield.apply(&mut cmd).map_err(anyhow::Error::msg)?;

    cmd.env("PYTHONPATH", &final_pythonpath)
        .env("VELO_PROFILE_OUTPUT", &profile_output);

    // Standard Velo envs
    cmd.env(
        "VELO_GRACEFUL_SHUTDOWN_TIMEOUT",
        config.graceful_shutdown_timeout.to_string(),
    );
    cmd.env(
        "VELO_SOCKET_STARTUP_TIMEOUT",
        config.zygote_socket_timeout.to_string(),
    );
    cmd.env("VELO_MAX_BUNDLE_SIZE", config.max_bundle_size.to_string());
    cmd.env(
        "VELO_SLOW_THRESHOLD_MS",
        config.slow_threshold_ms.to_string(),
    );
    cmd.env(
        "VELO_SECURITY_HPC_THREADS",
        config.security_hpc_threads.to_string(),
    );

    apply_standard_hygiene(&mut cmd);

    let status = cmd
        .arg(script_path)
        .status()
        .context("Failed to run Python")?;
    let total_time = start.elapsed();

    // Capture results
    let profile_data = if profile_output.exists() {
        profile::ProfileData::from_file(&profile_output).ok()
    } else {
        None
    };

    Ok((status, total_time, profile_data))
}

/// Internal helper to run module and capture profile data.
pub fn run_module_with_profile_capture(
    python: &Path,
    module_name: &str,
    args: &[&str],
    config: &crate::config::VeloConfig,
) -> Result<(
    std::process::ExitStatus,
    std::time::Duration,
    Option<profile::ProfileData>,
)> {
    use std::fs;
    use std::io::Write;

    // Create temp directory
    let temp_root = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
    let temp_dir = tempfile::Builder::new()
        .prefix("velo_profile_mod_")
        .tempdir_in(&temp_root)?;
    let temp_dir_path = temp_dir.path();

    // Write sitecustomize.py
    let sitecustomize_path = temp_dir_path.join("sitecustomize.py");
    let mut file = fs::File::create(&sitecustomize_path)?;
    file.write_all(profile::SITECUSTOMIZE_PY.as_bytes())?;

    // Profile output path
    let profile_output = temp_dir_path.join("profile.json");

    // Build PYTHONPATH
    let temp_dir_str = temp_dir_path.to_string_lossy().to_string();
    let current_dir = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
    let final_pythonpath = format!("{}:{}", temp_dir_str, current_dir.display());

    // Measure total time
    let start = std::time::Instant::now();

    // Run the module
    let mut cmd = Command::new(python);
    let shield = EnvironmentShield::new(config);
    shield.apply(&mut cmd).map_err(anyhow::Error::msg)?;

    cmd.env("PYTHONPATH", &final_pythonpath)
        .env("VELO_PROFILE_OUTPUT", &profile_output);

    // Standard Velo envs
    cmd.env(
        "VELO_GRACEFUL_SHUTDOWN_TIMEOUT",
        config.graceful_shutdown_timeout.to_string(),
    );
    cmd.env(
        "VELO_SOCKET_STARTUP_TIMEOUT",
        config.zygote_socket_timeout.to_string(),
    );
    cmd.env("VELO_MAX_BUNDLE_SIZE", config.max_bundle_size.to_string());
    cmd.env(
        "VELO_SLOW_THRESHOLD_MS",
        config.slow_threshold_ms.to_string(),
    );
    cmd.env(
        "VELO_SECURITY_HPC_THREADS",
        config.security_hpc_threads.to_string(),
    );

    apply_standard_hygiene(&mut cmd);

    cmd.arg("-m").arg(module_name);
    for arg in args {
        cmd.arg(arg);
    }

    let status = cmd.status().context("Failed to run Python module")?;
    let total_time = start.elapsed();

    // Capture results
    let profile_data = if profile_output.exists() {
        profile::ProfileData::from_file(&profile_output).ok()
    } else {
        None
    };

    Ok((status, total_time, profile_data))
}
