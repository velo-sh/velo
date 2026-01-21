//! CLI module for Velo
//!
//! This module handles:
//! - Command-line argument parsing
//! - Command dispatch (run, info, zygote, serve)
//! - Help and version display

use anyhow::Result;
use colored::Colorize;

use crate::cmd;

pub const USAGE: &str = "\
velo - The high-performance Python runtime for the AI era

USAGE:
    velo run [OPTIONS] <script.py>
    velo serve <app> [OPTIONS]
    velo test [path] [OPTIONS]       # Zygote-accelerated testing (RFC-0028)
    velo python <args>               # Managed Python (RFC-0018)
    velo analyze [OPTIONS] [file.py]
    velo bundle <inspect|build> [OPTIONS]
    velo zygote <start|stop|status|auto-config>
    velo debug <zygote> [OPTIONS]
    velo info
    velo audit
    velo graph <generate|verify> [OPTIONS]

COMMANDS:
    run      Run a Python script
    serve    Serve a Python ASGI/WSGI application
    test     Run tests with Zygote acceleration (RFC-0028)
    python   Run Python via managed uv toolchain
    analyze  Analyze import times and suggest optimizations
    bundle   Bundle management (inspect, build)
    zygote   Manage Zygote pre-warming daemon
    debug    Internal debugging tools (RFC-0020)
    info     Show environment information
    audit    Verify architectural governance (audit SSOT/Naming/Perf)

RUN OPTIONS:
    --zygote   Use Zygote for fast startup (auto-starts if needed)
    --profile  Show detailed startup timing breakdown
    --shm <PATH>  Map .safetensors into shared memory (Memory Gravity)

SERVE OPTIONS:
    --host <HOST>    Bind host (default: 127.0.0.1)
    --port <PORT>    Bind port (default: 8000)
    --workers <N>    Number of workers (default: 1)
    --reload         Enable hot reload
    --no-zygote      Disable Zygote integration

ANALYZE OPTIONS:
    --slow-threshold-ms <MS>  Threshold for 'slow' imports (default: 100)
    --suggest-preload         Show preload suggestions
    --fix                     Auto-update pyproject.toml with recommendations
    --output <FILE>           Save JSON report to file
    --shm <PATH>              Map .safetensors into shared memory (Memory Gravity)

ZYGOTE SUBCOMMANDS:
    start        Start Zygote daemon
    stop         Stop Zygote daemon
    status       Show Zygote status
    auto-config  Generate preload config from profile data

OPTIONS:
    -h, --help     Print help
    -V, --version  Print version
";

fn suggest_command(target: &str) -> Option<&'static str> {
    const COMMANDS: &[&str] = &[
        "run", "serve", "test", "python", "pip", "analyze", "bench", "bundle", "info", "audit",
        "zygote", "graph",
    ];
    let mut best_match = None;
    let mut min_dist = 2; // MANDATE OBS-001: Max threshold 2

    for &cmd in COMMANDS {
        let dist = strsim::levenshtein(target, cmd);
        if dist > 0 && dist <= min_dist {
            min_dist = dist;
            best_match = Some(cmd);
        }
    }
    best_match
}

/// Main entry point for CLI
pub fn run() -> Result<()> {
    // RFC-0020: Force colors if requested (even when piped/captured)
    // This ensures H-Gov audit signals maintain their ANSI formatting in CI/Logs.
    if std::env::var("CLICOLOR_FORCE").is_ok() || std::env::var("FORCE_COLOR").is_ok() {
        colored::control::set_override(true);
    }

    let args: Vec<String> = std::env::args().collect();

    if args.len() < 2 {
        print!("{}", USAGE);
        std::process::exit(0);
    }

    let result = match args[1].as_str() {
        "-h" | "--help" => {
            print!("{}", USAGE);
            return Ok(());
        }
        "-V" | "--version" => {
            println!(
                "velo {} ({})",
                env!("CARGO_PKG_VERSION"),
                crate::common::constants::BUILD_SCM_HASH
            );
            return Ok(());
        }
        "run" => cmd::cmd_run(&args),
        "serve" => cmd::cmd_serve(&args),
        "test" => cmd::cmd_vtest(&args), // RFC-0028: Zygote-accelerated testing
        "python" => cmd::cmd_python(&args), // RFC-0018: managed Python
        "analyze" => cmd::cmd_analyze(&args),
        "bench" => cmd::cmd_bench(&args),
        "bundle" => cmd::cmd_bundle(&args),
        "info" => cmd::cmd_info(),
        "audit" => cmd::cmd_audit(&args),
        "zygote" => cmd::cmd_zygote(&args),
        "debug" => cmd::cmd_debug(&args),
        "graph" => cmd::cmd_graph(&args),
        "worker-native" => cmd::cmd_worker_native(&args),
        cmd => {
            eprintln!("{}: unknown command '{}'", "error".red().bold(), cmd);
            if let Some(suggestion) = suggest_command(cmd) {
                eprintln!(
                    "   {} did you mean '{}'?",
                    "tip:".yellow(),
                    suggestion.cyan()
                );
            }
            eprintln!("\n{}", USAGE);
            std::process::exit(1);
        }
    };

    // Centralized error handling (P0 refactor)
    if let Err(e) = result {
        // Handle clap errors
        if let Some(clap_err) = e.downcast_ref::<clap::Error>() {
            clap_err.print().ok();
            match clap_err.kind() {
                clap::error::ErrorKind::DisplayHelp | clap::error::ErrorKind::DisplayVersion => {
                    std::process::exit(0);
                }
                _ => {
                    std::process::exit(2);
                }
            }
        }

        // Handle ServeError with rich formatting
        if let Some(serve_err) = e.downcast_ref::<crate::serve::error::ServeError>() {
            eprintln!("{}", serve_err.format_source_pointed());
            std::process::exit(serve_err.exit_code());
        }

        // Generic error format
        eprintln!("{}: {}", "error".red().bold(), e);
        std::process::exit(1);
    }

    Ok(())
}
