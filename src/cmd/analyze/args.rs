//! Argument parsing for `velo analyze` command.

use anyhow::{Context, Result};
use std::path::PathBuf;

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
    /// Dry-run mode: don't execute code, just show what would be done
    pub dry_run: bool,
    /// Skip confirmation prompt
    pub yes: bool,
}

impl Default for AnalyzeArgs {
    fn default() -> Self {
        Self {
            file: None,
            output: None,
            suggest_preload: false,
            fix: false,
            slow_threshold_ms: 100,
            dry_run: false,
            yes: false,
        }
    }
}

/// Validate a path argument for security issues
/// DEF-4.0-002: Reject special paths like /dev/null
/// DEF-4.0-003: Reject paths with null bytes
pub fn validate_path(path: &str, arg_name: &str) -> Result<PathBuf> {
    // DEF-4.0-003: Check for null bytes
    if path.contains('\0') {
        anyhow::bail!("{} contains invalid null byte: {:?}", arg_name, path);
    }

    // DEF-4.0-002: Check for special device paths
    let path_buf = PathBuf::from(path);
    let path_str = path_buf.to_string_lossy();

    // Block device paths on Unix
    if path_str.starts_with("/dev/") {
        anyhow::bail!("{} cannot be a device path: {}", arg_name, path_str);
    }

    // Block empty paths
    if path.is_empty() {
        anyhow::bail!("{} cannot be empty", arg_name);
    }

    Ok(path_buf)
}

/// Parse command-line arguments
pub fn parse_args(args: &[String]) -> Result<AnalyzeArgs> {
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
            "--dry-run" => {
                parsed.dry_run = true;
            }
            "--yes" | "-y" => {
                parsed.yes = true;
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
                parsed.file = Some(validate_path(&args[i], "file")?);
            }
        }
        i += 1;
    }

    Ok(parsed)
}

/// Print help message for analyze command
pub fn print_analyze_help() {
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
    --dry-run                 Don't execute code, just show what would be done
    --yes, -y                 Skip confirmation prompt
    -h, --help                Print help

EXAMPLES:
    velo analyze                    # Analyze with auto-detected entry point
    velo analyze main.py            # Analyze specific file
    velo analyze --slow-threshold-ms 50  # Custom threshold
    velo analyze --fix              # Update pyproject.toml automatically
    velo analyze --dry-run          # Preview without executing

NOTE:
    ⚠️  The script WILL BE EXECUTED to measure real import times.
    Only run this on code you trust.
"#
    );
}

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
        assert!(!parsed.dry_run);
        assert!(!parsed.yes);
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
    fn test_parse_args_dry_run() {
        let args = vec![
            "velo".to_string(),
            "analyze".to_string(),
            "--dry-run".to_string(),
        ];
        let parsed = parse_args(&args).unwrap();
        assert!(parsed.dry_run);
    }

    #[test]
    fn test_parse_args_yes_flag() {
        let args = vec![
            "velo".to_string(),
            "analyze".to_string(),
            "--yes".to_string(),
        ];
        let parsed = parse_args(&args).unwrap();
        assert!(parsed.yes);
    }

    #[test]
    fn test_parse_args_y_flag() {
        let args = vec!["velo".to_string(), "analyze".to_string(), "-y".to_string()];
        let parsed = parse_args(&args).unwrap();
        assert!(parsed.yes);
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
}
