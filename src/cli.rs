//! CLI module for Velo
//!
//! This module handles:
//! - Command-line argument parsing
//! - Command dispatch (run, info, zygote, serve)
//! - Help and version display

use anyhow::Result;

use crate::cmd;

pub const USAGE: &str = "\
velo - The high-performance Python runtime for the AI era

USAGE:
    velo run [OPTIONS] <script.py>
    velo serve <app> [OPTIONS]
    velo analyze [OPTIONS] [file.py]
    velo zygote <start|stop|status|auto-config>
    velo info

COMMANDS:
    run      Run a Python script
    serve    Serve a Python ASGI/WSGI application
    analyze  Analyze import times and suggest optimizations
    zygote   Manage Zygote pre-warming daemon
    info     Show environment information

RUN OPTIONS:
    --zygote   Use Zygote for fast startup (auto-starts if needed)
    --profile  Show detailed startup timing breakdown

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

ZYGOTE SUBCOMMANDS:
    start        Start Zygote daemon
    stop         Stop Zygote daemon
    status       Show Zygote status
    auto-config  Generate preload config from profile data

OPTIONS:
    -h, --help     Print help
    -V, --version  Print version
";

/// Main entry point for CLI
pub fn run() -> Result<()> {
    let args: Vec<String> = std::env::args().collect();

    if args.len() < 2 {
        print!("{}", USAGE);
        std::process::exit(0);
    }

    match args[1].as_str() {
        "-h" | "--help" => {
            print!("{}", USAGE);
            std::process::exit(0);
        }
        "-V" | "--version" => {
            println!("velo {}", env!("CARGO_PKG_VERSION"));
            std::process::exit(0);
        }
        "run" => cmd::cmd_run(&args)?,
        "serve" => cmd::cmd_serve(&args)?,
        "analyze" => cmd::cmd_analyze(&args)?,
        "info" => cmd::cmd_info()?,
        "zygote" => cmd::cmd_zygote(&args)?,
        cmd => {
            eprintln!("Error: unknown command '{}'", cmd);
            eprintln!("{}", USAGE);
            std::process::exit(1);
        }
    }

    Ok(())
}
