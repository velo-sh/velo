//! Handle 'velo analyze' command
//!
//! Analyzes Python project import times and suggests optimizations.
//! Uses runtime profiling (not hardcoded framework lists) per RFC-0004.

use anyhow::{Context, Result};
use std::path::{Path, PathBuf};
use std::process::Command;

use crate::profile::{ProfileData, SITECUSTOMIZE_PY, get_optimization_suggestions};
use crate::python;

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
}

impl Default for AnalyzeArgs {
    fn default() -> Self {
        Self {
            file: None,
            output: None,
            suggest_preload: false,
            fix: false,
            slow_threshold_ms: 100,
        }
    }
}

/// Configuration from pyproject.toml [tool.velo] section
#[derive(Debug, Clone, Default)]
pub struct VeloConfig {
    /// Modules to preload
    pub preload: Vec<String>,
    /// Custom slow threshold in ms
    pub slow_threshold_ms: Option<u64>,
}

impl VeloConfig {
    /// Read [tool.velo] configuration from pyproject.toml
    pub fn from_project(project_dir: &Path) -> Option<Self> {
        let pyproject_path = project_dir.join("pyproject.toml");
        if !pyproject_path.exists() {
            return None;
        }

        let content = std::fs::read_to_string(&pyproject_path).ok()?;
        Self::parse_toml(&content)
    }

    /// Parse [tool.velo] section from TOML content
    fn parse_toml(content: &str) -> Option<Self> {
        // Simple TOML parsing for [tool.velo] section
        // We avoid adding a full TOML parser dependency
        let mut in_tool_velo = false;
        let mut config = VeloConfig::default();

        for line in content.lines() {
            let trimmed = line.trim();

            // Check for section headers
            if trimmed.starts_with('[') {
                in_tool_velo = trimmed == "[tool.velo]";
                continue;
            }

            if !in_tool_velo {
                continue;
            }

            // Parse key = value pairs
            if let Some((key, value)) = trimmed.split_once('=') {
                let key = key.trim();
                let value = value.trim();

                match key {
                    "preload" => {
                        // Parse array: ["mod1", "mod2"]
                        config.preload = parse_string_array(value);
                    }
                    "slow_threshold_ms" => {
                        config.slow_threshold_ms = value.parse().ok();
                    }
                    _ => {}
                }
            }
        }

        if config.preload.is_empty() && config.slow_threshold_ms.is_none() {
            None
        } else {
            Some(config)
        }
    }
}

/// Parse a TOML-like string array: ["a", "b", "c"]
fn parse_string_array(s: &str) -> Vec<String> {
    let s = s.trim();
    if !s.starts_with('[') || !s.ends_with(']') {
        return vec![];
    }

    let inner = &s[1..s.len() - 1];
    inner
        .split(',')
        .map(|item| item.trim().trim_matches('"').trim_matches('\'').to_string())
        .filter(|s| !s.is_empty())
        .collect()
}

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

    // Detect Python
    let python_path = python::detect_python(&project_dir)?;

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

/// Parse command-line arguments
fn parse_args(args: &[String]) -> Result<AnalyzeArgs> {
    let mut parsed = AnalyzeArgs::default();
    let mut i = 2; // Skip "velo" and "analyze"

    while i < args.len() {
        match args[i].as_str() {
            "--output" | "-o" => {
                i += 1;
                if i >= args.len() {
                    anyhow::bail!("--output requires a path argument");
                }
                parsed.output = Some(PathBuf::from(&args[i]));
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
            "-h" | "--help" => {
                print_analyze_help();
                std::process::exit(0);
            }
            arg if arg.starts_with('-') => {
                anyhow::bail!("Unknown option: {}", arg);
            }
            _ => {
                parsed.file = Some(PathBuf::from(&args[i]));
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
    --fix                     Auto-update pyproject.toml with preload config
    --output, -o <FILE>       Save JSON report to file
    -h, --help                Print help

EXAMPLES:
    velo analyze                    # Analyze with auto-detected entry point
    velo analyze main.py            # Analyze specific file
    velo analyze --slow-threshold-ms 50  # Custom threshold
    velo analyze --fix              # Update pyproject.toml automatically
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
    fn test_parse_args_unknown_option() {
        let args = vec![
            "velo".to_string(),
            "analyze".to_string(),
            "--unknown".to_string(),
        ];
        let result = parse_args(&args);
        assert!(result.is_err());
        assert!(result.unwrap_err().to_string().contains("Unknown option"));
    }

    #[test]
    fn test_parse_string_array() {
        assert_eq!(
            parse_string_array(r#"["numpy", "pandas"]"#),
            vec!["numpy", "pandas"]
        );
        assert_eq!(parse_string_array(r#"["single"]"#), vec!["single"]);
        assert_eq!(parse_string_array("[]"), Vec::<String>::new());
        assert_eq!(parse_string_array("invalid"), Vec::<String>::new());
    }

    #[test]
    fn test_velo_config_parse_toml() {
        let content = r#"
[project]
name = "test"

[tool.velo]
preload = ["numpy", "pandas"]
slow_threshold_ms = 50
"#;
        let config = VeloConfig::parse_toml(content).unwrap();
        assert_eq!(config.preload, vec!["numpy", "pandas"]);
        assert_eq!(config.slow_threshold_ms, Some(50));
    }

    #[test]
    fn test_velo_config_parse_toml_no_section() {
        let content = r#"
[project]
name = "test"
"#;
        let config = VeloConfig::parse_toml(content);
        assert!(config.is_none());
    }

    #[test]
    fn test_velo_config_parse_toml_empty_preload() {
        let content = r#"
[tool.velo]
slow_threshold_ms = 75
"#;
        let config = VeloConfig::parse_toml(content).unwrap();
        assert!(config.preload.is_empty());
        assert_eq!(config.slow_threshold_ms, Some(75));
    }
}
