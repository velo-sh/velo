//! Handle 'velo serve' command

use anyhow::Result;
use std::path::Path;

use crate::python;
use crate::serve::{self, ServeArgs};

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
            "--reload" => {
                serve_args.reload = true;
            }
            "--no-zygote" => {
                serve_args.use_zygote = false;
            }
            arg if arg.starts_with('-') => {
                eprintln!("Error: unknown option '{}'", arg);
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

/// Print help for serve command
fn print_serve_help() {
    eprintln!(
        "velo serve - Serve a Python ASGI/WSGI application

USAGE:
    velo serve <app> [OPTIONS]

ARGUMENTS:
    <app>    Application path (e.g., 'main:app', 'myapp.main:create_app()')

OPTIONS:
    --host <HOST>    Bind host (default: 127.0.0.1)
    --port <PORT>    Bind port (default: 8000)
    --workers <N>    Number of workers (default: 1)
    --reload         Enable hot reload
    --no-zygote      Disable Zygote pre-warming
    -h, --help       Print this help

EXAMPLES:
    velo serve main:app
    velo serve main:app --port 9000 --reload
    velo serve main:app --workers 4 --no-zygote

NOTE:
    Requires uvicorn to be installed. Run: uv add uvicorn"
    );
}
