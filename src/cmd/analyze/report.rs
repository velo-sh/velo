//! Report generation for `velo analyze` command.
//!
//! Handles JSON report saving and pyproject.toml updates.

use anyhow::{Context, Result};
use std::path::Path;

use super::display::colors;
use crate::profile::ProfileData;

/// Save JSON report to file
pub fn save_json_report(profile: &ProfileData, output_path: &Path) -> Result<()> {
    let json = serde_json::to_string_pretty(&profile.import_times)
        .context("Failed to serialize profile data")?;
    std::fs::write(output_path, json).context("Failed to write report file")?;
    Ok(())
}

/// Update pyproject.toml with preload configuration
pub fn update_pyproject_toml(
    project_dir: &Path,
    profile: &ProfileData,
    threshold_ms: u64,
) -> Result<()> {
    let pyproject_path = project_dir.join("pyproject.toml");

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
