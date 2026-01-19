//! Test execution module - Zygote-accelerated test coordination
//!
//! RFC-0028: pytest-velo Plugin (Phase 13)
//!
//! This module provides the Rust-side coordination for running tests
//! via Zygote COW forks for maximum performance.

pub mod coordinator;

pub use coordinator::VtestCoordinator;

use anyhow::{Context, Result};
use std::path::Path;
use std::process::{Command, Stdio};

/// Phase 2: Forensic Collection of NodeIDs via pytest --collect-only
pub fn collect_nodeids(
    test_path: &Path,
    tier: Option<&String>,
    extra_args: &[&String],
) -> Result<Vec<String>> {
    let mut cmd = Command::new("uv");
    cmd.arg("run").arg("pytest");
    cmd.arg("-o").arg("addopts="); // RFC-0017: Override addopts to ensure machine-readable output
    cmd.arg(test_path);
    cmd.arg("--collect-only").arg("-q");

    // Ensure local modules are discoverable during collection
    if let Ok(cwd) = std::env::current_dir() {
        let pythonpath = std::env::var("PYTHONPATH")
            .map(|p| format!("{}:{}", cwd.display(), p))
            .unwrap_or_else(|_| cwd.display().to_string());
        cmd.env("PYTHONPATH", pythonpath);
    }

    if let Some(t) = tier {
        cmd.arg("-m").arg(t);
    }

    for arg in extra_args {
        cmd.arg(arg);
    }

    let output = cmd
        .stderr(Stdio::null()) // Hide collection warnings
        .output()
        .context("Failed to run pytest collection")?;

    if !output.status.success() {
        let err = String::from_utf8_lossy(&output.stdout);
        anyhow::bail!("Collection failed: {}", err);
    }

    let stdout = String::from_utf8_lossy(&output.stdout);
    let mut nodeids = Vec::new();

    for line in stdout.lines() {
        let line = line.trim();
        // pytest -q output lines with '::' are likely NodeIDs
        if line.contains("::") && !line.is_empty() {
            nodeids.push(line.to_string());
        }
    }

    Ok(nodeids)
}
