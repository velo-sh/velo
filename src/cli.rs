//! CLI module for Velo
//!
//! This module handles:
//! - Command-line argument parsing
//! - Command dispatch (run, info, zygote)
//! - Help and version display

use anyhow::Result;
use std::path::Path;

use crate::cache::{self, EnvCache};
use crate::zygote::{self, ZygoteLauncher};
use crate::{hardware, python, python_info, runner};

pub const USAGE: &str = "\
velo - The high-performance Python runtime for the AI era

USAGE:
    velo run [OPTIONS] <script.py>
    velo zygote <start|stop|status>
    velo info

COMMANDS:
    run      Run a Python script
    zygote   Manage Zygote pre-warming daemon
    info     Show environment information

RUN OPTIONS:
    --zygote   Use Zygote for fast startup (auto-starts if needed)
    --profile  Show detailed startup timing breakdown

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

    if !socket_path.exists() {
        eprintln!("🚀 Starting Zygote...");
        if let Err(e) = launcher.start(&[]) {
            eprintln!("⚠️ Failed to start Zygote: {}", e);
            eprintln!("   Falling back to normal mode");
            return Ok(None);
        }
        eprintln!("✅ Zygote ready");
    }

    // Try to spawn via Zygote
    if socket_path.exists() {
        match launcher.spawn_worker(script, &[]) {
            Ok(worker) => {
                eprintln!("⚡ Running via Zygote (PID: {})", worker.pid());
                return Ok(Some(()));
            }
            Err(e) => {
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
        subcmd => {
            eprintln!("Error: unknown zygote subcommand '{}'", subcmd);
            eprintln!("Usage: velo zygote <start|stop|status>");
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
