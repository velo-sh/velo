//! Python environment fingerprinting and setup
//!
//! This module handles:
//! - Detecting the Python interpreter (venv, VELO_PYTHON, system)
//! - Detecting site-packages paths
//! - Capturing sys.path from Python
//! - Setting up the Python environment with caching

use anyhow::{Context, Result};
use std::path::{Path, PathBuf};
use std::process::Command;

use crate::cache::EnvCache;

/// Check if a Python interpreter path is "hermetic" (resides within a managed environment).
pub fn is_hermetic_check(python_path: &Path) -> bool {
    let path_str = python_path.to_string_lossy();

    // 1. Check if it lives inside a .venv within the current directory
    if let Ok(cwd) = std::env::current_dir()
        && path_str.starts_with(&cwd.to_string_lossy().to_string())
        && path_str.contains("/.venv/")
    {
        return true;
    }

    // 2. Check for UV hermetic paths (default for uv managed pythons)
    if path_str.contains("/.local/share/uv/python/") {
        return true;
    }

    // 3. Check for specific common UV cache locations on Linux/macOS
    if path_str.contains("/Library/Application Support/uv/python/")
        || path_str.contains("/.cache/uv/python/")
    {
        return true;
    }

    false
}

/// Detect the project's Python interpreter.
/// Priority:
/// 1. VELO_PYTHON environment variable (explicit override for testing/CI)
/// 2. .venv/bin/python (local uv/virtualenv)
/// 3. VIRTUAL_ENV environment variable (activated venv)
/// 4. System python3
pub fn detect_python(project_dir: &Path) -> Result<PathBuf> {
    // 1. Check VELO_PYTHON env var FIRST (for test mocking and explicit overrides)
    if let Ok(python_path_str) = std::env::var("VELO_PYTHON") {
        let path = PathBuf::from(&python_path_str);
        if path.exists() {
            return Ok(path);
        }
        // If VELO_PYTHON is set but doesn't exist, log and continue
        eprintln!(
            "[WARN] VELO_PYTHON={} does not exist, falling back",
            python_path_str
        );
    }

    // 2. Check for project-local venv names
    for name in [".venv", "venv", ".env", "env"] {
        let path = project_dir.join(name);
        let python = if cfg!(windows) {
            path.join("Scripts/python.exe")
        } else {
            path.join("bin/python")
        };
        if python.exists() {
            return Ok(python);
        }
    }

    // 3. Check VIRTUAL_ENV env var (only if project venv not found)
    if let Ok(venv) = std::env::var("VIRTUAL_ENV")
        && !venv.trim().is_empty()
    {
        let path = PathBuf::from(venv);
        let python = if cfg!(windows) {
            path.join("Scripts/python.exe")
        } else {
            path.join("bin/python")
        };
        if python.exists() {
            return Ok(python);
        }
    }

    // 4. Fall back to system python3
    // Use 'which' to find python3 in PATH
    if let Ok(output) = Command::new("which").arg("python3").output()
        && output.status.success()
    {
        let path_str = String::from_utf8_lossy(&output.stdout).trim().to_string();
        let path = PathBuf::from(path_str);

        // SENTINEL: Check for system Python contamination
        if !is_hermetic_check(&path) {
            let strict = std::env::var("VELO_STRICT_SSOT").unwrap_or_else(|_| "0".into()) == "1";
            let msg = format!(
                "🚨 [SENTINEL] System Python Contamination Detected: {}\n\
                 Velo is currently configured to use a non-hermetic system Python.\n\
                 This causes environment drift and ModuleNotFound errors.\n\
                 FIX: Run 'uv sync' or 'source .venv/bin/activate'",
                path.display()
            );

            if strict {
                anyhow::bail!(msg);
            } else {
                eprintln!("[WARN] {}", msg);
            }
        }

        return Ok(path);
    }

    anyhow::bail!("No Python interpreter found. Please create a .venv or set VELO_PYTHON")
}

/// Detect site-packages path relative to the interpreter path
pub fn detect_site_packages(python_path: &Path) -> Option<String> {
    // Derive venv root from python path (python is in venv/bin/python or venv/Scripts/python.exe)
    // Derive venv root from python path (python is in venv/bin/python or venv/Scripts/python.exe)
    // On both Windows and Unix, we expect the bin/Scripts to be one level below the root.
    let venv_root = python_path.parent()?.parent()?;

    let lib_dir = venv_root.join("lib");
    if !lib_dir.exists() {
        return None;
    }

    if let Ok(entries) = std::fs::read_dir(&lib_dir) {
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

    // No cache - try to detect site-packages from the actual python path
    if let Some(site_packages) = detect_site_packages(_python) {
        // We have site-packages but no full cache - use it but request capture
        return (Some(site_packages), true);
    }

    // No venv detected - run without PYTHONPATH, request capture
    (None, true)
}
