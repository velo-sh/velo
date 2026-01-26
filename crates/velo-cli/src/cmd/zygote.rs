//! Handle 'velo zygote' command and subcommands
//!
//! Uses clap for argument parsing with derive macros.

use anyhow::{Result, bail};
use clap::{Parser, Subcommand};
use std::path::Path;

use velo_core::common::paths::VeloPaths;

use velo_core::zygote::ZygoteLauncher;

/// Zygote daemon management
#[derive(Parser, Debug)]
#[command(name = "zygote", about = "Manage Zygote pre-warming daemon")]
pub struct ZygoteCmd {
    #[command(subcommand)]
    pub command: ZygoteSubcommand,
}

#[derive(Subcommand, Debug)]
pub enum ZygoteSubcommand {
    /// Start Zygote daemon
    Start {
        /// Comma-separated list of modules to preload
        #[arg(long)]
        preload: Option<String>,
        /// Run in daemon mode (non-blocking)
        #[arg(long, default_value_t = false)]
        daemon: bool,
    },
    /// Stop Zygote daemon
    Stop,
    /// Show Zygote status
    Status,
    /// Generate preload config from profile data
    AutoConfig,
    /// Fork a new worker from Zygote
    Fork {
        /// Script path to execute
        #[arg(long)]
        script: String,
        /// Arguments to pass to the script
        #[arg(long)]
        arg: Vec<String>,
        /// Whether to return immediately
        #[arg(long, default_value_t = false)]
        async_mode: bool,
        /// Environment variables to set (NAME=VALUE)
        #[arg(long)]
        env: Vec<String>,
        /// Project root directory for worker CWD (defaults to current dir)
        #[arg(long)]
        project_root: Option<String>,
    },
}

/// Handle 'velo zygote' command (entry point from cli.rs)
pub fn cmd_zygote(args: &[String]) -> Result<()> {
    // Parse with clap - skip "velo" prefix
    let cmd = ZygoteCmd::try_parse_from(&args[1..])?;

    let project_dir = std::env::current_dir().unwrap_or_else(|_| Path::new(".").to_path_buf());

    match cmd.command {
        ZygoteSubcommand::Start { preload, daemon } => {
            cmd_zygote_start(&project_dir, preload, daemon)
        }
        ZygoteSubcommand::Stop => {
            cmd_zygote_stop();
            Ok(())
        }
        ZygoteSubcommand::Status => {
            cmd_zygote_status();
            Ok(())
        }
        ZygoteSubcommand::AutoConfig => cmd_zygote_auto_config(),
        ZygoteSubcommand::Fork {
            script,
            arg,
            async_mode,
            env,
            project_root,
        } => {
            let fork_project_dir = project_root
                .map(|p| Path::new(&p).to_path_buf())
                .unwrap_or(project_dir);
            cmd_zygote_fork(&fork_project_dir, &script, &arg, &env, async_mode)
        }
    }
}

fn cmd_zygote_fork(
    project_dir: &Path,
    script: &str,
    args: &[String],
    env_vars: &[String],
    async_mode: bool,
) -> Result<()> {
    let socket_path = velo_core::zygote::core_ipc::default_socket_path();
    if !socket_path.exists() {
        bail!("Zygote is not running. Start it with 'velo zygote start'");
    }

    let config =
        velo_core::config::VeloConfig::load_with_overrides(&VeloPaths::pyproject(project_dir));
    let mut launcher = ZygoteLauncher::new(socket_path);

    let script_path = Path::new(script);
    let args_slice: Vec<&str> = args.iter().map(|s| s.as_str()).collect();

    let mut env_overrides = std::collections::HashMap::new();
    for e in env_vars {
        if let Some((k, v)) = e.split_once('=') {
            env_overrides.insert(k.to_string(), v.to_string());
        }
    }

    let handle = launcher.spawn_worker(
        script_path,
        None, // module
        &args_slice,
        async_mode,
        false, // fast_mode
        None,  // bundle_path
        Some(project_dir.to_path_buf()),
        None, // max_bundle_size
        None, // shm_file
        Some(env_overrides),
        &config,
    )?;

    if async_mode {
        println!("🚀 Forked worker PID: {}", handle.pid());
    } else {
        match handle.wait() {
            Ok(code) => {
                // Read and re-emit worker output
                if let Some(stdout_path) = handle.stdout_path()
                    && let Ok(content) = std::fs::read_to_string(stdout_path)
                {
                    print!("{}", content);
                    let _ = std::io::Write::flush(&mut std::io::stdout());
                }
                if let Some(stderr_path) = handle.stderr_path()
                    && let Ok(content) = std::fs::read_to_string(stderr_path)
                {
                    eprint!("{}", content);
                    let _ = std::io::Write::flush(&mut std::io::stderr());
                }

                // P0-3: Correctly propagate exit code
                std::process::exit(code);
            }
            Err(e) => {
                bail!("Worker failed: {}", e);
            }
        }
    }

    Ok(())
}

#[cfg(unix)]
fn cmd_zygote_start(project_dir: &Path, preload_arg: Option<String>, daemon: bool) -> Result<()> {
    let python_path = velo_core::python::detect_python(project_dir)?;
    let socket_path = velo_core::zygote::core_ipc::default_socket_path();

    // SEC-005: Check both socket and auth file to determine if running
    let auth_path = VeloPaths::auth_file_for_socket(&socket_path);
    if socket_path.exists() && auth_path.exists() {
        println!("⚡ Zygote already running");
        println!("   Socket: {}", socket_path.display());
        return Ok(());
    } else if socket_path.exists() {
        // Socket exists but Auth missing -> Stale/Broken state
        // Fall through to let ZygoteLauncher::start() handle the healing/restart
        println!("⚠️  Zygote socket exists but auth file is missing. Attempting to heal...");
    } else {
        // Normal cold start case
    }
    #[cfg(unix)]
    if daemon {
        unsafe {
            match libc::fork() {
                -1 => anyhow::bail!("Fork failed"),
                0 => {
                    // Child: continues to start the Zygote
                    libc::setsid();
                    // Redirect IO to null in the daemonized process
                    // Redirect IO to log file in the daemonized process
                    let log_path = velo_core::common::paths::VeloPaths::zygote_log();
                    // Ensure logging directory exists
                    if let Some(parent) = log_path.parent() {
                        let _ = std::fs::create_dir_all(parent);
                    }

                    if let Ok(log_file) = std::fs::OpenOptions::new()
                        .create(true)
                        .append(true)
                        .open(&log_path)
                    {
                        let fd = std::os::unix::io::AsRawFd::as_raw_fd(&log_file);

                        // stdin -> /dev/null
                        if let Ok(null) = std::fs::File::open("/dev/null") {
                            let null_fd = std::os::unix::io::AsRawFd::as_raw_fd(&null);
                            libc::dup2(null_fd, 0);
                        }

                        // stdout -> log
                        libc::dup2(fd, 1);
                        // stderr -> log
                        libc::dup2(fd, 2);

                        // Leak file raw fd to keep it open across process lifetime
                        // (File object drop would try to close it, but dup2 makes copies)
                        // Actually, File drop closes original FD, but dup2'd FDs (1, 2) remain open.
                        // We must ensure 'log_file' lives long enough for dup2, which it does in this scope.
                    } else {
                        // Fallback to /dev/null if logging fails
                        if let Ok(null) = std::fs::File::open("/dev/null") {
                            let fd = std::os::unix::io::AsRawFd::as_raw_fd(&null);
                            libc::dup2(fd, 0);
                            libc::dup2(fd, 1);
                            libc::dup2(fd, 2);
                        }
                    }
                }
                _ => {
                    // Parent: exits immediately after reporting success
                    println!("🚀 Zygote daemonizing...");
                    return Ok(());
                }
            }
        }
    }
    let mut launcher = ZygoteLauncher::new(socket_path.clone()).with_python(python_path);

    // Parse --preload if provided
    let preload: Vec<&str> = preload_arg
        .as_ref()
        .map(|s| s.split(',').collect())
        .unwrap_or_default();

    let config =
        velo_core::config::VeloConfig::load_with_overrides(&VeloPaths::pyproject(project_dir));

    println!(
        "🚀 Starting Zygote{}...",
        if daemon { " daemon" } else { "" }
    );
    match launcher.start(&preload, None, daemon, &config) {
        Ok(()) => {
            log::info!(
                "[ZYGOTE] status=started socket={} preload={:?}",
                socket_path.display(),
                preload
            );
            println!("✅ Zygote started");
            println!("   Socket: {}", socket_path.display());

            if daemon {
                println!("🛡️  Guardian engaged. Press Ctrl+C to stop (or use 'velo zygote stop')");
            }

            // Keep launcher alive by forgetting it
            std::mem::forget(launcher);
        }
        Err(e) => {
            log::error!("[ZYGOTE] status=failed error={}", e);
            bail!("Failed to start Zygote: {}", e);
        }
    }
    Ok(())
}

#[cfg(not(unix))]
fn cmd_zygote_start(
    _project_dir: &Path,
    _preload_arg: Option<String>,
    _daemon: bool,
) -> Result<()> {
    bail!("Zygote not supported on this platform");
}

#[cfg(unix)]
fn cmd_zygote_stop() {
    let socket_path = velo_core::zygote::core_ipc::default_socket_path();

    if !socket_path.exists() {
        println!("ℹ️  Zygote not running");
    } else {
        println!("🛑 Stopping Zygote...");
        match velo_core::zygote::core_ipc::send_command(
            &socket_path,
            velo_core::zygote::core_ipc::ZygoteCommand::Shutdown,
            None,
        ) {
            Ok(_) => {
                println!("✅ Zygote stopped");
            }
            Err(e) => {
                eprintln!("⚠️  Error stopping Zygote: {}", e);
                velo_core::zygote::core_ipc::cleanup_socket(&socket_path);
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
    println!("▸ Zygote Status");
    match velo_core::zygote::get_status() {
        Ok(velo_core::zygote::core_ipc::ZygoteResponse::Status { pid, preload, .. }) => {
            println!("├─ Status: Running ✅ (PID: {})", pid);
            if preload.is_empty() {
                println!("└─ Preload: None");
            } else {
                println!(
                    "└─ Preload: ready ({} modules: {})",
                    preload.len(),
                    preload.join(", ")
                );
            }
        }
        Ok(resp) => {
            println!("├─ Status: Running ✅");
            println!("└─ Details: {:?}", resp);
        }
        Err(e) => {
            println!("└─ Status: Not running or unresponsive (Error: {})", e);
        }
    }
}

#[cfg(not(unix))]
fn cmd_zygote_status() {
    println!("▸ Zygote Status");
    println!("└─ Not supported on this platform");
}

/// Handle 'velo zygote auto-config' command
fn cmd_zygote_auto_config() -> Result<()> {
    use std::fs;
    use velo_core::zygote::auto_config::ZygoteConfig;

    let project_dir = std::env::current_dir()?;
    let profile_path = VeloPaths::zygote_profile(&project_dir);

    if !profile_path.exists() {
        bail!(
            "No profile data found.\n\n\
             To generate profile data, run:\n  \
             velo run --profile your_script.py\n\n\
             Then run auto-config again."
        );
    }

    let config = ZygoteConfig::from_profile_file(&profile_path)?;

    // Display summary
    println!("{}", config.summary());

    // Update pyproject.toml with [tool.velo] section
    let pyproject_path = VeloPaths::pyproject(&project_dir);

    if pyproject_path.exists() {
        let content = fs::read_to_string(&pyproject_path)?;
        if content.contains("[tool.velo]") {
            eprintln!("⚠️  [tool.velo] section already exists in pyproject.toml");
            eprintln!("   Please update manually with:");
            eprintln!("   preload = {:?}", config.preload);
        } else {
            // Append [tool.velo] section
            let new_content = format!("{}\n{}", content, config.to_toml());
            fs::write(&pyproject_path, new_content)?;
            println!(
                "📝 Updated: {} (added [tool.velo] section)",
                pyproject_path.display()
            );
        }
    } else {
        eprintln!("⚠️  No pyproject.toml found. Add this to your pyproject.toml:");
        println!("{}", config.to_toml());
    }

    if !config.preload.is_empty() {
        println!();
        println!("To start Zygote with these modules:");
        println!("  velo zygote start --preload {}", config.preload.join(","));
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_start_subcommand() {
        let cmd = ZygoteCmd::try_parse_from(["zygote", "start"]).unwrap();
        match cmd.command {
            ZygoteSubcommand::Start { preload, daemon } => {
                assert!(preload.is_none());
                assert!(!daemon);
            }
            _ => panic!("Expected Start subcommand"),
        }
    }

    #[test]
    fn test_parse_start_with_preload() {
        let cmd =
            ZygoteCmd::try_parse_from(["zygote", "start", "--preload", "fastapi,uvicorn"]).unwrap();
        match cmd.command {
            ZygoteSubcommand::Start { preload, daemon } => {
                assert_eq!(preload.unwrap(), "fastapi,uvicorn");
                assert!(!daemon);
            }
            _ => panic!("Expected Start subcommand"),
        }
    }

    #[test]
    fn test_parse_stop_subcommand() {
        let cmd = ZygoteCmd::try_parse_from(["zygote", "stop"]).unwrap();
        assert!(matches!(cmd.command, ZygoteSubcommand::Stop));
    }

    #[test]
    fn test_parse_status_subcommand() {
        let cmd = ZygoteCmd::try_parse_from(["zygote", "status"]).unwrap();
        assert!(matches!(cmd.command, ZygoteSubcommand::Status));
    }

    #[test]
    fn test_parse_auto_config_subcommand() {
        let cmd = ZygoteCmd::try_parse_from(["zygote", "auto-config"]).unwrap();
        assert!(matches!(cmd.command, ZygoteSubcommand::AutoConfig));
    }

    #[test]
    fn test_missing_subcommand_error() {
        let result = ZygoteCmd::try_parse_from(["zygote"]);
        assert!(result.is_err());
    }
}
