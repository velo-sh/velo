//! Python environment detection and setup
//!
//! This module handles:
//! - Detecting the Python interpreter (venv, VELO_PYTHON, system)
//! - Detecting site-packages paths
//! - Capturing sys.path from Python
//! - Setting up the Python environment with caching

use anyhow::{Context, Result};
use std::path::Path;
use std::process::Command;

use crate::cache::EnvCache;

/// Detect the project's Python interpreter.
/// Priority:
/// 1. .venv/bin/python (uv/virtualenv)
/// 2. VELO_PYTHON environment variable
/// 3. System python3
#[allow(clippy::collapsible_if)]
pub fn detect_python(project_dir: &Path) -> Result<std::path::PathBuf> {
    // 1. Check for .venv/bin/python
    let venv_python = project_dir.join(".venv/bin/python");
    if venv_python.exists() {
        return Ok(venv_python);
    }

    // 2. Check VELO_PYTHON env var
    if let Ok(python) = std::env::var("VELO_PYTHON") {
        let path = std::path::PathBuf::from(&python);
        if path.exists() {
            return Ok(path);
        }
    }

    // 3. Fall back to system python3
    // First check if python3 exists in PATH
    if let Ok(output) = Command::new("which").arg("python3").output() {
        if output.status.success() {
            let path = String::from_utf8_lossy(&output.stdout).trim().to_string();
            return Ok(std::path::PathBuf::from(path));
        }
    }

    anyhow::bail!("No Python interpreter found. Please create a .venv or set VELO_PYTHON")
}

/// Detect .venv/lib/python*/site-packages
pub fn detect_venv_site_packages(project_dir: &Path) -> Option<String> {
    let venv_lib = project_dir.join(".venv/lib");
    if !venv_lib.exists() {
        return None;
    }

    if let Ok(entries) = std::fs::read_dir(&venv_lib) {
        for entry in entries.flatten() {
            let name = entry.file_name();
            let name_str = name.to_string_lossy();
            if name_str.starts_with("python3") {
                let site_packages = entry.path().join("site-packages");
                if site_packages.exists() {
                    return Some(site_packages.to_string_lossy().to_string());
                }
            }
        }
    }

    None
}

/// Capture sys.path from Python and cache it.
pub fn capture_sys_path(python: &Path) -> Result<Vec<String>> {
    let output = Command::new(python)
        .args(["-c", "import sys; print('\\n'.join(sys.path))"])
        .output()
        .context("Failed to run Python to capture sys.path")?;

    if !output.status.success() {
        anyhow::bail!("Python failed to report sys.path");
    }

    let paths: Vec<String> = String::from_utf8_lossy(&output.stdout)
        .lines()
        .filter(|s| !s.is_empty())
        .map(|s| s.to_string())
        .collect();

    Ok(paths)
}

/// Setup Python environment, potentially using cache.
/// Returns (pythonpath, needs_capture) - if needs_capture is true, caller should
/// capture sys.path after script runs for next time.
#[allow(clippy::collapsible_if)]
pub fn setup_python_env(project_dir: &Path, _python: &Path) -> (Option<String>, bool) {
    // First, check if we have a valid cache
    if let Some(fingerprint) = EnvCache::compute_fingerprint(project_dir) {
        if let Some(cache) = EnvCache::load(project_dir, &fingerprint) {
            // Cache hit! Use cached PYTHONPATH
            if !cache.sys_path.is_empty() {
                let pythonpath = cache.sys_path.join(":");
                return (Some(pythonpath), false);
            }
        }
    }

    // No cache - try to detect venv site-packages at least
    if let Some(site_packages) = detect_venv_site_packages(project_dir) {
        // We have site-packages but no full cache - use it but request capture
        return (Some(site_packages), true);
    }

    // No venv detected - run without PYTHONPATH, request capture
    (None, true)
}
