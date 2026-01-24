//! Script execution for Velo
//!
//! This module handles running Python scripts with optional profiling.

use anyhow::{Context, Result};
use std::path::{Path, PathBuf};
use std::process::Command;

use crate::lifecycle::{EnvironmentShield, apply_standard_hygiene};
use crate::profile;
use std::fs;
use std::io::Write;
use tempfile::TempDir;

/// Helper to setup a temporary sitecustomize.py for profiling or preloading.
/// Returns (new_pythonpath, Option<TempDir>)
fn setup_sitecustomize(
    base_pythonpath: &str,
    _config: &crate::config::VeloConfig,
    force_preload: bool,
) -> Result<(String, Option<TempDir>)> {
    let has_lock = std::env::var("VELO_RUNTIME_PRELOAD_LOCK").is_ok()
        || Path::new("preload.lock").exists()
        || force_preload;

    if !has_lock {
        return Ok((base_pythonpath.to_string(), None));
    }

    // Create temp directory for sitecustomize.py
    let temp_root = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
    let temp_dir = tempfile::Builder::new()
        .prefix("velo_site_")
        .tempdir_in(&temp_root)?;
    let temp_dir_path = temp_dir.path();

    // Write sitecustomize.py (includes native preloading hook)
    let sitecustomize_path = temp_dir_path.join("sitecustomize.py");
    let mut file = fs::File::create(&sitecustomize_path)?;
    file.write_all(profile::SITECUSTOMIZE_PY.as_bytes())?;

    // Prepend temp dir to PYTHONPATH
    let temp_dir_str = temp_dir_path.to_string_lossy().to_string();
    let new_pythonpath = format!("{}:{}", temp_dir_str, base_pythonpath);

    Ok((new_pythonpath, Some(temp_dir)))
}

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

        // Build base PYTHONPATH (Include CWD for velo_zygote)
        let cwd = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
        let cwd_str = cwd.to_string_lossy();
        let final_pythonpath = match pythonpath {
            Some(pp) => format!("{}:{}:{}", script_dir, cwd_str, pp),
            None => format!("{}:{}", script_dir, cwd_str),
        };

        // Run the script using user's Python
        let mut cmd = Command::new(python);

        // RFC-0012: Surgical Environment Management (§3.1 & §3.5)
        let shield = EnvironmentShield::new(config);
        shield.apply(&mut cmd).map_err(anyhow::Error::msg)?;

        // Build final PYTHONPATH
        let (final_pythonpath_env, _sc_temp) =
            setup_sitecustomize(&final_pythonpath, config, false)?;
        cmd.env("PYTHONPATH", &final_pythonpath_env);

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

        // RFC-0035/SPEC-0005: Native Preload SSOT Injection
        if let Ok(exe_path) = std::env::current_exe() {
            cmd.env("VELO_RUNTIME_EXE_PATH", exe_path);
        }

        let lock_path_in_script = path.parent().unwrap_or(Path::new(".")).join("preload.lock");
        let lock_path_in_cwd = Path::new("preload.lock");

        let final_lock_path = if lock_path_in_script.exists() {
            Some(lock_path_in_script)
        } else if lock_path_in_cwd.exists() {
            Some(lock_path_in_cwd.to_path_buf())
        } else {
            None
        };

        if let Some(lp) = final_lock_path
            && let Ok(lock_json) = std::fs::read_to_string(&lp)
        {
            cmd.env("VELO_RUNTIME_PRELOAD_LOCK", lock_json);
        }

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
    let path = Path::new(script_path);
    if !path.exists() {
        anyhow::bail!("Script not found: {}", script_path);
    }

    // Get script directory
    let script_dir = path
        .parent()
        .map(|p| p.to_string_lossy().to_string())
        .unwrap_or_else(|| ".".to_string());

    // Build base PYTHONPATH
    let final_pythonpath = match pythonpath {
        Some(pp) => format!("{}:{}", script_dir, pp),
        None => script_dir,
    };

    // Setup sitecustomize for profiling AND preloading (forced for profile)
    let (final_pythonpath_env, temp_dir_option) =
        setup_sitecustomize(&final_pythonpath, config, true)?;

    // Profile output path
    let profile_output = if let Some(temp_dir) = &temp_dir_option {
        temp_dir.path().join("profile.json")
    } else {
        // This case should ideally not happen if setup_sitecustomize always returns a temp_dir
        // when `force_preload` is true. For now, we'll use a fallback or error.
        // Given the context, `setup_sitecustomize` with `true` for `force_preload`
        // should always return `Some(temp_dir)`.
        anyhow::bail!("Failed to get temporary directory for profile output.");
    };

    // Measure memory and time
    let rss_before = crate::common::memory::get_process_rss_bytes().unwrap_or(0);
    let start = std::time::Instant::now();

    // Run the script
    let mut cmd = Command::new(python);
    let shield = EnvironmentShield::new(config);
    shield.apply(&mut cmd).map_err(anyhow::Error::msg)?;

    cmd.env("PYTHONPATH", &final_pythonpath_env)
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

    // RFC-0035/SPEC-0005: Native Preload SSOT Injection
    if let Ok(exe_path) = std::env::current_exe() {
        cmd.env("VELO_RUNTIME_EXE_PATH", exe_path);
    }
    let lock_path_in_script = path.parent().unwrap_or(Path::new(".")).join("preload.lock");
    let lock_path_in_cwd = Path::new("preload.lock");

    let final_lock_path = if lock_path_in_script.exists() {
        Some(lock_path_in_script)
    } else if lock_path_in_cwd.exists() {
        Some(lock_path_in_cwd.to_path_buf())
    } else {
        None
    };

    if let Some(lp) = final_lock_path
        && let Ok(lock_json) = std::fs::read_to_string(&lp)
    {
        cmd.env("VELO_RUNTIME_PRELOAD_LOCK", lock_json);
    }

    apply_standard_hygiene(&mut cmd);

    let status = cmd
        .arg(script_path)
        .status()
        .context("Failed to run Python")?;
    let total_time = start.elapsed();
    let rss_after = crate::common::memory::get_process_rss_bytes().unwrap_or(0);

    // Capture results
    let profile_data = if profile_output.exists() {
        profile::ProfileData::from_file(&profile_output)
            .ok()
            .map(|mut pd| {
                pd.memory_delta_mb =
                    (rss_after.saturating_sub(rss_before) as f64) / (1024.0 * 1024.0);
                pd
            })
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
    // Build base PYTHONPATH
    let current_dir = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
    let final_pythonpath = current_dir.to_string_lossy().to_string();

    // Setup sitecustomize for profiling AND preloading (forced for profile)
    let (_final_pythonpath_env, temp_dir_option) =
        setup_sitecustomize(&final_pythonpath, config, true)?;

    // Profile output path
    let profile_output = if let Some(temp_dir) = &temp_dir_option {
        temp_dir.path().join("profile.json")
    } else {
        anyhow::bail!("Failed to get temporary directory for profile output.");
    };

    // Measure memory and time
    let rss_before = crate::common::memory::get_process_rss_bytes().unwrap_or(0);
    let start = std::time::Instant::now();

    // Run the module
    let mut cmd = Command::new(python);
    let shield = EnvironmentShield::new(config);
    shield.apply(&mut cmd).map_err(anyhow::Error::msg)?;
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

    // RFC-0035/SPEC-0005: Native Preload SSOT Injection
    if let Ok(exe_path) = std::env::current_exe() {
        cmd.env("VELO_RUNTIME_EXE_PATH", exe_path);
    }
    let current_dir = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
    let lock_path = current_dir.join("preload.lock");
    if lock_path.exists()
        && let Ok(lock_json) = std::fs::read_to_string(&lock_path)
    {
        cmd.env("VELO_RUNTIME_PRELOAD_LOCK", lock_json);
    }

    apply_standard_hygiene(&mut cmd);

    cmd.arg("-m").arg(module_name);
    for arg in args {
        cmd.arg(arg);
    }

    let status = cmd.status().context("Failed to run Python module")?;
    let total_time = start.elapsed();
    let rss_after = crate::common::memory::get_process_rss_bytes().unwrap_or(0);

    // Capture results
    let profile_data = if profile_output.exists() {
        profile::ProfileData::from_file(&profile_output)
            .ok()
            .map(|mut pd| {
                pd.memory_delta_mb =
                    (rss_after.saturating_sub(rss_before) as f64) / (1024.0 * 1024.0);
                pd
            })
    } else {
        None
    };

    Ok((status, total_time, profile_data))
}
