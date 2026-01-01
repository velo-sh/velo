//! CLI module for Velo
//!
//! This module handles:
//! - Command-line argument parsing
//! - Command dispatch (run, info, zygote, serve)
//! - Help and version display

use anyhow::Result;
use std::path::Path;

use crate::cache::{self, EnvCache};
use crate::serve::{self, ServeArgs};
use crate::zygote::{self, ZygoteLauncher};
use crate::{hardware, python, python_info, runner};

pub const USAGE: &str = "\
velo - The high-performance Python runtime for the AI era

USAGE:
    velo run [OPTIONS] <script.py>
    velo serve <app> [OPTIONS]
    velo zygote <start|stop|status|auto-config>
    velo info

COMMANDS:
    run      Run a Python script
    serve    Serve a Python ASGI/WSGI application
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
        "run" => cmd_run(&args)?,
        "serve" => cmd_serve(&args)?,
        "info" => cmd_info()?,
        "zygote" => cmd_zygote(&args)?,
        cmd => {
            eprintln!("Error: unknown command '{}'", cmd);
            eprintln!("{}", USAGE);
            std::process::exit(1);
        }
    }

    Ok(())
}

/// Handle 'velo run' command
#[allow(clippy::collapsible_if)]
fn cmd_run(args: &[String]) -> Result<()> {
    if args.len() < 3 {
        eprintln!("Error: missing script path");
        eprintln!("Usage: velo run [--zygote] [--profile] <script.py>");
        std::process::exit(1);
    }

    // Parse flags
    let mut zygote_enabled = false;
    let mut profile_enabled = false;
    let mut script_arg_idx = 2;

    for (i, arg) in args.iter().enumerate().skip(2) {
        match arg.as_str() {
            "--zygote" => {
                zygote_enabled = true;
                script_arg_idx = i + 1;
            }
            "--profile" => {
                profile_enabled = true;
                script_arg_idx = i + 1;
            }
            a if a.starts_with('-') => {
                eprintln!("Error: unknown option '{}'", a);
                std::process::exit(1);
            }
            _ => {
                script_arg_idx = i;
                break;
            }
        }
    }

    if script_arg_idx >= args.len() {
        eprintln!("Error: missing script path");
        eprintln!("Usage: velo run [--zygote] [--profile] <script.py>");
        std::process::exit(1);
    }

    // Determine project directory
    let project_dir = std::env::current_dir().unwrap_or_else(|_| Path::new(".").to_path_buf());

    // Detect user's Python
    let python_path = python::detect_python(&project_dir)?;

    // Zygote mode: use pre-warmed process
    if zygote_enabled {
        if let Some(()) = try_zygote_run(&python_path, &args[script_arg_idx])? {
            return Ok(());
        }
        // Fallback to normal mode if Zygote fails
    }

    // Normal mode (or fallback)
    let (pythonpath, needs_capture) = python::setup_python_env(&project_dir, &python_path);

    if profile_enabled {
        runner::run_script_with_profile(&python_path, &args[script_arg_idx], pythonpath)?;
    } else {
        runner::run_script(&python_path, &args[script_arg_idx], pythonpath)?;
    }

    // If we didn't have cache, capture sys.path for next time
    if needs_capture {
        save_cache_if_needed(&project_dir, &python_path);
    }

    Ok(())
}

/// Handle 'velo serve' command
fn cmd_serve(args: &[String]) -> Result<()> {
    if args.len() < 3 {
        eprintln!("Error: missing app argument");
        eprintln!("Usage: velo serve <app> [OPTIONS]");
        eprintln!("Example: velo serve main:app --workers 4");
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

/// Try to run via Zygote, returns Some(()) on success, None on failure
#[cfg(unix)]
fn try_zygote_run(python_path: &Path, script_path: &str) -> Result<Option<()>> {
    if !zygote::is_supported() {
        eprintln!("⚠️ Zygote not supported on this platform, using normal mode");
        return Ok(None);
    }

    let socket_path = zygote::ipc::default_socket_path();
    let script = Path::new(script_path);

    // Check if Zygote is running, start if not (hybrid mode)
    let mut launcher =
        ZygoteLauncher::new(socket_path.clone()).with_python(python_path.to_path_buf());

    let started_new = if !socket_path.exists() {
        eprintln!("🚀 Starting Zygote...");
        if let Err(e) = launcher.start(&[]) {
            eprintln!("⚠️ Failed to start Zygote: {}", e);
            eprintln!("   Falling back to normal mode");
            return Ok(None);
        }
        eprintln!("✅ Zygote ready");
        true
    } else {
        false
    };

    // Try to spawn via Zygote
    if socket_path.exists() {
        match launcher.spawn_worker(script, &[]) {
            Ok(worker) => {
                eprintln!("⚡ Running via Zygote (PID: {})", worker.pid());

                // Wait for worker to complete and get exit code
                let exit_code = worker.wait().unwrap_or(1);

                // Keep Zygote alive if we started it (daemon mode)
                if started_new {
                    std::mem::forget(launcher);
                }

                // Exit with worker's exit code (DEF-P3-013/014)
                std::process::exit(exit_code);
            }
            Err(e) => {
                // Check if this is a stale socket (connection refused)
                let is_stale = e.to_string().contains("Connection refused")
                    || e.to_string().contains("Connection failed");

                if is_stale && !started_new {
                    // Stale socket - remove and restart Zygote
                    eprintln!("🔄 Stale socket detected, restarting Zygote...");
                    zygote::ipc::cleanup_socket(&socket_path);

                    if let Ok(()) = launcher.start(&[]) {
                        eprintln!("✅ Zygote ready");

                        // Retry spawn
                        if let Ok(worker) = launcher.spawn_worker(script, &[]) {
                            eprintln!("⚡ Running via Zygote (PID: {})", worker.pid());
                            let exit_code = worker.wait().unwrap_or(1);
                            std::mem::forget(launcher);
                            std::process::exit(exit_code);
                        }
                    }
                }

                eprintln!("⚠️ Zygote spawn failed: {}", e);
                eprintln!("   Falling back to normal mode");
            }
        }
    }

    Ok(None)
}

#[cfg(not(unix))]
fn try_zygote_run(_python_path: &Path, _script_path: &str) -> Result<Option<()>> {
    eprintln!("⚠️ Zygote not supported on Windows, using normal mode");
    Ok(None)
}

/// Save cache after script execution
#[allow(clippy::collapsible_if)]
fn save_cache_if_needed(project_dir: &Path, python_path: &Path) {
    if let Some(fingerprint) = EnvCache::compute_fingerprint(project_dir) {
        if let Ok(paths) = python::capture_sys_path(python_path) {
            let (python_version, abi_tag, platform_tag) =
                match python_info::PythonInfo::detect(python_path) {
                    Ok(info) => (info.version, info.abi_tag, info.platform_tag),
                    Err(_) => (
                        python_info::PythonVersion::default(),
                        String::new(),
                        String::new(),
                    ),
                };

            let cache = EnvCache::new(
                fingerprint,
                paths,
                String::new(),
                python_version,
                abi_tag,
                platform_tag,
            );
            let _ = cache.save(project_dir);
        }
    }
}

/// Handle 'velo info' command
fn cmd_info() -> Result<()> {
    let project_dir = std::env::current_dir().unwrap_or_else(|_| Path::new(".").to_path_buf());

    println!("Velo {}", env!("CARGO_PKG_VERSION"));
    println!("══════════════════════════════════════════════════════════════\n");

    // Hardware info
    let hw_info = hardware::HardwareInfo::detect();
    println!("{}\n", hw_info.format());

    // Python environment
    if let Ok(python_path) = python::detect_python(&project_dir) {
        println!("▸ Python Environment");
        println!("├─ Path:    {}", python_path.display());
        if let Ok(info) = python_info::PythonInfo::detect(&python_path) {
            println!("├─ Version: {}", info.version);
            println!("├─ ABI:     {}-{}", info.abi_tag, info.platform_tag);
        }
        println!();
    } else {
        println!("▸ Python Environment");
        println!("└─ Not detected (no .venv or VELO_PYTHON set)\n");
    }

    // Cache status
    println!("▸ Cache Status");
    let cache_dir = cache::EnvCache::cache_dir(&project_dir);
    if cache_dir.exists() {
        if let Some(fingerprint) = EnvCache::compute_fingerprint(&project_dir) {
            if let Some(cache) = EnvCache::load(&project_dir, &fingerprint) {
                println!("├─ Location:    {}", cache_dir.display());
                println!("├─ Fingerprint: {}...", &fingerprint[..16]);
                println!(
                    "├─ Python:      {} ({})",
                    cache.python_version, cache.abi_tag
                );
                println!("├─ Version:     v{}", cache.cache_version);
                println!("└─ Status:      Valid ✅");
            } else {
                println!("├─ Location:    {}", cache_dir.display());
                println!("└─ Status:      Stale (fingerprint mismatch) ⚠️");
            }
        } else {
            println!("├─ Location:    {}", cache_dir.display());
            println!("└─ Status:      No uv.lock found");
        }
    } else {
        println!("└─ No cache (run a script first)");
    }

    Ok(())
}

/// Handle 'velo zygote' command
fn cmd_zygote(args: &[String]) -> Result<()> {
    if args.len() < 3 {
        eprintln!("Usage: velo zygote <start|stop|status>");
        std::process::exit(1);
    }

    let project_dir = std::env::current_dir().unwrap_or_else(|_| Path::new(".").to_path_buf());

    match args[2].as_str() {
        "start" => cmd_zygote_start(&project_dir, args)?,
        "stop" => cmd_zygote_stop(),
        "status" => cmd_zygote_status(),
        "auto-config" => cmd_zygote_auto_config()?,
        subcmd => {
            eprintln!("Error: unknown zygote subcommand '{}'", subcmd);
            eprintln!("Usage: velo zygote <start|stop|status|auto-config>");
            std::process::exit(1);
        }
    }

    Ok(())
}

#[cfg(unix)]
fn cmd_zygote_start(project_dir: &Path, args: &[String]) -> Result<()> {
    let python_path = python::detect_python(project_dir)?;
    let socket_path = zygote::ipc::default_socket_path();

    if socket_path.exists() {
        println!("⚡ Zygote already running");
        println!("   Socket: {}", socket_path.display());
    } else {
        let mut launcher = ZygoteLauncher::new(socket_path.clone()).with_python(python_path);

        // Parse --preload if provided
        let preload: Vec<&str> = if args.len() > 4 && args[3] == "--preload" {
            args[4].split(',').collect()
        } else {
            vec![]
        };

        println!("🚀 Starting Zygote daemon...");
        match launcher.start(&preload) {
            Ok(()) => {
                println!("✅ Zygote started");
                println!("   Socket: {}", socket_path.display());
                // Keep launcher alive by forgetting it (daemon mode)
                std::mem::forget(launcher);
            }
            Err(e) => {
                eprintln!("❌ Failed to start Zygote: {}", e);
                std::process::exit(1);
            }
        }
    }
    Ok(())
}

#[cfg(not(unix))]
fn cmd_zygote_start(_project_dir: &Path, _args: &[String]) -> Result<()> {
    eprintln!("❌ Zygote not supported on this platform");
    std::process::exit(1);
}

#[cfg(unix)]
fn cmd_zygote_stop() {
    let socket_path = zygote::ipc::default_socket_path();

    if !socket_path.exists() {
        println!("ℹ️  Zygote not running");
    } else {
        println!("🛑 Stopping Zygote...");
        match zygote::ipc::send_command(&socket_path, zygote::ipc::ZygoteCommand::Shutdown) {
            Ok(_) => {
                println!("✅ Zygote stopped");
            }
            Err(e) => {
                eprintln!("⚠️  Error stopping Zygote: {}", e);
                zygote::ipc::cleanup_socket(&socket_path);
                println!("   Socket cleaned up");
            }
        }
    }
}

#[cfg(not(unix))]
fn cmd_zygote_stop() {
    eprintln!("ℹ️  Zygote not supported on this platform");
}

#[cfg(unix)]
fn cmd_zygote_status() {
    let socket_path = zygote::ipc::default_socket_path();

    println!("▸ Zygote Status");
    if socket_path.exists() {
        println!("├─ Status: Running ✅");
        println!("└─ Socket: {}", socket_path.display());
    } else {
        println!("└─ Status: Not running");
    }
}

#[cfg(not(unix))]
fn cmd_zygote_status() {
    println!("▸ Zygote Status");
    println!("└─ Not supported on this platform");
}

/// Handle 'velo zygote auto-config' command
fn cmd_zygote_auto_config() -> Result<()> {
    use crate::zygote::auto_config::ZygoteConfig;
    use std::fs;

    let profile_path = std::env::temp_dir().join("velo_profile/profile.json");

    if !profile_path.exists() {
        eprintln!("❌ No profile data found.");
        eprintln!();
        eprintln!("To generate profile data, run:");
        eprintln!("  velo run --profile your_script.py");
        eprintln!();
        eprintln!("Then run auto-config again.");
        std::process::exit(1);
    }

    let config = ZygoteConfig::from_profile_file(&profile_path)?;

    // Display summary
    println!("{}", config.summary());

    // Write velo.toml
    let toml_content = config.to_toml();
    let toml_path = std::env::current_dir()?.join("velo.toml");

    fs::write(&toml_path, &toml_content)?;
    println!("📝 Generated: {}", toml_path.display());

    if !config.preload.is_empty() {
        println!();
        println!("To start Zygote with these modules:");
        println!("  velo zygote start --preload {}", config.preload.join(","));
    }

    Ok(())
}
