//! Handle 'velo serve' command

use anyhow::{Result, bail};
use std::path::{Path, PathBuf};

use crate::python;
use crate::serve;
use crate::serve::config::{LogFormat, ServeArgs};

/// Handle 'velo serve' command
pub fn cmd_serve(args: &[String]) -> Result<()> {
    // Handle --help early (this is the only acceptable exit point)
    if args.len() >= 3 && (args[2] == "--help" || args[2] == "-h") {
        print_serve_help();
        return Ok(());
    }

    // Parse arguments, returning Result instead of exit()
    let serve_args = parse_serve_args(args)?;

    // Determine project directory
    let project_dir = std::env::current_dir().unwrap_or_else(|_| Path::new(".").to_path_buf());

    // Detect user's Python
    let python_path = python::detect_python(&project_dir)?;

    // Run the server
    serve::run_server(&serve_args, &python_path, &project_dir)?;

    Ok(())
}

/// Parse serve command arguments into ServeArgs
/// Returns Result instead of calling exit()
fn parse_serve_args(args: &[String]) -> Result<ServeArgs> {
    if args.len() < 3 {
        bail!(
            "missing app argument\n\
             Usage: velo serve <app> [OPTIONS]\n\
             Example: velo serve main:app --workers 4\n\n\
             Run 'velo serve --help' for more information"
        );
    }

    let mut serve_args = ServeArgs::new(args[2].clone());
    let mut i = 3;

    while i < args.len() {
        match args[i].as_str() {
            "--host" => {
                i += 1;
                serve_args.host = require_value(args, i, "--host")?;
            }
            "--port" => {
                i += 1;
                let val = require_value(args, i, "--port")?;
                serve_args.port = val
                    .parse()
                    .map_err(|_| anyhow::anyhow!("invalid port number '{}'", val))?;
            }
            "--bind" => {
                i += 1;
                let val = require_value(args, i, "--bind")?;
                if let Some((host, port)) = val.rsplit_once(':') {
                    serve_args.host = host.to_string();
                    serve_args.port = port
                        .parse()
                        .map_err(|_| anyhow::anyhow!("invalid port in bind address '{}'", val))?;
                } else {
                    bail!("--bind requires HOST:PORT format (e.g., 0.0.0.0:8080)");
                }
            }
            "--workers" => {
                i += 1;
                let val = require_value(args, i, "--workers")?;
                serve_args.workers = val
                    .parse()
                    .map_err(|_| anyhow::anyhow!("invalid worker count '{}'", val))?;
            }
            "--timeout" => {
                i += 1;
                let val = require_value(args, i, "--timeout")?;
                serve_args.timeout = val
                    .parse()
                    .map_err(|_| anyhow::anyhow!("invalid timeout '{}'", val))?;
            }
            "--health-bind" => {
                i += 1;
                serve_args.health_bind = Some(require_value(args, i, "--health-bind")?);
            }
            "--pid-file" => {
                i += 1;
                let val = require_value(args, i, "--pid-file")?;
                serve_args.pid_file = Some(PathBuf::from(val));
            }
            "--log-format" => {
                i += 1;
                let val = require_value(args, i, "--log-format")?;
                serve_args.log_format = match val.as_str() {
                    "text" => LogFormat::Text,
                    "json" => LogFormat::Json,
                    other => bail!("unknown log format '{}'. Use 'text' or 'json'", other),
                };
            }
            "--reload" => {
                serve_args.reload = true;
            }
            "--prod" => {
                serve_args.prod = true;
            }
            "--no-zygote" => {
                serve_args.use_zygote = false;
            }
            arg if arg.starts_with('-') => {
                return Err(unknown_flag_error(arg));
            }
            other => {
                bail!("unexpected argument '{}'", other);
            }
        }
        i += 1;
    }

    // Apply prod mode settings (disables reload, auto workers)
    serve_args.apply_prod_mode();

    // SEC-P0-001: Validate app target for shell injection (ADR D1)
    serve_args.validate()?;

    // Validate app format
    if !serve_args.app.contains(':') {
        bail!(
            "invalid app format '{}'\nExpected 'module:app' (e.g., 'main:app')",
            serve_args.app
        );
    }

    Ok(serve_args)
}

/// Helper: require a value for a flag, return Result
fn require_value(args: &[String], i: usize, flag: &str) -> Result<String> {
    args.get(i)
        .cloned()
        .ok_or_else(|| anyhow::anyhow!("{} requires a value", flag))
}

/// Helper: create error for unknown flag with suggestion
fn unknown_flag_error(unknown: &str) -> anyhow::Error {
    use strsim::jaro_winkler;

    const VALID_FLAGS: &[&str] = &[
        "--host",
        "--port",
        "--bind",
        "--workers",
        "--timeout",
        "--health-bind",
        "--pid-file",
        "--log-format",
        "--reload",
        "--prod",
        "--no-zygote",
        "--help",
    ];

    let unknown_lower = unknown.to_lowercase();
    let mut best_match: Option<(&str, f64)> = None;

    for flag in VALID_FLAGS {
        let score = jaro_winkler(&unknown_lower, flag);
        if score > 0.8 && (best_match.is_none() || score > best_match.unwrap().1) {
            best_match = Some((flag, score));
        }
    }

    if let Some((suggestion, _)) = best_match {
        anyhow::anyhow!(
            "unknown option '{}'\n       Did you mean '{}'?",
            unknown,
            suggestion
        )
    } else {
        anyhow::anyhow!("unknown option '{}'", unknown)
    }
}

/// Print help for serve command
fn print_serve_help() {
    eprintln!(
        "velo serve - Serve a Python ASGI/WSGI application

USAGE:
    velo serve <app> [OPTIONS]

ARGUMENTS:
    <app>    Application path (e.g., 'main:app', 'myapp.main:create_app()')

OPTIONS:
    --host <HOST>         Bind host (default: 127.0.0.1)
    --port <PORT>         Bind port (default: 8000)
    --bind <HOST:PORT>    Shorthand for --host and --port
    --workers <N>         Number of workers (default: 1, auto in --prod)
    --timeout <SECS>      Graceful shutdown timeout (default: 30)
    --health-bind <ADDR>  Health check endpoint (e.g., 0.0.0.0:8081)
    --pid-file <PATH>     Write PID file for process management
    --log-format <FMT>    Output format: text (default) or json
    --reload              Enable hot reload (disabled in --prod)
    --prod                Production mode (no reload, auto workers)
    --no-zygote           Disable Zygote pre-warming
    -h, --help            Print this help

EXAMPLES:
    velo serve main:app
    velo serve main:app --bind 0.0.0.0:8080 --reload
    velo serve main:app --prod --health-bind 0.0.0.0:8081
    velo serve main:app --workers 4 --timeout 60

NOTE:
    Requires uvicorn (ASGI) or gunicorn (WSGI) to be installed.
    Run: uv add uvicorn"
    );
}
