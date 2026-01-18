//! `velo test` command - Zygote-accelerated test execution
//!
//! RFC-0028: pytest-velo Plugin (Phase 13)
//!
//! This command wraps pytest with Zygote acceleration for faster test execution.
//! It passes through to pytest with `--velo` flag for COW fork optimization.

use anyhow::{Context, Result};
use clap::{Arg, ArgAction, Command};
use std::process::{Command as ProcessCommand, Stdio};

/// Build the clap Command for `velo test`
fn build_cli() -> Command {
    Command::new("test")
        .about("Run tests with Zygote acceleration (RFC-0028)")
        .arg(
            Arg::new("path")
                .help("Test path (default: tests/)")
                .default_value("tests/")
                .index(1),
        )
        .arg(
            Arg::new("workers")
                .short('n')
                .long("workers")
                .help("Number of parallel workers")
                .value_name("N")
                .default_value("1"),
        )
        .arg(
            Arg::new("tier")
                .long("tier")
                .help("Filter by tier marker (e.g., tier0, tier1)")
                .value_name("TIER"),
        )
        .arg(
            Arg::new("preload")
                .long("preload")
                .help("Comma-separated modules to preload in Zygote")
                .value_name("MODULES"),
        )
        .arg(
            Arg::new("zygote")
                .long("zygote")
                .help("Enable Zygote acceleration (requires pytest-velo plugin)")
                .action(ArgAction::SetTrue),
        )
        .arg(
            Arg::new("cov")
                .long("cov")
                .help("Enable coverage measurement (passes --cov to pytest)")
                .value_name("PATH")
                .num_args(0..=1)
                .default_missing_value("."),
        )
        .arg(
            Arg::new("verbose")
                .short('v')
                .long("verbose")
                .help("Verbose output")
                .action(ArgAction::SetTrue),
        )
        .arg(
            Arg::new("pytest_args")
                .help("Additional pytest arguments")
                .last(true)
                .num_args(0..),
        )
}

/// Main entry point for `velo test`
pub fn cmd_vtest(args: &[String]) -> Result<()> {
    let cli = build_cli();
    let matches = cli.try_get_matches_from(&args[1..])?;

    let test_path = matches.get_one::<String>("path").unwrap();
    let workers: u32 = matches
        .get_one::<String>("workers")
        .unwrap()
        .parse()
        .context("Invalid worker count")?;
    let tier = matches.get_one::<String>("tier");
    let preload = matches.get_one::<String>("preload");
    let use_zygote = matches.get_flag("zygote");
    let cov_path = matches.get_one::<String>("cov");
    let verbose = matches.get_flag("verbose");
    let extra_args: Vec<&String> = matches
        .get_many::<String>("pytest_args")
        .map(|v| v.collect())
        .unwrap_or_default();

    // Use uv run pytest which handles Python environment automatically
    let mut cmd = ProcessCommand::new("uv");
    cmd.arg("run").arg("pytest");

    // Ensure pytest_velo module is discoverable
    // This is needed when running from a different directory (e.g., temp dir in E2E tests)
    if let Ok(exe_path) = std::env::current_exe()
        && let Some(project_root) = exe_path
            .parent()
            .and_then(|p| p.parent())
            .and_then(|p| p.parent())
    {
        let pythonpath = std::env::var("PYTHONPATH")
            .map(|p| format!("{}:{}", project_root.display(), p))
            .unwrap_or_else(|_| project_root.display().to_string());
        cmd.env("PYTHONPATH", pythonpath);
    }

    // Add test path
    cmd.arg(test_path);

    // Add Zygote flags if enabled
    if use_zygote {
        cmd.arg("-p").arg("pytest_velo.plugin"); // Force load plugin
        cmd.arg("--velo");
        if let Some(modules) = preload {
            cmd.arg(format!("--velo-preload={}", modules));
        }
    }

    // Add tier marker filter
    if let Some(t) = tier {
        cmd.arg("-m").arg(t);
    }

    // Add verbosity
    if verbose {
        cmd.arg("-v");
    }

    // Add coverage if requested
    if let Some(path) = cov_path {
        cmd.arg(format!("--cov={}", path));
        cmd.arg("--cov-report=term-missing");
    }

    // Parallel workers: pass -n to pytest
    // Phase 14: --workers + --zygote now supported (xdist + Zygote acceleration)
    if workers > 1 {
        cmd.arg("-n").arg(workers.to_string());
        if use_zygote {
            log::info!(
                "Running with {} xdist workers + Zygote acceleration",
                workers
            );
        }
    }

    // Pass through extra pytest args
    for arg in extra_args {
        cmd.arg(arg);
    }

    // Execute pytest
    cmd.stdin(Stdio::inherit())
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit());

    let status = cmd.status().context("Failed to execute pytest")?;

    // Exit with pytest's exit code
    std::process::exit(status.code().unwrap_or(1));
}
