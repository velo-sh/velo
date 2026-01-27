//! `velo test` command - Zygote-accelerated test execution
//!
//! RFC-0028: pytest-velo Plugin (Phase 13)
//!
//! This command wraps pytest with Zygote acceleration for faster test execution.
//! It passes through to pytest with `--velo` flag for COW fork optimization.

use anyhow::{Context, Result};
use clap::{Arg, ArgAction, Command};
use std::path::Path;
use std::process::{Command as ProcessCommand, Stdio};

/// Build the clap Command for `velo test`
fn build_cli() -> Command {
    Command::new("test")
        .about("Run tests with Zygote acceleration (RFC-0028)")
        .arg(
            Arg::new("path")
                .help("Test path (default: tests/)")
                .default_value("tests/"),
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
            Arg::new("strict_compat")
                .long("strict-compat")
                .help("Mimic vanilla pytest isolation (disable TMPDIR/socket isolation)")
                .action(ArgAction::SetTrue),
        )
        .arg(
            Arg::new("pytest_args")
                .help("Additional pytest arguments")
                .last(true)
                .num_args(0..),
        )
        .arg(
            Arg::new("vibe")
                .long("vibe")
                .help("Enable Vibe Coding mode for real-time test feedback [RFC-0029]")
                .action(ArgAction::SetTrue),
        )
        .arg(
            Arg::new("live")
                .long("live")
                .help("Alias for --vibe")
                .action(ArgAction::SetTrue),
        )
}

/// Run tests in Vibe Coding mode (RFC-0029)
///
/// This starts the VibeEngine watching the test path for instant re-execution.
#[tokio::main]
async fn run_vibe_test_mode(test_path: &Path) -> Result<()> {
    use colored::Colorize;

    println!("{}", "🏛️  Vibe Engine (Test Mode) Activated".green().bold());
    println!("Architecture Directive: Phase 8 (Vibe-Coding)");
    println!("Watching: {}", test_path.display());
    println!();
    println!("Tests will re-run automatically on file changes.");
    println!("Press Ctrl+C to stop.");

    // For test mode, we use a simpler file watcher approach
    // that triggers pytest on any .py file change in the test directory
    let target = test_path.to_path_buf();
    let gateway_addr = "127.0.0.1:8080";

    let engine = velo_serve::v_live::engine::VibeEngine::new(target, gateway_addr);
    engine.start().await?;

    Ok(())
}

/// Main entry point for `velo test`
pub fn cmd_vtest(args: &[String]) -> Result<()> {
    let cli = build_cli();
    let matches = cli.try_get_matches_from(&args[1..])?;

    let test_path_str = matches.get_one::<String>("path").unwrap();
    let test_path = Path::new(test_path_str);
    let workers: usize = matches
        .get_one::<String>("workers")
        .unwrap()
        .parse()
        .context("Invalid worker count")?;

    let use_zygote = matches.get_flag("zygote");
    let use_vibe = matches.get_flag("vibe") || matches.get_flag("live");
    let verbose = matches.get_flag("verbose");
    let tier = matches.get_one::<String>("tier");
    let preload = matches.get_one::<String>("preload");

    let extra_args_refs: Vec<&String> = matches
        .get_many::<String>("pytest_args")
        .map(|v| v.collect())
        .unwrap_or_default();

    // RFC-0029: Vibe mode for real-time test feedback
    if use_vibe {
        return run_vibe_test_mode(test_path);
    }

    // vtest Sovereignty: If Zygote or native orchestration is requested,
    // we use the NodeID dispatch loop instead of coarse-grained subprocesses.
    if use_zygote {
        log::info!("🚀 Starting vtest native orchestration (RFC-0028/Phase 13)...");
        log::debug!("vtest PID: {}", std::process::id());

        // RFC-0028: Get coverage path if specified
        let cov_path = matches.get_one::<String>("cov").cloned();

        // 1. NodeID Discovery (Phase 2)
        let nodeids = crate::collect_nodeids(test_path, tier, &extra_args_refs)
            .context("Failed to collect test NodeIDs")?;

        log::info!("📊 Discovered {} test cases.", nodeids.len());

        if nodeids.is_empty() {
            log::warn!(
                "⚠️ No tests discovered at path: {} (tier: {:?})",
                test_path_str,
                tier
            );
            return Ok(());
        }

        // 2. Orchestration Initialization (Phase 1)
        let config = velo_core::config::VeloConfig::from_pyproject_toml();
        let mut coordinator = crate::VtestCoordinator::new(&config, workers, cov_path)
            .context("Failed to initialize crate::VtestCoordinator")?;

        // Lifecycle: Zygote pre-flighting (Phase 3)
        let preload_list: Vec<&str> = if let Some(p) = preload {
            p.split(',').map(|s| s.trim()).collect()
        } else {
            Vec::new()
        };

        coordinator.ensure_zygote(&preload_list)?;

        // 3. Dispatch & Execution Loop (Phase 3)
        for nodeid in nodeids {
            coordinator.add_test(nodeid)?;
        }

        let report = match coordinator.run_all() {
            Ok(r) => r,
            Err(e) => {
                log::error!("🔥 Fatal error during test orchestration: {:?}", e);
                std::process::exit(1);
            }
        };

        // 4. Reporting (Phase 4)
        if verbose || !report.all_passed() {
            for res in &report.results {
                if !res.passed {
                    log::error!("❌ FAILED: {}", res.test_id);
                    if let Some(ref err) = res.stderr {
                        eprintln!("{}", err);
                    }
                } else if verbose {
                    log::info!("✅ PASSED: {}", res.test_id);
                }
            }
        }

        println!("\nTest Summary:");
        println!("  Total:   {}", report.total);
        println!("  Passed:  {}", report.passed);
        println!("  Failed:  {}", report.failed);
        println!("  Time:    {}ms", report.total_duration_ms);

        if !report.all_passed() {
            std::process::exit(1);
        }

        return Ok(());
    }

    // Fallback: Legacy/Standard pytest path (INV-001 notes we should gradually deprecate this)
    let mut cmd = ProcessCommand::new("uv");
    cmd.arg("run").arg("pytest");

    // Ensure pytest_velo module is discoverable
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

    cmd.arg(test_path_str);

    if workers > 1 {
        cmd.arg("-n").arg(workers.to_string());
    }

    if verbose {
        cmd.arg("-v");
    }

    for arg in extra_args_refs {
        cmd.arg(arg);
    }

    cmd.stdin(Stdio::inherit())
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit());

    let status = cmd.status().context("Failed to execute pytest")?;
    std::process::exit(status.code().unwrap_or(1));
}
