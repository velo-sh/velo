//! Handle 'velo analyze' command
//!
//! Analyzes Python project import times and suggests optimizations.
//! Uses runtime profiling (not hardcoded framework lists) per RFC-0004.

mod args;
mod config;
mod display;
mod report;

use anyhow::{Context, Result};
use std::io::{self, Write};
use std::path::{Path, PathBuf};
use std::process::Command;

use crate::profile::{ProfileData, SITECUSTOMIZE_PY};
use crate::python;

// Re-export public types
pub use args::{AnalyzeArgs, parse_args, validate_path};
pub use config::{VeloConfig, parse_string_array};
pub use display::{colors, display_analysis, display_preload_suggestions, truncate_str};
pub use report::{save_json_report, update_pyproject_toml};

/// Check if running in an interactive terminal
fn is_interactive() -> bool {
    atty::is(atty::Stream::Stdin) && atty::is(atty::Stream::Stderr)
}

/// Read confirmation from user (y/Y = yes, anything else = no)
fn read_confirmation() -> bool {
    io::stderr().flush().ok();
    let mut input = String::new();
    if io::stdin().read_line(&mut input).is_ok() {
        input.trim().eq_ignore_ascii_case("y")
    } else {
        false
    }
}

/// Handle 'velo analyze' command
pub fn cmd_analyze(args: &[String]) -> Result<()> {
    let parsed = parse_args(args)?;

    // Determine project directory
    let project_dir = std::env::current_dir().unwrap_or_else(|_| Path::new(".").to_path_buf());

    // Read existing [tool.velo] config
    let existing_config = VeloConfig::from_project(&project_dir);

    // Determine effective threshold (CLI > config > default)
    let effective_threshold = if parsed.slow_threshold_ms != 100 {
        parsed.slow_threshold_ms // CLI takes priority
    } else if let Some(ref cfg) = existing_config {
        cfg.slow_threshold_ms.unwrap_or(100)
    } else {
        100
    };

    // Show existing config if present
    if let Some(ref cfg) = existing_config {
        eprintln!(
            "{}📦 Found [tool.velo] config:{}",
            colors::CYAN,
            colors::RESET
        );
        if !cfg.preload.is_empty() {
            eprintln!("   preload = {:?}", cfg.preload);
        }
        if let Some(t) = cfg.slow_threshold_ms {
            eprintln!("   slow_threshold_ms = {}", t);
        }
        eprintln!();
    }

    // Find entry point script
    let script = match &parsed.file {
        Some(f) => f.clone(),
        None => find_entry_point(&project_dir)?,
    };

    // Dry-run mode: just show what would be done
    if parsed.dry_run {
        eprintln!(
            "{}🔍 Dry-run mode: would analyze {}{}",
            colors::CYAN,
            script.display(),
            colors::RESET
        );
        eprintln!("   Threshold: {}ms", effective_threshold);
        eprintln!("   Suggest preload: {}", parsed.suggest_preload);
        eprintln!("   Auto-fix: {}", parsed.fix);
        return Ok(());
    }

    // Consent prompt for code execution (Phase 4.1 security)
    if !parsed.yes && is_interactive() {
        eprintln!(
            "{}⚠️  WARNING: This will execute your Python code to measure import times.{}",
            colors::YELLOW,
            colors::RESET
        );
        eprint!("Continue? [y/N]: ");
        if !read_confirmation() {
            eprintln!("Aborted.");
            return Ok(());
        }
    }

    // Detect Python
    let python_path = python::detect_python(&project_dir)?;

    // Security notice
    eprintln!(
        "{}⚠️  Note: Script will be executed to measure import times{}",
        colors::YELLOW,
        colors::RESET
    );

    // Run with profiling
    eprintln!(
        "{}📊 Analyzing imports for {}...{}",
        colors::CYAN,
        script.display(),
        colors::RESET
    );

    let profile_data = run_with_profile(&python_path, &script, &project_dir)?;

    // Display results
    display_analysis(&profile_data, effective_threshold);

    // Show suggestions if requested
    if parsed.suggest_preload {
        display_preload_suggestions(&profile_data, effective_threshold, existing_config.as_ref());
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
fn run_with_profile(python_path: &Path, script: &Path, project_dir: &Path) -> Result<ProfileData> {
    // Create temp directory for sitecustomize.py
    let temp_dir = tempfile::tempdir().context("Failed to create temp directory")?;
    let sitecustomize_path = temp_dir.path().join("sitecustomize.py");
    let profile_output_path = temp_dir.path().join("velo_profile.json");

    // Write sitecustomize.py
    std::fs::write(&sitecustomize_path, SITECUSTOMIZE_PY)
        .context("Failed to write sitecustomize.py")?;

    // Build PYTHONPATH with sitecustomize directory first
    let pythonpath = temp_dir.path().to_string_lossy().to_string();

    // Run script with profiling enabled
    let output = Command::new(python_path)
        .arg(script)
        .current_dir(project_dir)
        .env("PYTHONPATH", &pythonpath)
        .env(
            "VELO_PROFILE_OUTPUT",
            profile_output_path.to_string_lossy().as_ref(),
        )
        .output()
        .context("Failed to run Python script")?;

    // Check for script errors (but don't fail - we still want profile data)
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        if !stderr.is_empty() {
            eprintln!(
                "{}⚠️ Script had errors (analysis may be incomplete):{}",
                colors::YELLOW,
                colors::RESET
            );
            eprintln!("{}{}{}", colors::DIM, stderr.trim(), colors::RESET);
        }
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

// Note: Tests are in individual submodule files (args.rs, config.rs, display.rs)
