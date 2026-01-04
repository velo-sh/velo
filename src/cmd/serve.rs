//! Handle 'velo serve' command

use anyhow::Result;
use std::path::{Path, PathBuf};

use crate::python;
use crate::serve::{self, LogFormat, ServeArgs, ServeError};
use regex::Regex;

/// Handle 'velo serve' command
pub fn cmd_serve(args: &[String]) -> Result<()> {
    // Handle --help early
    if args.len() >= 3 && (args[2] == "--help" || args[2] == "-h") {
        print_serve_help();
        std::process::exit(0);
    }

    if args.len() < 3 {
        eprintln!("Error: missing app argument");
        eprintln!("Usage: velo serve <app> [OPTIONS]");
        eprintln!("Example: velo serve main:app --workers 4");
        eprintln!("\nRun 'velo serve --help' for more information");
        std::process::exit(1);
    }

    // Parse arguments
    let mut serve_args = ServeArgs::new(args[2].clone());
    let mut i = 3;

    while i < args.len() {
        match args[i].as_str() {
            "--host" => {
                i += 1;
                if i >= args.len() {
                    eprintln!("Error: --host requires a value");
                    std::process::exit(1);
                }
                serve_args.host = args[i].clone();
            }
            "--port" => {
                i += 1;
                if i >= args.len() {
                    eprintln!("Error: --port requires a value");
                    std::process::exit(1);
                }
                serve_args.port = args[i].parse().unwrap_or_else(|_| {
                    eprintln!("Error: invalid port number '{}'", args[i]);
                    std::process::exit(1);
                });
            }
            // --bind is shorthand for --host:--port (e.g., --bind 0.0.0.0:8080)
            "--bind" => {
                i += 1;
                if i >= args.len() {
                    eprintln!("Error: --bind requires a value (e.g., 0.0.0.0:8080)");
                    std::process::exit(1);
                }
                if let Some((host, port)) = args[i].rsplit_once(':') {
                    serve_args.host = host.to_string();
                    serve_args.port = port.parse().unwrap_or_else(|_| {
                        eprintln!("Error: invalid port in bind address '{}'", args[i]);
                        std::process::exit(1);
                    });
                } else {
                    eprintln!("Error: --bind requires HOST:PORT format (e.g., 0.0.0.0:8080)");
                    std::process::exit(1);
                }
            }
            "--workers" => {
                i += 1;
                if i >= args.len() {
                    eprintln!("Error: --workers requires a value");
                    std::process::exit(1);
                }
                serve_args.workers = args[i].parse().unwrap_or_else(|_| {
                    eprintln!("Error: invalid worker count '{}'", args[i]);
                    std::process::exit(1);
                });
            }
            "--timeout" => {
                i += 1;
                if i >= args.len() {
                    eprintln!("Error: --timeout requires a value (seconds)");
                    std::process::exit(1);
                }
                serve_args.timeout = args[i].parse().unwrap_or_else(|_| {
                    eprintln!("Error: invalid timeout '{}'", args[i]);
                    std::process::exit(1);
                });
            }
            "--health-bind" => {
                i += 1;
                if i >= args.len() {
                    eprintln!("Error: --health-bind requires a value (e.g., 0.0.0.0:8081)");
                    std::process::exit(1);
                }
                serve_args.health_bind = Some(args[i].clone());
            }
            "--pid-file" => {
                i += 1;
                if i >= args.len() {
                    eprintln!("Error: --pid-file requires a path");
                    std::process::exit(1);
                }
                serve_args.pid_file = Some(PathBuf::from(&args[i]));
            }
            "--log-format" => {
                i += 1;
                if i >= args.len() {
                    eprintln!("Error: --log-format requires a value (text or json)");
                    std::process::exit(1);
                }
                serve_args.log_format = match args[i].as_str() {
                    "text" => LogFormat::Text,
                    "json" => LogFormat::Json,
                    other => {
                        eprintln!(
                            "Error: unknown log format '{}'. Use 'text' or 'json'",
                            other
                        );
                        std::process::exit(1);
                    }
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
                // Suggest similar flags using strsim
                suggest_similar_flag(arg);
                std::process::exit(1);
            }
            _ => {
                // Unexpected positional argument
                eprintln!("Error: unexpected argument '{}'", args[i]);
                std::process::exit(1);
            }
        }
        i += 1;
    }

    // Apply prod mode settings (disables reload, auto workers)
    serve_args.apply_prod_mode();

    // SEC-P0-001: Validate app target for shell injection (ADR D1)
    // Fail-fast: reject malicious input before ANY subprocess work
    validate_app_target(&serve_args.app)?;

    // Validate app format
    if !serve_args.app.contains(':') {
        eprintln!("Error: invalid app format '{}'", serve_args.app);
        eprintln!("Expected 'module:app' (e.g., 'main:app')");
        std::process::exit(1);
    }

    // Determine project directory
    let project_dir = std::env::current_dir().unwrap_or_else(|_| Path::new(".").to_path_buf());

    // Detect user's Python
    let python_path = python::detect_python(&project_dir)?;

    // Run the server
    serve::run_server(&serve_args, &python_path, &project_dir)?;

    Ok(())
}

/// SEC-P0-001: Validate app target for shell injection prevention (ADR D1)
///
/// Rejects shell metacharacters that could enable command injection.
/// Uses strict allowlist regex per RFC-0010 SEC-P0-001.
fn validate_app_target(app: &str) -> Result<()> {
    // RFC-0010 SEC-P0-001: Strict regex for app format
    // Allow: module.path:object OR module.path:factory()
    let re = Regex::new(r"^[a-zA-Z_][a-zA-Z0-9_.]*:[a-zA-Z_][a-zA-Z0-9_]*(\(\))?$").unwrap();

    if !re.is_match(app) {
        // Fallback check for common shell metacharacters to give better error message
        const FORBIDDEN: &[char] = &[
            '|', '&', ';', '$', '`', '\\', '"', '\'', '<', '>', '\n', '\r', '\0',
        ];

        if app.chars().any(|c| FORBIDDEN.contains(&c)) {
            let err = ServeError::ShellMetacharacters {
                app: app.to_string(),
            };
            eprintln!("{}", err.format_source_pointed());
            std::process::exit(err.exit_code());
        }

        // Generic invalid format error if regex fails but no dangerous chars
        // This enforces the "module:app" structure strictly
        eprintln!("Error: invalid app format '{}'", app);
        eprintln!(
            "Expected 'module:app' (e.g., 'main:app') matching regex: {}",
            re.as_str()
        );
        std::process::exit(1);
    }

    Ok(())
}

/// SEC-P0-002: Path Traversal Protection (RFC §4.10.2)
///
/// Ensures auto-discovery scanning does not escape project directory.
#[allow(dead_code)] // Currently helper for future auto-discovery usage
fn validate_scan_path(path: &Path, project_dir: &Path) -> Result<PathBuf> {
    let canonical = path
        .canonicalize()
        .map_err(|e| anyhow::anyhow!("Invalid path: {}", e))?;
    let project = project_dir
        .canonicalize()
        .map_err(|e| anyhow::anyhow!("Invalid project dir: {}", e))?;

    // Must be within project directory
    if !canonical.starts_with(&project) {
        let err = ServeError::PathTraversal {
            path: path.to_path_buf(),
        };
        // We return anyhow::Result to match cmd_serve signature if used there,
        // but strictly we should use ServeError.
        // Since cmd_serve uses anyhow, we'll convert.
        anyhow::bail!(err);
    }

    Ok(canonical)
}

/// Suggest similar flags for typos (D11, RFC §4.12.2)
fn suggest_similar_flag(unknown: &str) {
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

    eprintln!("Error: unknown option '{}'", unknown);
    if let Some((suggestion, _)) = best_match {
        eprintln!("       Did you mean '{}'?", suggestion);
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_validate_app_target_valid() {
        assert!(validate_app_target("main:app").is_ok());
        assert!(validate_app_target("my_module:app").is_ok());
        assert!(validate_app_target("pkg.mod:app").is_ok());
        assert!(validate_app_target("main:create_app()").is_ok());
    }

    #[test]
    fn test_validate_app_target_invalid_regex() {
        // These should fail regex check
        // "main:app;" is caught by fallback shell check too, but regex is first line of defense
        // "main:app " (space) is caught by regex
        // "1main:app" (invalid start char)

        // We can't easily assert exit(1) in unit tests without a harness,
        // but we can check the regex directly since validate_app_target uses exit()
        let re = Regex::new(r"^[a-zA-Z_][a-zA-Z0-9_.]*:[a-zA-Z_][a-zA-Z0-9_]*(\(\))?$").unwrap();

        assert!(!re.is_match("1main:app"));
        assert!(!re.is_match("main:app "));
        assert!(!re.is_match("main:app;"));
        assert!(!re.is_match("../main:app"));
    }

    #[test]
    fn test_validate_scan_path() {
        use std::fs::File;
        use tempfile::tempdir;

        let dir = tempdir().unwrap();
        let project_dir = dir.path();
        let file_path = project_dir.join("test.txt");
        File::create(&file_path).unwrap();

        // Valid path inside project
        assert!(validate_scan_path(&file_path, project_dir).is_ok());

        // Invalid path outside project
        let outside_dir = tempdir().unwrap();
        let outside_file = outside_dir.path().join("evil.txt");
        File::create(&outside_file).unwrap();

        // This should fail
        assert!(validate_scan_path(&outside_file, project_dir).is_err());
    }
}
